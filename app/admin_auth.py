"""Revocable, independent per-browser administrator sessions (not HTTP Basic)."""
from __future__ import annotations

import hashlib
import secrets
import time

from .database import connect

COOKIE_NAME = 'gmcs_admin_session'
SESSION_SECONDS = 8 * 3600


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def new_session(db_path: str, client_ip: str, password: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(40)
    csrf_token = secrets.token_urlsafe(32)
    now = int(time.time())
    with connect(db_path) as con:
        con.execute('DELETE FROM admin_sessions WHERE expires_at<=?', (now,))
        con.execute("""INSERT INTO admin_sessions
            (token_hash,csrf_token,client_ip,password_tag,created_at,expires_at)
            VALUES (?,?,?,?,?,?)""",
            (digest(token), csrf_token, client_ip, digest(password), now, now+SESSION_SECONDS))
    return token, csrf_token


def find_session(db_path: str, token: str, client_ip: str, password: str):
    if not token or len(token) > 200:
        return None
    with connect(db_path) as con:
        row = con.execute("""SELECT csrf_token, expires_at FROM admin_sessions
            WHERE token_hash=? AND client_ip=? AND password_tag=? AND expires_at>?""",
            (digest(token), client_ip, digest(password), int(time.time()))).fetchone()
        return dict(row) if row else None


def revoke_session(db_path: str, token: str):
    if token and len(token) <= 200:
        with connect(db_path) as con:
            con.execute('DELETE FROM admin_sessions WHERE token_hash=?', (digest(token),))
