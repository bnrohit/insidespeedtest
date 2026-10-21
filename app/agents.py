"""Per-host credentials, bound to an IP subnet as observed on the VM.

Never keep plaintext secrets in Git: publish only a header-only config file.
"""
from __future__ import annotations

import csv
import hashlib
import ipaddress
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class Agent:
    agent_id: str
    token_sha256: str
    allowed_cidr: ipaddress.IPv4Network | ipaddress.IPv6Network


class Agents:
    def __init__(self, filename: str):
        self.rows: dict[str, Agent] = {}
        with Path(filename).open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or not {"agent_id", "token_sha256", "allowed_cidr"}.issubset(reader.fieldnames):
                raise ValueError("Agents config must have agent_id,token_sha256,allowed_cidr")
            for i, row in enumerate(reader, 2):
                if not any((x or "").strip() for x in row.values()):
                    continue
                key = (row["agent_id"] or "").strip()
                digest = (row["token_sha256"] or "").strip().lower()
                if not AGENT_ID_RE.fullmatch(key) or not re.fullmatch(r"[a-f0-9]{64}", digest) or key in self.rows:
                    raise ValueError(f"Invalid or duplicate agent on row {i}")
                cidr = ipaddress.ip_network((row["allowed_cidr"] or "").strip(), strict=True)
                self.rows[key] = Agent(key, digest, cidr)

    def authenticate(self, agent_id: str, token: str, observed_ip: str) -> bool:
        row = self.rows.get(agent_id)
        if not row or len(token) < 32 or len(token) > 256:
            return False
        try:
            ip = ipaddress.ip_address(observed_ip)
        except ValueError:
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip in row.allowed_cidr and secrets.compare_digest(
            hashlib.sha256(token.encode("utf-8")).hexdigest(), row.token_sha256
        )
