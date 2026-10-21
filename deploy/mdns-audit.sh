#!/usr/bin/env bash
# Inspect the VM for Bonjour/mDNS exposure. Never silently mutate the host.
# With --apply, disable common Linux responders and block UDP 5353 via UFW,
# if UFW is already active. Additional mDNS programs must be handled manually.
set -euo pipefail
mode="${1:---check}"
if [[ "$mode" != '--check' && "$mode" != '--apply' ]]; then
  echo 'Usage: sudo bash deploy/mdns-audit.sh [--check|--apply]' >&2; exit 2
fi

check_listeners() {
  echo '--- UDP/5353 listeners ---'
  if ! command -v ss >/dev/null 2>&1; then
    echo 'UNVERIFIED: ss is not installed (install iproute2).'; return 2
  fi
  # -H suppresses header. Includes IPv4/IPv6. Listening 5353 might be another
  # responder; do not assume all listeners belong to Avahi.
  local found
  found=$(ss -H -lunp 2>/dev/null | awk '$5 ~ /:5353$/ || $5 ~ /\]:5353$/ {print}')
  if [[ -n "$found" ]]; then
    echo "$found"
    return 1
  fi
  echo 'PASS: No local UDP/5353 listener shown by ss.'
  return 0
}

echo '=== GMCS VM mDNS/Bonjour exposure check (IPv4 + IPv6) ==='
echo 'This is a host-service check, not an Nginx feature.'
if command -v systemctl >/dev/null 2>&1; then
  for svc in avahi-daemon.service avahi-daemon.socket; do
    systemctl is-active "$svc" 2>/dev/null || true
    systemctl is-enabled "$svc" 2>/dev/null || true
  done
fi
if [[ "$mode" == '--apply' ]]; then
  if [[ $EUID -ne 0 ]]; then echo 'ERROR: --apply requires sudo/root.' >&2; exit 2; fi
  echo 'Disabling Avahi only; confirm no other application needs local service discovery.'
  if command -v systemctl >/dev/null 2>&1; then
    for svc in avahi-daemon.socket avahi-daemon.service; do
      if systemctl list-unit-files "$svc" --no-legend 2>/dev/null | grep -q '^'; then
        systemctl disable --now "$svc" || true
        systemctl mask "$svc" || true
      fi
    done
  fi
  if command -v ufw >/dev/null 2>&1 && ufw status | grep -Eq '^Status: active'; then
    ufw deny in 5353/udp comment 'GMCS speed test: block Bonjour mDNS' || true
    echo 'UFW rule added; verify both IPv4 and IPv6 rules (IPV6=yes in /etc/default/ufw).'
  else
    echo 'WARNING: UFW is not active. Enforce UDP/5353 denial at your existing host and network firewall.'
    echo 'Do NOT blindly enable UFW: it might block SSH to this VM.'
  fi
fi
status=0
check_listeners || status=$?
echo '--- systemd-resolved multicast DNS configuration ---'
if command -v resolvectl >/dev/null 2>&1; then
  resolvectl status 2>/dev/null | grep -iE 'MulticastDNS|LLMNR' | head -n 8 || true
  echo 'If MulticastDNS is enabled, disable it under /etc/systemd/resolved.conf.d/ and restart systemd-resolved in a maintenance window.'
fi
echo '--- UFW state (if installed) ---'
if command -v ufw >/dev/null 2>&1; then ufw status | head -n 15 || true; fi
echo '--- Network validation (from a different school/admin segment) ---'
echo '  nmap -sU -Pn -p 5353 --reason <speedtest-vm-ip>'
echo '  sudo tcpdump -ni <vm-interface> udp port 5353'
echo 'NOTE: filtered|open result is not proof of a responsive mDNS service; verify with an authorized mDNS-specific scan.'
if [[ "$status" -ne 0 ]]; then echo 'FAIL/UNVERIFIED: UDP/5353 listener still visible. Identify the process above.' >&2; exit 1; fi
