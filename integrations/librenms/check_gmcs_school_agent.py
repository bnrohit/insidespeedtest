#!/usr/bin/env python3
"""LibreNMS read-only service plugin: cache school-host agent samples, never run a test.

Deploy on the LibreNMS POLLER only. The token does not belong on school hosts.
"""
from __future__ import annotations

import argparse
import http.client
import json
import math
from pathlib import Path
import re
import ssl
import sys
import time
import urllib.parse

ID_RE=re.compile(r'^[A-Za-z0-9_.-]{1,64}$')


def check(agent_id: str, base_url: str, token_file: str, ca_file=None, now=None):
    if not ID_RE.fullmatch(agent_id):
        return 3, 'UNKNOWN - Invalid school-agent ID'
    url=urllib.parse.urlsplit(base_url)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.path not in ('','/') or url.query or url.fragment:
        return 3, 'UNKNOWN - HTTPS-only base URL required'
    conn=None
    try:
        key=Path(token_file).read_text(encoding='utf-8').strip()
        if len(key)<32:return 3,'UNKNOWN - Monitoring-only token missing'
        ctx=ssl.create_default_context(cafile=ca_file)
        conn=http.client.HTTPSConnection(url.hostname,url.port or 443,context=ctx,timeout=10)
        conn.request('GET','/api/monitoring/school-agent/'+agent_id,headers={'Authorization':'Bearer '+key})
        response=conn.getresponse()
        if response.status!=200:
            return 3,'UNKNOWN - Monitoring API returned HTTP '+str(response.status)
        raw=response.read(8193)
        if len(raw)>8192:return 3,'UNKNOWN - Oversized response'
        obj=json.loads(raw)
        if obj.get('agent_id')!=agent_id:return 3,'UNKNOWN - Agent ID mismatch'
        age=(int(time.time()) if now is None else int(now))-int(obj['at'])
        if age < -120 or age>9000 or obj.get('status')!='REPORTING':
            return 3,'UNKNOWN - Agent test stale or not reporting; not proof of WAN outage'
        data={}
        for key in ('download_mbps','upload_mbps','latency_ms','jitter_ms','loss_pct'):
            number=obj.get(key)
            if not isinstance(number,(float,int)) or not math.isfinite(number) or number<0:
                return 3,'UNKNOWN - Invalid metric '+key
            data[key]=float(number)
        if data['loss_pct']>100 or data['download_mbps']>100000 or data['upload_mbps']>100000:
            return 3,'UNKNOWN - Out of bounds sample'
        d=data
        perf=(f"download_mbps={d['download_mbps']:.3f}Mbps;;;0; "
              f"upload_mbps={d['upload_mbps']:.3f}Mbps;;;0; "
              f"latency_ms={d['latency_ms']:.3f}ms;;;0; "
              f"jitter_ms={d['jitter_ms']:.3f}ms;;;0; "
              f"loss_pct={d['loss_pct']:.3f}%;0;100;0;100")
        return 0, (f"OK - {agent_id} school-host to GMCS NOC: "
                   f"down {d['download_mbps']:.2f}, up {d['upload_mbps']:.2f} Mbps ({age//60}m old) | {perf}")
    except (OSError,ValueError,KeyError,OverflowError,json.JSONDecodeError, http.client.HTTPException) as exc:
        return 3,'UNKNOWN - Monitoring API unavailable ('+type(exc).__name__+')'
    finally:
        if conn is not None:conn.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--agent-id',required=True)
    parser.add_argument('--url',required=True)
    parser.add_argument('--token-file',required=True)
    parser.add_argument('--ca-file')
    args=parser.parse_args()
    code,msg=check(args.agent_id,args.url,args.token_file,args.ca_file)
    print(msg)
    return code

if __name__=='__main__':sys.exit(main())
