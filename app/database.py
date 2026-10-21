"""SQLite with atomic, bounded sessions; durable report/notification audit."""
from __future__ import annotations

import sqlite3
import time
import json
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, client_ip TEXT NOT NULL, created_at INTEGER NOT NULL,
 used_at INTEGER, agent_id TEXT NOT NULL DEFAULT '',
 group_key TEXT NOT NULL DEFAULT '',
 download_reserved INTEGER NOT NULL DEFAULT 0,
 upload_reserved INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_ip_created ON sessions(client_ip, created_at);
CREATE TABLE IF NOT EXISTS results (
 id INTEGER PRIMARY KEY AUTOINCREMENT, completed_at INTEGER NOT NULL,
 client_ip TEXT NOT NULL, school TEXT NOT NULL, vlan TEXT NOT NULL,
 network_label TEXT NOT NULL, agent_id TEXT NOT NULL DEFAULT '',
 download_mbps REAL NOT NULL, upload_mbps REAL NOT NULL,
 latency_ms REAL NOT NULL, jitter_ms REAL NOT NULL,
 packet_loss_pct REAL NOT NULL, download_bytes INTEGER NOT NULL,
 upload_bytes INTEGER NOT NULL, email_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_results_completed ON results(completed_at);
CREATE INDEX IF NOT EXISTS idx_results_school ON results(school, completed_at);
CREATE TABLE IF NOT EXISTS notification_gates (
 group_key TEXT PRIMARY KEY,
 result_id INTEGER NOT NULL,
 next_eligible_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_smtp_probe (
 id INTEGER PRIMARY KEY CHECK (id=1), last_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_failures (
 client_ip TEXT NOT NULL, attempted_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_failures ON admin_failures(client_ip, attempted_at);
"""


@contextmanager
def connect(db_path: str):
    con = sqlite3.connect(db_path, timeout=15)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=15000")
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        # Upgrade an existing private deployment without destroying results.
        for table, column, definition in [
            ("sessions", "agent_id", "TEXT NOT NULL DEFAULT ''"),
            ("sessions", "group_key", "TEXT NOT NULL DEFAULT ''"),
            ("sessions", "download_reserved", "INTEGER NOT NULL DEFAULT 0"),
            ("sessions", "upload_reserved", "INTEGER NOT NULL DEFAULT 0"),
            ("results", "agent_id", "TEXT NOT NULL DEFAULT ''"),
        ]:
            existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        con.execute("CREATE INDEX IF NOT EXISTS idx_sessions_group_created ON sessions(group_key, created_at)")


def notification_group(identity: dict, ip: str) -> str:
    """A single email bucket per school and VLAN, including unknown identities.

    Unknown clients must NOT each open their own mail bucket: a large number of
    unmapped school visitors could otherwise flood the district SMTP relay.
    Source IP is still retained on every individual test record.
    """
    school = identity.get("school", "Unknown")
    vlan = identity.get("vlan", "Unknown")
    return json.dumps([school, vlan], separators=(",", ":"))


def create_session(db_path: str, token_hash: str, ip: str, cooldown_seconds: int,
                   max_per_hour: int, agent_id: str = "", group_key: str = "",
                   max_active: int = 20, max_group_active: int = 4,
                   active_lease_seconds: int = 120) -> str:
    """Atomically limit simultaneous active tests and per-client frequency."""
    now = int(time.time())
    with connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM sessions WHERE created_at < ?", (now - 86400,))
        latest, count = con.execute(
            "SELECT MAX(created_at), COUNT(*) FROM sessions WHERE client_ip=? AND created_at>=?",
            (ip, now - 3600),
        ).fetchone()
        if count >= max_per_hour or (latest is not None and now - latest < cooldown_seconds):
            return "client_limit"
        active = con.execute("SELECT COUNT(*) FROM sessions WHERE used_at IS NULL AND created_at>=?",
                             (now - active_lease_seconds,)).fetchone()[0]
        if active >= max_active:
            return "busy"
        active_group = con.execute("""SELECT COUNT(*) FROM sessions
            WHERE used_at IS NULL AND created_at>=? AND group_key=?""",
                                   (now - active_lease_seconds, group_key)).fetchone()[0]
        if active_group >= max_group_active:
            return "busy"
        con.execute("INSERT INTO sessions(token_hash,client_ip,created_at,agent_id,group_key) VALUES(?,?,?,?,?)",
                    (token_hash, ip, now, agent_id, group_key))
        return "created"


def claim_notification(db_path: str, group_key: str, result_id: int,
                       cooldown_seconds: int) -> bool:
    """Single atomic winner per school/VLAN across concurrent workers/requests."""
    now = int(time.time())
    with connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        cur = con.execute("""INSERT INTO notification_gates (group_key,result_id,next_eligible_at)
          VALUES (?,?,?) ON CONFLICT(group_key) DO UPDATE SET
          result_id=excluded.result_id, next_eligible_at=excluded.next_eligible_at
          WHERE notification_gates.next_eligible_at<=?""",
          (group_key, result_id, now + cooldown_seconds, now))
        if cur.rowcount == 1:
            con.execute("UPDATE results SET email_status='queued' WHERE id=?", (result_id,))
        else:
            con.execute("UPDATE results SET email_status='suppressed' WHERE id=?", (result_id,))
        return cur.rowcount == 1


def failed_notification(db_path: str, result_id: int, retry_seconds: int = 900):
    """Mail outage: permit one later retry, never an immediate notification storm."""
    now = int(time.time())
    with connect(db_path) as con:
        con.execute("""UPDATE notification_gates SET next_eligible_at=?
          WHERE result_id=?""", (now + retry_seconds, result_id))
        con.execute("UPDATE results SET email_status='failed' WHERE id=?", (result_id,))


def reserve_transfer(db_path: str, token_hash: str, ip: str, amount: int,
                     direction: str, max_total_bytes: int, max_direction_bytes: int, ttl_seconds: int = 600) -> bool:
    """Reserve transfer allowance before sending/receiving; atomic across requests."""
    if direction not in ("download", "upload") or amount <= 0:
        return False
    column = "download_reserved" if direction == "download" else "upload_reserved"
    now = int(time.time())
    with connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        cur = con.execute(f"""UPDATE sessions SET {column}={column}+?
          WHERE token_hash=? AND client_ip=? AND used_at IS NULL AND created_at>=?
          AND download_reserved+upload_reserved+?<=? AND {column}+?<=?""",
                          (amount, token_hash, ip, now - ttl_seconds, amount, max_total_bytes, amount, max_direction_bytes))
        return cur.rowcount == 1


def valid_session(db_path: str, token_hash: str, ip: str, ttl_seconds: int = 600) -> bool:
    now = int(time.time())
    with connect(db_path) as con:
        row = con.execute(
            "SELECT 1 FROM sessions WHERE token_hash=? AND client_ip=? AND used_at IS NULL AND created_at>=?",
            (token_hash, ip, now - ttl_seconds),
        ).fetchone()
    return row is not None


def save_result(db_path: str, token_hash: str, ip: str, record: dict, ttl_seconds: int = 600) -> tuple[int, str] | None:
    now = int(time.time())
    with connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        session = con.execute("""SELECT agent_id,download_reserved,upload_reserved FROM sessions
             WHERE token_hash=? AND client_ip=? AND used_at IS NULL AND created_at>=?""",
                              (token_hash, ip, now - ttl_seconds)).fetchone()
        if session is None:
            return None
        # Report must reflect actual, server-observed transfer reservations.
        if (not 0 < record["download_bytes"] <= session["download_reserved"] or
                not 0 < record["upload_bytes"] <= session["upload_reserved"]):
            return None
        cur = con.execute("UPDATE sessions SET used_at=? WHERE token_hash=? AND used_at IS NULL",
                          (now, token_hash))
        if cur.rowcount != 1:
            return None
        agent_id = session["agent_id"]
        cur = con.execute(
            """INSERT INTO results (completed_at,client_ip,school,vlan,network_label,agent_id,
               download_mbps,upload_mbps,latency_ms,jitter_ms,packet_loss_pct,download_bytes,upload_bytes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now, ip, record["school"], record["vlan"], record["network_label"], agent_id,
             record["download_mbps"], record["upload_mbps"], record["latency_ms"],
             record["jitter_ms"], record["packet_loss_pct"],
             record["download_bytes"], record["upload_bytes"]),
        )
        return int(cur.lastrowid), agent_id


def set_email_status(db_path: str, result_id: int, status: str) -> None:
    with connect(db_path) as con:
        con.execute("UPDATE results SET email_status=? WHERE id=?", (status, result_id))


def admin_blocked(db_path: str, ip: str, max_failures: int = 7, window: int = 900) -> bool:
    now = int(time.time())
    with connect(db_path) as con:
        con.execute("DELETE FROM admin_failures WHERE attempted_at<?", (now - window,))
        count = con.execute("SELECT COUNT(*) FROM admin_failures WHERE client_ip=? AND attempted_at>=?",
                            (ip, now - window)).fetchone()[0]
        return count >= max_failures


def admin_failure(db_path: str, ip: str):
    with connect(db_path) as con:
        con.execute("INSERT INTO admin_failures(client_ip,attempted_at) VALUES(?,?)", (ip, int(time.time())))


def admin_success(db_path: str, ip: str):
    with connect(db_path) as con:
        con.execute("DELETE FROM admin_failures WHERE client_ip=?", (ip,))


def allow_smtp_probe(db_path: str, cooldown: int = 300) -> bool:
    """Persisted cross-request rate limit so SMTP diagnostics cannot flood inboxes."""
    now = int(time.time())
    with connect(db_path) as con:
        con.execute("BEGIN IMMEDIATE")
        result = con.execute("""INSERT INTO admin_smtp_probe(id,last_at) VALUES(1,?)
            ON CONFLICT(id) DO UPDATE SET last_at=excluded.last_at
            WHERE admin_smtp_probe.last_at<=?""", (now, now-cooldown))
        return result.rowcount == 1
