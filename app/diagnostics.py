"""Bounded, consent-based diagnostic snapshots associated with a completed test.

No remote command execution. A browser cannot read MAC, routes, ARP, DNS cache or
running sockets. Optional OS reports must be reviewed and uploaded by the user.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import secrets
from .database import connect

ALLOWED_COMMANDS = frozenset({
    'hostname', 'ipconfig', 'ifconfig', 'getmac', 'interfaces', 'gateway',
    'routes', 'dns_servers', 'ping_internal', 'ping_internal_backup',
    'ping_external', 'nslookup_internal', 'nslookup_google',
    'traceroute_internal', 'traceroute_external', 'netstat', 'arp',
    'dns_cache', 'flush_dns'
})
MAX_COMMAND_CHARS = 3600
MAX_REPORT_CHARS = 34000
PAIR_SECONDS = 600


def init_diagnostics(db_path: str):
    with connect(db_path) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS client_diagnostics (
            result_id INTEGER PRIMARY KEY REFERENCES results(id),
            token_hash TEXT NOT NULL,
            client_ip TEXT NOT NULL,
            browser_json TEXT NOT NULL DEFAULT '{}',
            advanced_json TEXT,
            advanced_at INTEGER,
            created_at INTEGER NOT NULL
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_client_diag_ip ON client_diagnostics(client_ip)')
        con.execute("""CREATE TABLE IF NOT EXISTS diagnostic_upload_codes (
          code_hash TEXT PRIMARY KEY,
          result_id INTEGER NOT NULL UNIQUE,
          client_ip TEXT NOT NULL,
          expires_at INTEGER NOT NULL
        )""")
        con.execute('CREATE INDEX IF NOT EXISTS idx_diag_codes_expires ON diagnostic_upload_codes(expires_at)')
        con.execute('DELETE FROM diagnostic_upload_codes WHERE expires_at <= ?', (int(time.time()),))
        # Minimize retention of client device details; do not keep indefinitely.
        con.execute('DELETE FROM client_diagnostics WHERE created_at<?', (int(time.time())-30*86400,))


def record_browser(db_path: str, result_id: int, token: str, ip: str, browser: dict):
    with connect(db_path) as con:
        con.execute('''INSERT INTO client_diagnostics
          (result_id,token_hash,client_ip,browser_json,created_at)
          VALUES (?,?,?,?,?)''', (result_id, hashlib.sha256(token.encode()).hexdigest(),
                             ip, json.dumps(browser, separators=(',', ':')), int(time.time())))


def validate_advanced(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != {'platform', 'hostname', 'commands'}:
        raise ValueError('Expected platform, hostname and commands fields')
    if data['platform'] not in {'Windows', 'macOS'}:
        raise ValueError('Only Windows or macOS diagnostic bundles are accepted')
    if not isinstance(data['hostname'], str) or len(data['hostname']) > 100:
        raise ValueError('Hostname is not valid')
    commands = data['commands']
    if not isinstance(commands, dict) or not commands or not set(commands).issubset(ALLOWED_COMMANDS):
        raise ValueError('Unexpected diagnostic command labels')
    if any(not isinstance(k, str) or not isinstance(v, str) or len(v) > MAX_COMMAND_CHARS
           for k, v in commands.items()):
        raise ValueError('One of the diagnostic sections is too large')
    if len(json.dumps(data, ensure_ascii=True)) > MAX_REPORT_CHARS:
        raise ValueError('Diagnostic report exceeds the safe size limit')
    return data


def submit_advanced(db_path: str, result_id: int, token: str, ip: str, data: dict) -> bool:
    """One submission per completed browser result, authenticated by IP and test secret."""
    content = json.dumps(validate_advanced(data), separators=(',', ':'))
    with connect(db_path) as con:
        con.execute('BEGIN IMMEDIATE')
        result = con.execute('''UPDATE client_diagnostics
           SET advanced_json=?,advanced_at=?
           WHERE result_id=? AND client_ip=? AND token_hash=? AND advanced_at IS NULL
             AND created_at>=? AND EXISTS
             (SELECT 1 FROM results r WHERE r.id=client_diagnostics.result_id
              AND r.agent_id='' AND r.client_ip=client_diagnostics.client_ip)''',
             (content, int(time.time()), result_id, ip,
              hashlib.sha256(token.encode()).hexdigest(), int(time.time())-86400))
        return result.rowcount == 1


def issue_upload_code(db_path: str, result_id: int, token: str, ip: str) -> dict | None:
    """Short-lived one-time pairing code only the original test browser may request."""
    now = int(time.time())
    code = secrets.token_urlsafe(24)
    with connect(db_path) as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('DELETE FROM diagnostic_upload_codes WHERE expires_at <= ?', (now,))
        row = con.execute("""SELECT 1 FROM client_diagnostics d JOIN results r ON r.id=d.result_id
          WHERE d.result_id=? AND d.client_ip=? AND d.token_hash=?
          AND d.advanced_at IS NULL AND d.created_at>=? AND r.agent_id='' AND r.client_ip=?""",
          (result_id, ip, hashlib.sha256(token.encode()).hexdigest(), now-86400, ip)).fetchone()
        if row is None:
            return None
        # Rotating the code invalidates the previous one. No plaintext codes in SQLite.
        con.execute('DELETE FROM diagnostic_upload_codes WHERE result_id=?', (result_id,))
        con.execute("""INSERT INTO diagnostic_upload_codes(code_hash,result_id,client_ip,expires_at)
          VALUES (?,?,?,?)""", (hashlib.sha256(code.encode()).hexdigest(),result_id,ip,now+PAIR_SECONDS))
    return {'upload_code':code,'expires_in_seconds':PAIR_SECONDS,'result_id':result_id}


def submit_paired(db_path: str, code: str, ip: str, data: dict) -> int | None:
    """Atomically redeem paired report; exact source IP and one submission only."""
    report = json.dumps(validate_advanced(data), separators=(',', ':'))
    now = int(time.time())
    with connect(db_path) as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("""SELECT p.result_id FROM diagnostic_upload_codes p
          JOIN client_diagnostics d ON d.result_id=p.result_id
          JOIN results r ON r.id=p.result_id
          WHERE p.code_hash=? AND p.client_ip=? AND p.expires_at>?
            AND d.client_ip=? AND d.advanced_at IS NULL AND d.created_at>=?
            AND r.agent_id='' AND r.client_ip=?""",
          (hashlib.sha256(code.encode()).hexdigest(),ip,now,ip,now-86400,ip)).fetchone()
        if row is None:
            return None
        rid=int(row['result_id'])
        changed=con.execute("""UPDATE client_diagnostics
          SET advanced_json=?,advanced_at=? WHERE result_id=? AND advanced_at IS NULL""",
          (report,now,rid)).rowcount
        if changed!=1:
            return None
        con.execute('DELETE FROM diagnostic_upload_codes WHERE result_id=?', (rid,))
    return rid


def fetch_report(db_path: str, result_id: int) -> dict | None:
    with connect(db_path) as con:
        row = con.execute('''SELECT r.*, d.browser_json, d.advanced_json, d.advanced_at
            FROM results r LEFT JOIN client_diagnostics d ON r.id=d.result_id
            WHERE r.id=?''', (result_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out['browser'] = json.loads(out.pop('browser_json') or '{}')
    out['advanced'] = json.loads(out.pop('advanced_json') or 'null')
    out['assessment'] = assess(out)
    return out


def assess(record: dict) -> list[dict]:
    """Interpret symptoms without pretending to identify a fault location."""
    found = []
    def add(severity, area, observation, suggestion):
        found.append({'severity':severity, 'area':area,
                      'observation':observation, 'next_step':suggestion})
    loss = record.get('packet_loss_pct')
    jitter = record.get('jitter_ms')
    latency = record.get('latency_ms')
    try:
        if loss is not None and math.isfinite(float(loss)) and float(loss) >= 10:
            add('high', 'School-to-NOC HTTP requests',
                f"{float(loss):.0f}% of browser HTTP latency probes failed; this is not ICMP packet loss.",
                'Inspect client Wi-Fi, VLAN uplink, school VyOS/WAN counters and the NOC test service.')
        if latency is not None and math.isfinite(float(latency)) and float(latency) >= 80:
            add('warning', 'School-to-NOC latency', f"Browser HTTP latency measured {float(latency):.1f} ms.",
                'Compare same-site wired tests and VyOS/WAN RTT; inspect queue drops and circuit utilization.')
        if jitter is not None and math.isfinite(float(jitter)) and float(jitter) >= 30:
            add('warning', 'Path consistency', f"Browser HTTP jitter measured {float(jitter):.1f} ms.",
                'Repeat on Ethernet and inspect Wi-Fi interference, congestion and QoS counters.')
        for direction in ('download_mbps', 'upload_mbps'):
            rate = record.get(direction)
            if rate is not None and math.isfinite(float(rate)) and float(rate) < 5:
                add('warning', 'Internal throughput', f"{direction.replace('_',' ')} measured {float(rate):.1f} Mbps to the NOC VM.",
                    'Compare with same-VLAN wired baseline; check speed-test host load, circuit shaping, interface errors and ACLs.')
    except (ValueError, TypeError, OverflowError):
        pass
    advanced = record.get('advanced') or {}
    commands = advanced.get('commands') or {}
    for key in ('ping_internal','ping_external','nslookup_internal','nslookup_google'):
        value = commands.get(key, '').lower()
        if not value:
            continue
        if any(x in value for x in ['could not find host', 'unknown host', 'name or service not known', 'server failed', 'timed out', '100% packet loss', '100% loss', 'request timed out']):
            if key == 'ping_internal':
                add('warning','Internal DNS-server reachability','Diagnostic output indicates failed responses to internal DNS IP.',
                    'Check DNS server availability and VLAN-to-DNS ACLs; note ICMP may be filtered even if DNS works.')
            elif key == 'nslookup_internal':
                add('warning','Internal DNS resolution','A local DNS lookup reported an error.',
                    'Check configured resolvers, routing, DNS firewall policy and DNS service health.')
            elif key == 'ping_external':
                add('warning','Internet ICMP reachability','External ping returned a failure indication.',
                    'Check default route, VyOS NAT/firewall, ISP egress; ICMP blocking alone does not prove Internet outage.')
            else:
                add('warning','Public DNS resolution','Public DNS lookup reported an error.',
                    'Compare internal DNS resolution and HTTPS browser access before concluding Internet is down.')
    if not found:
        add('info','No decisive fault signature',
            'Available measurements do not establish an obvious failure. This is not proof the network is healthy.',
            'Compare a known-good device at the same site, run separate Internet test and review WAN/VM counters.')
    return found[:8]
