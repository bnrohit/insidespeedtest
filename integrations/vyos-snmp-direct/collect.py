#!/usr/bin/env python3
"""On-router GMCS HTTPS throughput collector; no Ookla, SSH polling, or remote commands.

A scheduled VyOS task invokes this file. LibreNMS reads ONLY the public cached
measurements via an SNMP extension, which never launches network tests.
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
import urllib.parse
import re

DEFAULT_CONFIG = Path('/config/auth/gmcs-speedtest/direct.json')
DEFAULT_CACHE = Path('/config/user-data/gmcs-vyos-speedtest/latest.json')
DEFAULT_AGENT = Path('/config/scripts/gmcs-speedtest/school_agent.py')


def validated(config: dict) -> dict:
    if not isinstance(config, dict) or set(config) != {'inside'}:
        raise ValueError('Only the GMCS inside test configuration is supported')
    inside=config['inside']
    if not isinstance(inside, dict) or set(inside)-{'enabled','url','agent_id','token_file','ca_file'}:
        raise ValueError('Invalid inside-test configuration')
    if type(inside.get('enabled')) is not bool:
        raise ValueError('inside.enabled must be true/false')
    if inside['enabled']:
        url=urllib.parse.urlsplit(inside.get('url',''))
        if (url.scheme!='https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in ('','/')):
            raise ValueError('GMCS test requires trusted HTTPS URL, no redirects')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', inside.get('agent_id','')):
            raise ValueError('Invalid enrolled agent ID')
        for field in ('token_file','ca_file'):
            value=inside.get(field,'')
            if field=='token_file' and not value:
                raise ValueError('Missing token path')
            if value and not Path(value).is_relative_to('/config/auth/gmcs-speedtest'):
                raise ValueError('Secret and CA paths must stay under /config/auth/gmcs-speedtest')
            if value and ('..' in Path(value).parts or value=='/config/auth/gmcs-speedtest'):
                raise ValueError('Invalid path')
    return config


def number(value, max_value=100000):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=max_value:
        return None
    return round(float(value), 3)


def measure(config: dict, script=DEFAULT_AGENT, run_command=subprocess.run) -> dict:
    if not config['enabled']:
        return {'status':'disabled'}
    cmd=[sys.executable,str(script),'--url',config['url'],
         '--agent-id',config['agent_id'],'--token-file',config['token_file'],
         '--download-seconds','3','--upload-seconds','3',
         '--download-max-mib','24','--upload-max-mib','8',
         '--chunk-mib','2','--request-timeout','25']
    if config.get('ca_file'):
        cmd += ['--ca-file',config['ca_file']]
    try:
        done=run_command(cmd,capture_output=True,text=True,timeout=165,check=False)
        if done.returncode:
            return {'status':'failed'}
        raw=json.loads(done.stdout.strip().splitlines()[-1])
        if raw.get('agent_id')!=config['agent_id']:
            return {'status':'invalid'}
        # A server acknowledgement is emitted only after this agent completed both
        # real HTTP transfers, latency probes and the authenticated result upload.
        receipt = raw.get('result_id')
        if type(receipt) not in (str, int) or not str(receipt).strip():
            return {'status':'invalid'}
        fields={
            'download_mbps':number(raw.get('download_mbps')),
            'upload_mbps':number(raw.get('upload_mbps')),
            'latency_ms':number(raw.get('latency_ms'),60000),
            'jitter_ms':number(raw.get('jitter_ms'),60000),
            'loss_pct':number(raw.get('packet_loss_pct'),100),
        }
        if any(x is None for x in fields.values()):
            return {'status':'invalid'}
        return {'status':'ok','source':'vyos-local-gmcs-https',**fields}
    except (OSError,subprocess.TimeoutExpired,ValueError,UnicodeError,KeyError,IndexError,TypeError):
        return {'status':'failed'}


def persist(path:Path,content:dict):
    # Cache is under an already-installed persistent, world-traversable directory.
    # Only nonsecret measurements are stored; no tokens, IPs, hostnames or usernames.
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(content,separators=(',',':'),allow_nan=False)+'\n'
    fd,temp=tempfile.mkstemp(prefix='.gmcs-',dir=path.parent)
    try:
        os.fchmod(fd,0o644)
        with os.fdopen(fd,'w',encoding='utf-8') as fh:
            fh.write(payload); fh.flush(); os.fsync(fh.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def run(config_path:Path,cache_path:Path):
    config=validated(json.loads(config_path.read_text(encoding='utf-8')))
    measured=measure(config['inside'])
    # Timestamp the completed measurement, not the beginning of the test.
    now=int(time.time())
    persist(cache_path,{'version':1,'at':now,'inside':measured})
    print(json.dumps({'at':now,'inside_status':measured['status']},separators=(',',':')))
    return 0 if measured['status']=='ok' else 1


def main():
    cli=argparse.ArgumentParser(description='VyOS-local GMCS HTTPS speed test')
    cli.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    cli.add_argument('--cache',type=Path,default=DEFAULT_CACHE)
    cli.add_argument('--validate-only',action='store_true')
    a=cli.parse_args()
    if a.validate_only:
        validated(json.loads(a.config.read_text(encoding='utf-8')))
        print('GMCS configuration validated (no tests sent, no credentials disclosed)')
        return 0
    return run(a.config,a.cache)

if __name__=='__main__':sys.exit(main())
