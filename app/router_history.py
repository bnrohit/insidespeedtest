"""Read-only site history for capped VyOS-to-NOC iperf3 samples.

Rows come from the existing, administrator-operated central SSH collector, never
from arbitrary browser clients. Status is preserved; missing metrics are NULL.
"""
from __future__ import annotations

import csv
import datetime as dt
import ipaddress
import math
import re
from pathlib import Path
from .database import connect

RETENTION_DAYS = 732  # >= two calendar years including a leap day
SITE = re.compile(r"^[A-Z0-9_-]{2,12}$")
WINDOWS = {'6h': (6*3600, 3600), 'day': (86400, 3600),
           'week': (7*86400, 3600), 'month': (31*86400, 6*3600),
           'year': (366*86400, 86400), '2years': (732*86400, 3*86400)}
COLUMNS = {'site', 'name', 'router_ip', 'classification', 'inventory_status',
           'status', 'ping_loss_percent', 'avg_latency_ms',
           'upload_mbps_capped', 'download_mbps_capped', 'comment'}


def initialize(db_path: str):
    with connect(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS vyos_hourly (
            site TEXT NOT NULL, at INTEGER NOT NULL, name TEXT NOT NULL,
            router_ip TEXT NOT NULL, status TEXT NOT NULL, inventory_status TEXT NOT NULL,
            ping_loss REAL, latency_ms REAL, up_mbps REAL, down_mbps REAL,
            cap_mbps REAL NOT NULL, note TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(site,at))''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_vyos_hourly_at ON vyos_hourly(at)')


def metric(value: str, max_value: float) -> float | None:
    if value is None or str(value).strip() == '':
        return None
    try:
        f = float(value)
    except (ValueError, TypeError):
        return None
    return round(f, 3) if math.isfinite(f) and 0 <= f <= max_value else None


def import_rows(db_path: str, rows: list[dict], at: int, cap_mbps: float):
    if at < 1_700_000_000 or not 0 < cap_mbps <= 10000:
        raise ValueError('Invalid timestamp or cap')
    at = at // 3600 * 3600
    seen = set()
    prepared = []
    for row in rows:
        if not COLUMNS.issubset(row):
            raise ValueError('CSV schema mismatch')
        site = row['site'].upper()
        if not SITE.fullmatch(site) or site in seen:
            raise ValueError('Duplicate/invalid site code')
        seen.add(site)
        ip = ipaddress.ip_address(row['router_ip'])
        if not ip.is_private or ip.version != 4 or not str(ip).startswith('10.'):
            raise ValueError('Unexpected router IP')
        if len(row['name']) > 140 or len(row['status']) > 45 or len(row['comment']) > 400:
            raise ValueError('Unexpected field length')
        prepared.append((site, at, row['name'], str(ip), row['status'],
            row['inventory_status'], metric(row['ping_loss_percent'],100),
            metric(row['avg_latency_ms'],60000), metric(row['upload_mbps_capped'],10000),
            metric(row['download_mbps_capped'],10000), cap_mbps, row['comment']))
    initialize(db_path)
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        db.executemany('''INSERT INTO vyos_hourly
           (site,at,name,router_ip,status,inventory_status,ping_loss,latency_ms,
            up_mbps,down_mbps,cap_mbps,note)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(site,at) DO UPDATE SET
            name=excluded.name, router_ip=excluded.router_ip,
            status=excluded.status,inventory_status=excluded.inventory_status,
            ping_loss=excluded.ping_loss,latency_ms=excluded.latency_ms,
            up_mbps=excluded.up_mbps,down_mbps=excluded.down_mbps,
            cap_mbps=excluded.cap_mbps,note=excluded.note''', prepared)
        # Retain hourly raw samples for >= two years, independent of LibreNMS RRD.
        db.execute('DELETE FROM vyos_hourly WHERE at<?', (at-RETENTION_DAYS*86400,))
    return len(prepared)


def latest(db_path: str):
    with connect(db_path) as db:
        rows=db.execute('''SELECT h.* FROM vyos_hourly h JOIN
             (SELECT site,MAX(at) AS at FROM vyos_hourly GROUP BY site) m
             ON h.site=m.site AND h.at=m.at ORDER BY h.site''').fetchall()
    return [dict(r) for r in rows]


def latest_site(db_path: str, site: str):
    if not SITE.fullmatch(site):
        raise ValueError('Unknown site code')
    with connect(db_path) as db:
        row=db.execute('SELECT * FROM vyos_hourly WHERE site=? ORDER BY at DESC LIMIT 1',(site,)).fetchone()
    return dict(row) if row else None


def trend(db_path: str, site: str, range_name: str, now: int | None = None):
    if not SITE.fullmatch(site) or range_name not in WINDOWS:
        raise ValueError('Invalid site or time range')
    n=int(dt.datetime.now(dt.timezone.utc).timestamp()) if now is None else now
    seconds,period=WINDOWS[range_name]
    with connect(db_path) as db:
        rows=db.execute('''SELECT (at / ?)*? AS at, AVG(down_mbps) AS down_mbps,
             AVG(up_mbps) AS up_mbps,AVG(latency_ms) AS latency_ms,
             AVG(ping_loss) AS ping_loss,COUNT(*) AS samples,
             SUM(CASE WHEN down_mbps IS NULL THEN 1 ELSE 0 END) AS missing
             FROM vyos_hourly WHERE site=? AND at>=? AND at<=?
             GROUP BY 1 ORDER BY at''',
             (period,period,site,n-seconds,n)).fetchall()
    return {'site':site,'range':range_name,'cap_note':'Throughput is capped; values are NOT ISP line rate',
            'points':[dict(row) for row in rows]}
