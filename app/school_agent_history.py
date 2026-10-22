"""Independent school-host agent history. Never mixes VyOS-router tests or browser tests.

School agents submit genuine, server-observed transfer results using their existing
source-IP-bound per-host credentials; LibreNMS only reads cached measurements.
"""
from __future__ import annotations

import time
from .agents import AGENT_ID_RE
from .database import connect
from .router_history import WINDOWS, RETENTION_DAYS

STALE_SECONDS = 150 * 60


def initialize(db_path: str) -> None:
    with connect(db_path) as con:
        con.execute('CREATE INDEX IF NOT EXISTS idx_results_agent_completed ON results(agent_id,completed_at)')


def check_agent_id(agent_id: str) -> str:
    if not AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError('Invalid registered agent ID')
    return agent_id


def most_recent(db_path: str, agent_id: str, now: int | None = None) -> dict | None:
    check_agent_id(agent_id)
    t = int(time.time()) if now is None else int(now)
    with connect(db_path) as con:
        row = con.execute('''SELECT id,completed_at,client_ip,school,vlan,agent_id,
          download_mbps,upload_mbps,latency_ms,jitter_ms,packet_loss_pct
          FROM results WHERE agent_id=? ORDER BY completed_at DESC,id DESC LIMIT 1''',
          (agent_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result['age_seconds'] = max(0,t-result['completed_at'])
    result['status'] = 'REPORTING' if -60 <= t-result['completed_at'] <= STALE_SECONDS else 'STALE'
    return result


def listed(db_path: str, agents: list[str], now: int | None = None) -> list[dict]:
    rows=[]
    for agent_id in sorted(agents):
        data=most_recent(db_path,agent_id,now)
        rows.append(data if data is not None else {'agent_id':agent_id,'status':'NO_SAMPLE',
                                                    'completed_at':None})
    return rows


def graph(db_path: str, agent_id: str, window: str, now: int | None = None) -> dict:
    check_agent_id(agent_id)
    if window not in WINDOWS:
        raise ValueError('Invalid chart window')
    n=int(time.time()) if now is None else int(now)
    seconds,step=WINDOWS[window]
    with connect(db_path) as con:
        rows=con.execute('''SELECT (completed_at / ?)*? AS at,
            ROUND(AVG(download_mbps),3) AS down_mbps,
            ROUND(AVG(upload_mbps),3) AS up_mbps,
            ROUND(AVG(latency_ms),3) AS latency_ms,
            ROUND(AVG(jitter_ms),3) AS jitter_ms,
            ROUND(AVG(packet_loss_pct),3) AS loss_pct,
            COUNT(*) AS samples
          FROM results
          WHERE agent_id=? AND completed_at>=? AND completed_at<=?
          GROUP BY 1 ORDER BY at''',
          (step,step,agent_id,n-seconds,n)).fetchall()
    return {'agent_id':agent_id, 'range':window,
            'path':'School agent device to GMCS NOC HTTPS server; NOT VyOS router or Internet speed',
            'retention_days':RETENTION_DAYS,'points':[dict(row) for row in rows]}
