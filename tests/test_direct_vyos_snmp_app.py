"""VyOS runs GMCS test locally; LibreNMS polls cached measurements without running commands."""
from __future__ import annotations
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'integrations' / 'vyos-snmp-direct'


def load(path, name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def config():
    return {'inside': {'enabled':True,'url':'https://10.250.31.192:18443',
                       'agent_id':'CDE-VYOS01',
                       'token_file':'/config/auth/gmcs-speedtest/token',
                       'ca_file':'/config/auth/gmcs-speedtest/ca.pem'}}


def test_configuration_rejects_ookla_plain_http_and_bad_paths():
    m=load('collect.py','direct_collect_a')
    c=config();assert m.validated(c)==c
    invalid=[c|{'ookla':{'enabled':True}},c|{'shell':'id'},
            {'inside':dict(c['inside'],url='http://10.250.31.192:18443')},
            {'inside':dict(c['inside'],url='https://x/?command=bad')},
            {'inside':dict(c['inside'],token_file='/tmp/key')},
            {'inside':dict(c['inside'],agent_id='CDE;sh')},
            {'inside':dict(c['inside'],ca_file='/config/auth/gmcs-speedtest/../other')}]
    for cfg in invalid:
        with pytest.raises(ValueError):m.validated(cfg)


def test_local_measurement_and_outbound_gmcs_only():
    m=load('collect.py','direct_collect_b')
    seen=[]
    def fake(cmd,**kwargs):
        seen.extend(cmd)
        return SimpleNamespace(returncode=0,stdout=json.dumps({'agent_id':'CDE-VYOS01',
            'download_mbps':46.3,'upload_mbps':25.5,'latency_ms':8.4,
            'jitter_ms':1.2,'packet_loss_pct':0}))
    result=m.measure(config()['inside'],script=Path('/config/scripts/gmcs-speedtest/school_agent.py'),run_command=fake)
    assert result['status']=='ok' and result['download_mbps']==46.3 and result['loss_pct']==0
    assert '--url' in seen and '--token-file' in seen
    assert all('ookla' not in str(v).lower() for v in seen)


def test_failed_local_measurement_is_null_not_zero():
    m=load('collect.py','direct_collect_c')
    def failed(cmd,**kw):return SimpleNamespace(returncode=1,stdout='',stderr='')
    assert m.measure(config()['inside'],run_command=failed)=={'status':'failed'}
    assert m.measure({'enabled':False})=={'status':'disabled'}


def test_snmp_reads_cache_no_network_no_credentials(tmp_path):
    m=load('collect.py','direct_collect_d')
    x=load('extend.py','direct_snmp_d')
    stamp=int(time.time())
    file=tmp_path/'latest.json'
    m.persist(file,{'version':1,'at':stamp,'inside':{'status':'ok',
        'download_mbps':82.2,'upload_mbps':43.3,'latency_ms':5.0,'jitter_ms':1.1,'loss_pct':0}})
    assert (file.stat().st_mode & 0o777)==0o644
    out=json.loads(x.render(file,now=stamp))
    assert out['data']['download_mbps']==82.2
    assert out['data']['loss_pct']==0
    assert out['version']==1 and out['error']==0
    assert 'token' not in json.dumps(out)
    stale=json.loads(x.render(file,now=stamp+10000))
    assert stale['data']['status']=='stale'
    assert all(stale['data'][k] is None for k in x.FIELDS)
    missing=json.loads(x.render(tmp_path/'missing',now=stamp))
    assert missing['data']['status']=='missing'
    assert all(missing['data'][k] is None for k in x.FIELDS)


def test_native_app_rrd_schema_and_no_ookla():
    base=Path(__file__).resolve().parents[1]/'integrations/librenms-app/gmcs_vyos_speedtest'
    p=(base/'includes/polling/applications/gmcs_vyos_speedtest.inc.php').read_text()
    assert 'json_app_get($device, $name, 1)' in p
    for field in ('inside_down','inside_up','inside_ping','inside_jitter','inside_loss'):
        assert field in p
    assert 'ookla' not in p.lower()
    for graph in ('local_bandwidth','local_ping','local_loss'):
        assert (base/f'includes/html/graphs/application/gmcs_vyos_speedtest_{graph}.inc.php').is_file()
    assert 'Ookla' not in (base/'includes/html/pages/device/apps/gmcs_vyos_speedtest.inc.php').read_text().replace('the existing Ookla application remains untouched.','')
