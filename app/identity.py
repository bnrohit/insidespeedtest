"""Map a network client's observed IP address to its school and VLAN.

No VLAN is guessed from octets: only an explicitly configured subnet may identify it.
"""
from __future__ import annotations

import csv
import ipaddress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NetworkEntry:
    scope: str
    school: str
    vlan: str
    subnet: ipaddress.IPv4Network | ipaddress.IPv6Network
    label: str


class IdentityMatcher:
    def __init__(self, entries: list[NetworkEntry]):
        self.entries = sorted(entries, key=lambda e: e.subnet.prefixlen, reverse=True)

    @classmethod
    def from_csv(cls, filename: str | Path) -> "IdentityMatcher":
        filename = Path(filename)
        if not filename.exists():
            raise FileNotFoundError(f"Missing subnet mapping file: {filename}")
        entries = []
        with filename.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"scope", "school", "vlan", "cidr", "label"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError(f"Mapping CSV must contain headers: {', '.join(sorted(required))}")
            for row_num, row in enumerate(reader, 2):
                if not any((v or "").strip() for v in row.values()):
                    continue
                scope = (row["scope"] or "").strip().lower()
                school = (row["school"] or "").strip()
                vlan = (row["vlan"] or "").strip()
                label = (row["label"] or "").strip()
                if scope not in {"school", "vlan"} or not school:
                    raise ValueError(f"Mapping row {row_num}: expected scope=school/vlan and school name")
                if scope == "vlan" and (not vlan.isdigit() or not 1 <= int(vlan) <= 4094):
                    raise ValueError(f"Mapping row {row_num}: invalid VLAN ID")
                if scope == "school" and vlan:
                    raise ValueError(f"Mapping row {row_num}: school scope must leave VLAN empty")
                subnet = ipaddress.ip_network((row["cidr"] or "").strip(), strict=True)
                entries.append(NetworkEntry(scope, school, vlan, subnet, label))
        # Equal-prefix duplicate ranges with conflicting identities are ambiguous.
        seen = {}
        for entry in entries:
            k = (entry.scope, str(entry.subnet))
            if k in seen and seen[k] != (entry.school, entry.vlan):
                raise ValueError(f"Conflicting mapping for {entry.subnet} ({entry.scope})")
            seen[k] = (entry.school, entry.vlan)
        return cls(entries)

    def lookup(self, source_ip: str) -> dict[str, str]:
        try:
            address = ipaddress.ip_address(source_ip)
        except ValueError:
            return {"school": "Unknown", "vlan": "Unknown", "network_label": "Unmapped client"}
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        school = next((e for e in self.entries if e.scope == "school" and address in e.subnet), None)
        vlan = next((e for e in self.entries if e.scope == "vlan" and address in e.subnet), None)
        # Prefer a more-specific VLAN mapping for both school and VLAN, but
        # an independently matched school may be a useful fallback.
        return {
            "school": vlan.school if vlan else (school.school if school else "Unknown"),
            "vlan": str(int(vlan.vlan)) if vlan else "Unknown",
            "network_label": (vlan.label or "Configured VLAN") if vlan else (school.label or "School site range") if school else "Unmapped client",
        }
