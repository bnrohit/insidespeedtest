#!/usr/bin/env python3
"""Import hourly, capped SSH-controlled VyOS tests from the existing collector.

Runs on the Debian NOC VM; it does not install agents on school computers or
change VyOS configurations. Shares the original collector's concurrency lock.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

APP = Path('/home/rohith/insidespeedtest')
COLLECTOR = Path('/opt/gmcs-router-report/morning_report.py')
COLLECTOR_CONFIG = Path('/etc/gmcs-router-report/config.json')
COLLECTOR_SITES = Path('/etc/gmcs-router-report/sites.csv')
CONFIG = Path('/etc/gmcs-router-hourly/config.json')
OUTPUT = Path('/var/lib/gmcs-router-report')
ARCHIVE = Path('/var/lib/gmcs-router-hourly/csv')
# Pilot: these are the 17 previously enrolled and successfully tested routers.
DEFAULT_SITES = 'CDE,CME,CMM,CPE,CPH,CPM,DNE,DSE,GCH,GPH,GPM,HMH,JFE,KEM,RAE,THE,TOM'.split(',')


def load_config(path=CONFIG):
    config=json.loads(path.read_text())
    if not isinstance(config,dict) or not isinstance(config.get('sites'),list):
        raise ValueError('Expected an explicit list of previously authorized school codes')
    sites=config['sites']
    if not sites or len(set(sites))!=len(sites) or any(not s.isupper() or not s.isalnum() or len(s)>12 for s in sites):
        raise ValueError('Invalid authorized site list')
    return config


def get_db_path():
    c=json.loads(subprocess.check_output(['docker','inspect','gmcs-inside-speed-test'],text=True))[0]
    mounts=[m for m in c['Mounts'] if m['Destination']=='/data']
    if len(mounts)!=1:
        raise RuntimeError('Docker /data database mount is ambiguous')
    db=Path(mounts[0]['Source'])/'results.sqlite3'
    if not db.is_file():
        raise RuntimeError('Existing results DB missing; refusing to overwrite')
    return str(db)


def merge_inventory(all_sites, tested, allowed):
    expected={r['site']:r for r in all_sites}
    if len(expected)!=len(all_sites) or not set(allowed).issubset(expected):
        raise ValueError('Authorized school codes do not match the district inventory')
    if len({r['site'] for r in tested})!=len(tested) or not set(r['site'] for r in tested).issubset(set(allowed)):
        raise ValueError('Unrecognized collector site in CSV')
    found={r['site']:r for r in tested}
    rows=[]
    for s in all_sites:
        if s['site'] in found:
            rows.append(found[s['site']]); continue
        if s['inventory_status']=='needs_verification': status='NEEDS_VERIFICATION'
        elif s['classification'] in ('infrastructure','legacy'): status='SKIPPED_INFRA'
        else: status='NOT_ENROLLED'
        rows.append({'site':s['site'], 'name':s['name'],'router_ip':s['router_ip'],
            'classification':s['classification'],'inventory_status':s['inventory_status'],
            'status':status, 'ping_loss_percent':'','avg_latency_ms':'',
            'upload_mbps_capped':'','download_mbps_capped':'',
            'comment':'No hourly active test; verify management reachability and opt in explicitly'})
    return rows


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',type=Path,default=CONFIG)
    ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args()
    cfg=load_config(args.config)
    with COLLECTOR_SITES.open(newline='') as f:
        inventory=list(csv.DictReader(f))
    allowed=cfg['sites']
    if not set(allowed).issubset({r['site'] for r in inventory}):
        raise ValueError('Site list does not match private inventory')
    if args.dry_run:
        print(f'Validated {len(inventory)} school/site rows, {len(allowed)} enrolled. No tests initiated.')
        return 0
    if not COLLECTOR.is_file() or not COLLECTOR_CONFIG.is_file():
        raise SystemExit('Existing GMCS morning-report collector/config missing')
    conf=json.loads(COLLECTOR_CONFIG.read_text())
    if conf.get('mode') != 'throughput' or not conf.get('cap','').endswith('M'):
        raise SystemExit('Hourly job requires existing capped throughput mode (Mbit cap)')
    cap=float(conf['cap'][:-1])
    if not 1 <= cap <= 50: raise SystemExit('Refusing uncapped/high-impact hourly tests')
    started=int(dt.datetime.now(dt.timezone.utc).timestamp())
    local_date=dt.datetime.now(dt.timezone(dt.timedelta(hours=-6))).date() # actual collector determines Denver date
    cmd=[sys.executable,str(COLLECTOR),'--mode','throughput','--sites',','.join(allowed),
         '--config',str(COLLECTOR_CONFIG),'--inventory',str(COLLECTOR_SITES),
         '--out',str(OUTPUT),'--ping-count','2']
    print(f'Running {len(allowed)} capped school-router probes; no SMTP mail on this hourly job',flush=True)
    done=subprocess.run(cmd,timeout=1800)
    if done.returncode!=0:
        raise SystemExit(f'Collector returned {done.returncode}. Hourly import refused.')
    # Existing program writes a date-named -pilot CSV after successful completion.
    # Check mtime to avoid erroneously importing a previous day's/hour's report.
    candidates=list(OUTPUT.glob('gmcs-router-report-*-pilot.csv'))
    if not candidates: raise SystemExit('Expected pilot CSV missing')
    source=max(candidates,key=lambda p:p.stat().st_mtime)
    if source.stat().st_mtime < started - 3:
        raise SystemExit('Collector CSV is stale; refusing to import')
    with source.open(newline='') as f: data=list(csv.DictReader(f))
    if len(data)!=len(allowed):raise SystemExit('Collector returned fewer rows than enrolled sites')
    rows=merge_inventory(inventory,data,allowed)
    sys.path.insert(0,str(APP))
    from app.router_history import import_rows
    count=import_rows(get_db_path(),rows,started,cap)
    ARCHIVE.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(ARCHIVE,0o700)
    snap=ARCHIVE/(dt.datetime.fromtimestamp(started,dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.csv')
    shutil.copy2(source,snap)
    os.chmod(snap,0o600)
    for old in ARCHIVE.glob('*.csv'):
        if old.stat().st_mtime < started-732*86400:old.unlink()
    print(f'Imported {count} per-site hourly records, including explicit unavailable statuses; archive={snap}',flush=True)
    return 0

if __name__=='__main__':sys.exit(main())
