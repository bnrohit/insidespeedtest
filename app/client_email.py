"""Allow a recent real browser test to request one bounded admin email.

No arbitrary recipients, recipient input, relay credentials, or unsigned result IDs.
"""
from __future__ import annotations

import hashlib
import json
import time

from .database import connect, notification_group


class EmailClaimError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def claim_email(db_path: str, result_id: int, session_token: str, client_ip: str) -> dict:
    now = int(time.time())
    token_hash = hashlib.sha256(session_token.encode('utf-8')).hexdigest()
    with connect(db_path) as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute("""SELECT r.* FROM results r JOIN sessions s ON s.result_id=r.id
          WHERE r.id=? AND s.token_hash=? AND s.client_ip=? AND r.client_ip=?
          AND s.agent_id='' AND s.used_at>=?""",
          (result_id, token_hash, client_ip, client_ip, now-3600)).fetchone()
        if row is None:
            raise EmailClaimError(403, 'Only the originating browser can email its recent test')
        record = dict(row)
        if record['client_email_status'] != 'not_requested':
            raise EmailClaimError(409, 'This result has already been submitted for email')
        if record['email_status'] in {'queued', 'sent'}:
            raise EmailClaimError(409, 'This result has already been queued or sent to administrators')
        group = notification_group(record, client_ip)
        con.execute('DELETE FROM client_email_audit WHERE created_at<?', (now-86400,))
        count_ip = con.execute('SELECT COUNT(*) FROM client_email_audit WHERE client_ip=?', (client_ip,)).fetchone()[0]
        count_all = con.execute('SELECT COUNT(*) FROM client_email_audit').fetchone()[0]
        if count_ip >= 3 or count_all >= 100:
            raise EmailClaimError(429, 'Email limit reached; administrators can view your result on the dashboard')
        gate = con.execute('SELECT last_at FROM client_email_gates WHERE group_key=?', (group,)).fetchone()
        if gate and gate[0] > now - 3600:
            raise EmailClaimError(429, 'An email was recently requested for this school/VLAN; try later')
        con.execute("""INSERT INTO client_email_gates(group_key,last_at) VALUES(?,?)
          ON CONFLICT(group_key) DO UPDATE SET last_at=excluded.last_at""", (group, now))
        con.execute('INSERT INTO client_email_audit(client_ip,created_at) VALUES(?,?)', (client_ip, now))
        con.execute("UPDATE results SET client_email_status='queued' WHERE id=?", (result_id,))
        return record


def update_client_email(db_path: str, result_id: int, status: str):
    if status not in {'sent', 'failed', 'disabled'}:
        raise ValueError('Invalid email state')
    with connect(db_path) as con:
        con.execute('UPDATE results SET client_email_status=? WHERE id=?', (status, result_id))
