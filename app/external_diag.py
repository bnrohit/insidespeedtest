"""Opt-in admin-only NOC/VM Internet egress sampling with fixed public endpoint.

Not a substitute for a school-client's direct Internet measurement.
No user-supplied destinations, redirects, or arbitrary host probing.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from .database import connect

HOST = 'speed.cloudflare.com'
DOWNLOAD_BYTES = 4 * 1024 * 1024
UPLOAD_BYTES = 1 * 1024 * 1024
COOLDOWN = 120


class _PinnedHTTPS(http.client.HTTPSConnection):
    """Connect to already-vetted public IPv4, while validating the HTTPS hostname."""
    def __init__(self, ip: str):
        super().__init__(HOST, 443, timeout=12, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        tcp = socket.create_connection((self._ip, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(tcp, server_hostname=HOST)
        except BaseException:
            tcp.close()
            raise


def _resolve_public_ip() -> tuple[str, float]:
    t = time.perf_counter()
    addresses = socket.getaddrinfo(HOST, 443, socket.AF_INET, socket.SOCK_STREAM)
    ips = {row[4][0] for row in addresses}
    if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
        raise OSError('Public DNS resolved an unsafe/private address')
    return sorted(ips)[0], round((time.perf_counter() - t)*1000, 1)


def _transfer(ip: str, method: str, target: str, size: int) -> tuple[float, float]:
    """Fixed bounded request. Refuses redirects, unexpected response size and partial responses."""
    c = _PinnedHTTPS(ip)
    try:
        started = time.perf_counter()
        c.connect()
        handshake_ms = round((time.perf_counter()-started)*1000,1)
        started = time.perf_counter()
        body = (b'G' * size) if method == 'POST' else None
        c.request(method, target, body=body,
                  headers={'Accept-Encoding':'identity','Cache-Control':'no-store',
                           'Content-Type':'application/octet-stream', 'Connection':'close'})
        response = c.getresponse()
        if response.status != 200:
            raise OSError(f'External provider returned HTTP {response.status}')
        count = 0
        while True:
            block = response.read(min(65536, size + 1 - count))
            if not block:
                break
            count += len(block)
            if count > size:
                raise OSError('External response exceeded its configured size limit')
        elapsed = max(time.perf_counter()-started,0.001)
        if method == 'GET' and count != size:
            raise OSError('Unexpected external sample response length')
        return round((size * 8 / 1_000_000)/elapsed,2), handshake_ms
    finally:
        c.close()


def init_external(db_path: str):
    with connect(db_path) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS external_checks (
           id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
           operator_ip TEXT NOT NULL, status TEXT NOT NULL,
           dns_ms REAL, tls_ms REAL, download_mbps REAL, upload_mbps REAL,
           detail TEXT NOT NULL DEFAULT ''
        )''')


def history(db_path: str) -> list[dict]:
    with connect(db_path) as con:
        rows = con.execute('''SELECT at, status, dns_ms, tls_ms, download_mbps,
            upload_mbps, detail FROM external_checks ORDER BY id DESC LIMIT 10''').fetchall()
    return [dict(r) for r in rows]


def run_external(db_path: str, operator_ip: str) -> dict:
    now = int(time.time())
    with connect(db_path) as con:
        con.execute('BEGIN IMMEDIATE')
        last = con.execute('SELECT at FROM external_checks ORDER BY id DESC LIMIT 1').fetchone()
        if last and now - last[0] < COOLDOWN:
            return {'status': 'cooldown', 'retry_after_seconds': COOLDOWN-(now-last[0])}
        cur = con.execute("INSERT INTO external_checks(at,operator_ip,status) VALUES(?,?,'running')",
                          (now, operator_ip))
        run_id = cur.lastrowid
    values = {'dns_ms':None,'tls_ms':None,'download_mbps':None,'upload_mbps':None}
    try:
        ip, values['dns_ms'] = _resolve_public_ip()
        values['download_mbps'], values['tls_ms'] = _transfer(ip, 'GET', f'/__down?bytes={DOWNLOAD_BYTES}', DOWNLOAD_BYTES)
        values['upload_mbps'], _ = _transfer(ip, 'POST', '/__up', UPLOAD_BYTES)
        status, detail = 'ok', 'Bounded HTTPS sample to Cloudflare edge from the GMCS VM'
    except (OSError, TimeoutError, ValueError, ssl.SSLError, http.client.HTTPException) as exc:
        status, detail = 'failed', f'{type(exc).__name__}: {str(exc)[:140]}'
    with connect(db_path) as con:
        con.execute('''UPDATE external_checks SET status=?,detail=?,dns_ms=?,tls_ms=?,
           download_mbps=?,upload_mbps=? WHERE id=?''',
           (status,detail,values['dns_ms'],values['tls_ms'],values['download_mbps'],values['upload_mbps'],run_id))
    return {'status':status, 'at':now,'target':HOST,**values,'detail':detail}
