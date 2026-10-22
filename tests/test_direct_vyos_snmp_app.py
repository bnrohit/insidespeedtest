"""Non-network regression: router measures; SNMP reads sanitized cache; RRD mapping stable."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'integrations' / 'vyos-snmp-direct'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_validated_and_forbidden_values():
    m = load('collect.py', 'gmcs_router_collect')
    cfg = {'inside': {'enabled': True, 'url': 'https://10.250.31.192:18443',
                      'agent_id': 'CDE-VYOS01',
                      'token_file': '/config/auth/gmcs-speedtest/token',
                      'ca_file': '/config/auth/gmcs-speedtest/ca.pem'},
           'ookla': {'enabled': True, 'binary': '/usr/bin/speedtest'}}
    assert m.validated(cfg) == cfg
    for broken in [cfg | {'shell': 'echo test'},
                   {'inside': dict(cfg['inside'], url='http://10.250.31.192:18443')},
                   {'inside': dict(cfg['inside'], token_file='/tmp/exposed')},
                   {'inside': dict(cfg['inside'], url='https://x/?command=bad')},
                   {'ookla': {'enabled': True, 'binary': '/tmp/custom'}}]:
        with pytest.raises(ValueError):
            m.validated(broken)


def test_inside_test_launches_on_router_only():
    m = load('collect.py', 'gmcs_router_collect2')
    cmd_seen = []
    def fake(cmd, **kwargs):
        cmd_seen.extend(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'agent_id': 'CDE-VYOS01', 'download_mbps': 75,
            'upload_mbps': 46, 'latency_ms': 7.2, 'jitter_ms': 1.1,
            'packet_loss_pct': 0}))
    r = m.inside_result({'enabled': True, 'url': 'https://gmcs.test',
         'agent_id': 'CDE-VYOS01','token_file': '/config/auth/gmcs-speedtest/token'},
         agent_script=Path('/config/scripts/gmcs-speedtest/school_agent.py'),
         subprocess_run=fake)
    assert r['status'] == 'ok' and r['download_mbps'] == 75
    assert '75' not in cmd_seen and '--url' in cmd_seen
    assert '/config/scripts/gmcs-speedtest/school_agent.py' in cmd_seen


def test_ookla_json_is_bytes_per_second(monkeypatch, tmp_path):
    m = load('collect.py', 'gmcs_router_collect3')
    f = tmp_path/'speedtest';f.write_text('#!/bin/sh\n');f.chmod(0o755)
    def fake(cmd, **kwargs):
        assert cmd[-1] == '--format=json'
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'download': {'bandwidth': 12500000}, 'upload': {'bandwidth': 5000000},
            'ping': {'latency': 12.4, 'jitter': 1.7}, 'packetLoss': 0.2}))
    result = m.ookla_result({'enabled': True, 'binary': str(f)}, subprocess_run=fake)
    assert result == {'status':'ok','download_mbps':100.0,'upload_mbps':40.0,
                      'latency_ms':12.4,'jitter_ms':1.7,'loss_pct':0.2}
    def no_loss(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'download': {'bandwidth': 12500000}, 'upload': {'bandwidth': 5000000},
            'ping': {'latency': 12.4, 'jitter': 1.7}}))
    missing_loss = m.ookla_result({'enabled': True, 'binary': str(f)}, subprocess_run=no_loss)
    assert missing_loss['status'] == 'ok' and missing_loss['loss_pct'] is None
    assert m.ookla_result({'enabled':False})['status'] == 'disabled'
    assert m.ookla_result({'enabled':True,'binary':str(tmp_path/'missing')})['status'] == 'not_installed'


def test_cache_snmp_no_secrets_and_stale(tmp_path):
    collect = load('collect.py', 'gmcs_router_collect4')
    extend = load('extend.py', 'gmcs_router_snmp_extend')
    cache = tmp_path/'latest.json'
    now = int(time.time())
    collect.persist(cache, {'version': 1,'at': now,
        'inside': {'status': 'ok','download_mbps': 120, 'upload_mbps': 65,
                   'latency_ms': 7,'jitter_ms': 0.1, 'loss_pct':0},
        'ookla': {'status':'disabled'}})
    assert cache.stat().st_mode & 0o777 == 0o644
    raw = extend.render(cache, now=now)
    data = json.loads(raw)
    assert data['version'] == 1 and data['error'] == 0
    assert data['data']['inside']['download_mbps'] == 120
    assert data['data']['ookla']['download_mbps'] is None
    assert 'token' not in raw.lower() and '10.250.31' not in raw
    stale = json.loads(extend.render(cache, now=now+9900))
    assert stale['data']['inside']['download_mbps'] is None
    assert stale['data']['inside']['status'] == 'stale'
    missing = json.loads(extend.render(tmp_path/'missing.json', now=now))
    assert missing['data']['inside']['status'] == 'missing'


def test_app_graph_schema_present():
    lib = Path(__file__).resolve().parents[1]/'integrations'/'librenms-app'/'gmcs_vyos_speedtest'
    p=(lib/'includes'/'polling'/'applications'/'gmcs_vyos_speedtest.inc.php').read_text()
    assert "json_app_get($device, $name, 1)" in p
    for field in ('ookla_down','ookla_up','ookla_ping','ookla_jitter',
                  'inside_down','inside_up','inside_ping','inside_jitter'):
        assert field in p
    for file in ('ookla_bandwidth','ookla_ping','local_bandwidth','local_ping'):
        assert (lib/'includes'/'html'/'graphs'/'application'/f'gmcs_vyos_speedtest_{file}.inc.php').is_file()
