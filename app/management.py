"""Local VM-only management configuration, never committed to the public repository.

Files are persisted below the writable data volume with restrictive permissions. A
single Uvicorn worker is used, and config objects are swapped atomically in-process.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import hashlib
import ipaddress
from dataclasses import replace
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .identity import IdentityMatcher
from .agents import Agents, AGENT_ID_RE

CONFIG_LOCK = RLock()
HOST_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$')
MAIL_RE = re.compile(r'^[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$')


class SMTPForm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    host: str = Field(default='', max_length=253)
    port: int = Field(default=25, ge=1, le=65535)
    tls_mode: str = Field(default='starttls')
    username: str = Field(default='', max_length=254)
    password: str | None = Field(default=None, max_length=1024)
    clear_password: bool = False
    sender: str = Field(default='', max_length=254)
    recipients: str = Field(default='', max_length=1000)
    email_browser_results: bool = True
    email_agent_results: bool = True
    dedupe_seconds: int = Field(default=86400, ge=300, le=604800)

    @field_validator('host')
    @classmethod
    def host_validation(cls, v: str):
        v = v.strip()
        if v and not HOST_RE.fullmatch(v):
            raise ValueError('Host must be a plain hostname or IP address, without a URL or port')
        return v

    @model_validator(mode='after')
    def check_mail(self):
        if self.tls_mode not in {'ssl', 'starttls', 'none'}:
            raise ValueError('TLS mode must be ssl, starttls, or none')
        if self.username and self.tls_mode == 'none':
            raise ValueError('SMTP authentication requires encrypted transport')
        if self.clear_password and self.password:
            raise ValueError('Cannot both clear and replace password')
        for addr in ([self.sender] if self.sender else []) + [x.strip() for x in self.recipients.split(',') if x.strip()]:
            if not MAIL_RE.fullmatch(addr) or '\n' in addr or '\r' in addr:
                raise ValueError('Use simple, valid email addresses separated by commas')
        return self


class CSVForm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    csv_text: str = Field(min_length=24, max_length=150_000)


class AgentForm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    agent_id: str = Field(min_length=1, max_length=64)
    allowed_cidr: str = Field(min_length=3, max_length=49)

    @field_validator('agent_id')
    @classmethod
    def validate_id(cls, val):
        if not AGENT_ID_RE.fullmatch(val):
            raise ValueError('Use letters, digits, underscore, dot, or dash only')
        return val

    @field_validator('allowed_cidr')
    @classmethod
    def validate_cidr(cls, val):
        parsed = ipaddress.ip_network(val, strict=True)
        # Restrict agent to a specific host to limit damage from token disclosure.
        if parsed.num_addresses != 1:
            raise ValueError('Use an individual server IP (/32 for IPv4, /128 for IPv6)')
        if not parsed.is_private:
            raise ValueError('Agent IP must be on a private network')
        return str(parsed)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        tmp.unlink(missing_ok=True)


def managed_paths(db_path: str) -> dict[str, Path]:
    base = Path(db_path).resolve().parent / 'managed'
    return {'mappings': base / 'networks.csv', 'agents': base / 'agents.csv', 'smtp': base / 'smtp.json'}


def setup_managed(db_path: str, original_mapping: str, original_agents: str) -> dict[str, Path]:
    paths = managed_paths(db_path)
    with CONFIG_LOCK:
        paths['mappings'].parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(paths['mappings'].parent, 0o700)
        for key, source in [('mappings', original_mapping), ('agents', original_agents)]:
            if not paths[key].exists():
                data = Path(source).read_text(encoding='utf-8-sig')
                _atomic_write(paths[key], data)
    return paths


def load_smtp(path: Path, defaults):
    if not path.exists():
        return defaults
    with CONFIG_LOCK:
        obj = json.loads(path.read_text(encoding='utf-8'))
    return replace(defaults, smtp_host=obj.get('host', ''), smtp_port=obj.get('port', 25),
                   smtp_tls_mode=obj.get('tls_mode', 'starttls'),
                   smtp_username=obj.get('username', ''), smtp_password=obj.get('password', ''),
                   smtp_from=obj.get('sender', ''),
                   smtp_to=tuple(x.strip() for x in obj.get('recipients', '').split(',') if x.strip()),
                   email_browser_results=obj.get('email_browser_results', True),
                   email_agent_results=obj.get('email_agent_results', True),
                   email_dedupe_seconds=obj.get('dedupe_seconds', 86400))


def smtp_public_config(path: Path, defaults):
    cfg = load_smtp(path, defaults)
    return {'host': cfg.smtp_host, 'port': cfg.smtp_port, 'tls_mode': cfg.smtp_tls_mode,
            'username': cfg.smtp_username, 'password_configured': bool(cfg.smtp_password),
            'sender': cfg.smtp_from, 'recipients': ', '.join(cfg.smtp_to),
            'email_browser_results': cfg.email_browser_results,
            'email_agent_results': cfg.email_agent_results, 'dedupe_seconds': cfg.email_dedupe_seconds}


def save_smtp(path: Path, form: SMTPForm, defaults):
    with CONFIG_LOCK:
        previous = load_smtp(path, defaults)
        obj = form.model_dump(exclude={'clear_password'})
        if form.clear_password:
            obj['password'] = ''
        elif form.password is None or form.password == '':
            obj['password'] = previous.smtp_password
        _atomic_write(path, json.dumps(obj, indent=2) + '\n')
    return smtp_public_config(path, defaults)


def validate_mapping_csv(text: str) -> IdentityMatcher:
    if '\x00' in text:
        raise ValueError('NUL byte not allowed')
    # Avoid side-effects by validating from memory before any file changes.
    reader = csv.DictReader(io.StringIO(text))
    headers = ['scope', 'school', 'vlan', 'cidr', 'label']
    if not reader.fieldnames or not set(headers).issubset(reader.fieldnames):
        raise ValueError('Required headers: ' + ','.join(headers))
    rows = []
    for n, row in enumerate(reader, 2):
        if not any(str(v or '').strip() for v in row.values()):
            continue
        if None in row:
            raise ValueError(f'Row {n}: extra CSV columns')
        scope, school, vlan, cidr, label = (str(row.get(k) or '').strip() for k in headers)
        if not school or len(school) > 100 or '\r' in school or '\n' in school:
            raise ValueError(f'Row {n}: invalid school')
        if len(label) > 200:
            raise ValueError(f'Row {n}: label too long')
        if scope not in {'school', 'vlan'} or (scope == 'school' and vlan) or (scope == 'vlan' and (not vlan.isdecimal() or not 1 <= int(vlan) <= 4094)):
            raise ValueError(f'Row {n}: invalid scope/VLAN')
        subnet = ipaddress.ip_network(cidr, strict=True)
        if subnet.is_global or subnet.is_multicast or subnet.is_unspecified:
            raise ValueError(f'Row {n}: use a nonpublic client range')
        rows.append((scope, school, vlan, subnet, label))
    if len(rows) > 2000:
        raise ValueError('Too many mapping rows')
    # A duplicated exact school subnet with conflicting labels is ambiguous.
    schools = {}
    for row in rows:
        if row[0] == 'school':
            prev = schools.get(str(row[3]))
            if prev is not None and prev != row[1]:
                raise ValueError(f'Conflicting school identities for {row[3]}')
            schools[str(row[3])] = row[1]
    # VLAN CIDRs cannot overlap with a different identity; such a record is ambiguous.
    vlan_rows = [r for r in rows if r[0] == 'vlan']
    for i, a in enumerate(vlan_rows):
        for b in vlan_rows[:i]:
            if a[3].overlaps(b[3]) and (a[1], a[2]) != (b[1], b[2]):
                raise ValueError(f'Conflicting overlapping VLAN subnets: {a[3]} and {b[3]}')
    from .identity import NetworkEntry
    entries = [NetworkEntry(scope, school, vlan, subnet, label) for scope, school, vlan, subnet, label in rows]
    return IdentityMatcher(entries)


def put_mappings(path: Path, text: str):
    m = validate_mapping_csv(text)
    with CONFIG_LOCK:
        _atomic_write(path, text)
    return m


def list_agents(path: Path) -> list[dict]:
    agents = Agents(str(path))
    return [{'agent_id': k, 'allowed_cidr': str(row.allowed_cidr)} for k, row in sorted(agents.rows.items())]


def put_agent(path: Path, form: AgentForm) -> tuple[Agents, str]:
    with CONFIG_LOCK:
        agents = Agents(str(path))
        if form.agent_id in agents.rows:
            raise ValueError('Server ID already exists')
        key = secrets.token_urlsafe(48)
        digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
        with path.open(newline='', encoding='utf-8-sig') as fp:
            reader = csv.DictReader(fp)
            rows = list(reader)
        rows.append({'agent_id': form.agent_id, 'token_sha256': digest, 'allowed_cidr': form.allowed_cidr})
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['agent_id', 'token_sha256', 'allowed_cidr'], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
        _atomic_write(path, output.getvalue())
        return Agents(str(path)), key


def remove_agent(path: Path, agent_id: str):
    with CONFIG_LOCK:
        agent_list = Agents(str(path))
        if agent_id not in agent_list.rows:
            raise ValueError('Server ID not found')
        rows = [{'agent_id': k, 'token_sha256': v.token_sha256, 'allowed_cidr': str(v.allowed_cidr)}
                for k, v in agent_list.rows.items() if k != agent_id]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['agent_id', 'token_sha256', 'allowed_cidr'], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
        _atomic_write(path, output.getvalue())
        return Agents(str(path))