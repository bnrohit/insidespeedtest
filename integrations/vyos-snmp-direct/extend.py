#!/usr/bin/env python3
"""SNMP extension: READ cached on-router measurements, never perform speed tests."""
from __future__ import annotations
import json
import math
from pathlib import Path
import sys
import time

DEFAULT=Path('/config/user-data/gmcs-vyos-speedtest/latest.json')
FIELDS=('download_mbps','upload_mbps','latency_ms','jitter_ms','loss_pct')


def render(path=DEFAULT, now=None):
    t=int(time.time()) if now is None else now
    result={'version':1,'error':0,'errorString':'','data':{}}
    status='missing'; stamp=0; source=''; metrics={k:None for k in FIELDS}
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('version')!=1:raise ValueError('Unknown cache version')
        stamp=int(data['at'])
        raw=data['inside']
        status=str(raw.get('status','invalid'))[:16]
        source=raw.get('source','') if status=='ok' else ''
        if not -60<=t-stamp<=5400:
            status='stale'
        if status=='ok' and source!='vyos-local-gmcs-https':
            status='invalid'
        if status=='ok':
            for key in FIELDS:
                v=raw.get(key)
                cap=100 if key=='loss_pct' else 100000
                if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=cap:
                    status='invalid';break
                metrics[key]=v
            if status!='ok':metrics={k:None for k in FIELDS}
    except (OSError,TypeError,ValueError,KeyError,json.JSONDecodeError):
        status='missing';stamp=0
    # Source and status are diagnostic metadata only: never RRD graph series.
    result['data']={'status':status,'at':stamp,
                    'source':source if status=='ok' else '',**metrics}
    return json.dumps(result,separators=(',',':'),allow_nan=False)

if __name__=='__main__':
    print(render(Path(sys.argv[1]) if len(sys.argv)>1 else DEFAULT))
