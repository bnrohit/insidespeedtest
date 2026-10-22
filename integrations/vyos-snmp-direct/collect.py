#!/usr/bin/env python3
"""VyOS-local scheduled measurements; LibreNMS polls a different cached SNMP extend.

No remote SSH or NOC test scheduler. Subprocesses execute only fixed, installed tools.
No private fields or credentials are written to the SNMP-visible report.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

DEFAULT_CONFIG = Path('/config/auth/gmcs-speedtest/direct.json')
DEFAULT_CACHE = Path('/config/user-data/gmcs-vyos-speedtest/latest.json')
DEFAULT_AGENT = Path('/config/scripts/gmcs-speedtest/school_agent.py')


def validated(config: dict) -> dict:
    if not isinstance(config, dict):
        raise ValueError('Configuration must be an object')
    supported = {'inside', 'ookla'}
    if set(config) - supported:
        raise ValueError('Unexpected keys in configuration')
    inside = config.get('inside', {})
    ookla = config.get('ookla', {})
    if not isinstance(inside, dict) or not isinstance(ookla, dict):
        raise ValueError('inside/ookla configuration must be objects')
    if set(inside) - {'enabled', 'url', 'agent_id', 'token_file', 'ca_file'}:
        raise ValueError('Unexpected inside settings')
    if set(ookla) - {'enabled', 'binary'}:
        raise ValueError('Unexpected Ookla settings')
    if type(inside.get('enabled', False)) is not bool or type(ookla.get('enabled', False)) is not bool:
        raise ValueError('enabled must be a boolean')
    if inside.get('enabled'):
        import urllib.parse
        url = urllib.parse.urlsplit(inside.get('url', ''))
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in ('', '/')):
            raise ValueError('Internal test requires an HTTPS URL with a trusted certificate')
        from re import fullmatch
        if not fullmatch('[A-Za-z0-9_.-]{1,64}', inside.get('agent_id', '')):
            raise ValueError('Invalid school agent ID')
        if not inside.get('token_file', '').startswith('/config/auth/gmcs-speedtest/'):
            raise ValueError('Token file must remain under private VyOS config')
        ca = inside.get('ca_file', '')
        if ca and not ca.startswith('/config/auth/gmcs-speedtest/'):
            raise ValueError('CA bundle must remain under approved router config')
    binary = ookla.get('binary', '/usr/bin/speedtest')
    if binary not in ('/usr/bin/speedtest', '/usr/local/bin/speedtest'):
        raise ValueError('Only preinstalled, approved Ookla binaries are permitted')
    return {'inside': inside, 'ookla': ookla}


def numeric(value, low=0, high=100000):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    n = float(value)
    return round(n, 3) if math.isfinite(n) and low <= n <= high else None


def inside_result(config, agent_script=DEFAULT_AGENT, subprocess_run=subprocess.run):
    result = {'status': 'disabled'}
    if not config.get('enabled', False):
        return result
    ca = config.get('ca_file', '')
    cmd = [sys.executable, str(agent_script), '--url', config['url'],
           '--agent-id', config['agent_id'], '--token-file', config['token_file'],
           '--download-seconds', '3', '--upload-seconds', '3', '--download-max-mib', '24',
           '--upload-max-mib', '8', '--chunk-mib', '2', '--request-timeout', '25']
    if ca:
        cmd += ['--ca-file', ca]
    try:
        p = subprocess_run(cmd, capture_output=True, text=True, timeout=165, check=False)
        if p.returncode:
            return {'status': 'failed'}
        data = json.loads(p.stdout.strip().splitlines()[-1])
        fields = {'download_mbps': numeric(data.get('download_mbps')),
                  'upload_mbps': numeric(data.get('upload_mbps')),
                  'latency_ms': numeric(data.get('latency_ms'), high=60000),
                  'jitter_ms': numeric(data.get('jitter_ms'), high=60000),
                  'loss_pct': numeric(data.get('packet_loss_pct'), high=100)}
        if data.get('agent_id') != config['agent_id'] or any(v is None for v in fields.values()):
            return {'status': 'invalid'}
        return {'status': 'ok', **fields}
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, KeyError, IndexError):
        return {'status': 'failed'}


def ookla_result(config, subprocess_run=subprocess.run):
    if not config.get('enabled', False):
        return {'status': 'disabled'}
    binary = config.get('binary', '/usr/bin/speedtest')
    if not Path(binary).is_file() or not os.access(binary, os.X_OK):
        return {'status': 'not_installed'}
    try:
        # The district administrator must install/accept Ookla's license separately.
        p = subprocess_run([binary, '--format=json'], capture_output=True,
                           text=True, timeout=165, check=False)
        if p.returncode:
            return {'status': 'failed'}
        data = json.loads(p.stdout)
        # Ookla JSON bandwidth is bytes/sec (not Mbps).
        down_bytes = numeric(data.get('download', {}).get('bandwidth'), high=12_500_000_000)
        up_bytes = numeric(data.get('upload', {}).get('bandwidth'), high=12_500_000_000)
        down = numeric(down_bytes * 8 / 1_000_000) if down_bytes is not None else None
        up = numeric(up_bytes * 8 / 1_000_000) if up_bytes is not None else None
        ping = data.get('ping') or {}
        values = {'download_mbps': down, 'upload_mbps': up,
                  'latency_ms': numeric(ping.get('latency'), high=60000),
                  'jitter_ms': numeric(ping.get('jitter'), high=60000),
                  'loss_pct': numeric(data.get('packetLoss'), high=100)}
        # Some Ookla releases do not report packet loss; do not erase
        # valid throughput just because an optional metric is absent.
        if down is None or up is None:
            return {'status': 'invalid'}
        return {'status': 'ok', **values}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, AttributeError):
        return {'status': 'failed'}


def persist(cache: Path, data: dict):
    cache.parent.mkdir(parents=True, exist_ok=True)
    # No secrets, router IP, hostnames, or arbitrary command output in this cache.
    content = json.dumps(data, separators=(',', ':'), allow_nan=False)
    fd, temp = tempfile.mkstemp(prefix='.gmcs-', dir=cache.parent)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(content + '\n')
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, cache)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def run(config_path: Path, cache_path: Path):
    config = validated(json.loads(config_path.read_text(encoding='utf-8')))
    now = int(time.time())
    result = {
        'version': 1,
        'at': now,
        'inside': inside_result(config['inside']),
        'ookla': ookla_result(config['ookla']),
    }
    persist(cache_path, result)
    print(json.dumps({'at': now, 'inside_status': result['inside']['status'],
                      'ookla_status': result['ookla']['status']}, separators=(',', ':')))
    return 0 if any(result[k]['status'] == 'ok' for k in ('inside', 'ookla')) else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    p.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    p.add_argument('--validate-only', action='store_true')
    a = p.parse_args()
    if a.validate_only:
        print('Configuration valid:', validated(json.loads(a.config.read_text(encoding='utf-8'))))
        return 0
    return run(a.config, a.cache)


if __name__ == '__main__':
    sys.exit(main())
