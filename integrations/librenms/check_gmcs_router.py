#!/usr/bin/env python3
"""Nagios-format cached hourly GMCS WAN values; NO speed test during LibreNMS polls.

Run from LibreNMS poller, one service per school device. Metrics are sourced
from GMCS central VM's hourly SQLite history via a read-only authenticated API.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import ssl
import re

CODE=re.compile(r'^[A-Z0-9_-]{2,12}$')

def check(site,base_url,token_file,ca_file=None,now=None):
    if not CODE.fullmatch(site):return 3,'UNKNOWN - Invalid site code'
    if not base_url.startswith('https://') or urllib.parse.urlparse(base_url).username:
        return 3,'UNKNOWN - HTTPS endpoint required'
    try:
        token=Path(token_file).read_text(encoding='utf-8').strip()
        if len(token)<32: return 3,'UNKNOWN - Monitoring credential missing'
        ctx=ssl.create_default_context(cafile=ca_file)
        url=base_url.rstrip('/')+'/api/monitoring/router-hourly/'+site
        req=urllib.request.Request(url,headers={'Authorization':'Bearer '+token})
        with urllib.request.urlopen(req,timeout=10,context=ctx) as response:
            payload=json.load(response)
        if payload.get('site')!=site:return 3,'UNKNOWN - Site mismatch'
        t=int(time.time()) if now is None else now
        age=t-int(payload['at'])
        if age < -3600 or age>9000:
            return 3,f'UNKNOWN - No recent hourly sample ({max(0,age)//3600} h old)'
        down,up,lat,loss=(payload.get(k) for k in ('down_mbps','up_mbps','latency_ms','ping_loss'))
        if payload['status']!='TEST_COMPLETE' or down is None or up is None:
            return 3,'UNKNOWN - '+str(payload['status'])[:60]+' (not proof school is down)'
        if any(not isinstance(n,(int,float)) or not 0<=n<=10000 for n in (down,up)):
            return 3,'UNKNOWN - Invalid throughput sample'
        # Single perf-data record per source. LibreNMS stores graphs in service RRDs.
        perf=f"download_mbps={down:.3f}Mbps;;;0; upload_mbps={up:.3f}Mbps;;;0;"
        if lat is not None:perf+=f" latency_ms={float(lat):.3f}ms;;;0;"
        if loss is not None:perf+=f" loss_pct={float(loss):.3f}%;0;100;0;100"
        return 0,f'OK - {site} router-to-NOC capped ↓{down:.2f}/↑{up:.2f} Mbps ({age//60}m old) | {perf}'
    except (OSError,ValueError,KeyError,urllib.error.URLError,json.JSONDecodeError) as exc:
        return 3,'UNKNOWN - GMCS central metrics unavailable ('+type(exc).__name__+')'


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--site',required=True)
    p.add_argument('--url',required=True)
    p.add_argument('--token-file',required=True)
    p.add_argument('--ca-file',default=None)
    a=p.parse_args()
    code,out=check(a.site.upper(),a.url,a.token_file,a.ca_file)
    print(out)
    return code

if __name__=='__main__':sys.exit(main())
