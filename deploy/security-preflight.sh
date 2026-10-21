#!/usr/bin/env bash
set -euo pipefail

# Host-side deployment preflight for the internal speed-test VM.
# Current security baseline (2026-10-21):
#   - NGINX stable >= 1.30.6, or mainline >= 1.31.7
#   - no active Bonjour/mDNS/ZeroConf responder
#   - no UDP/5353 listener

fail=0

version_ok() {
  local version="$1"
  local major minor patch
  IFS=. read -r major minor patch <<<"$version"

  if (( major > 1 )); then return 0; fi
  if (( major < 1 )); then return 1; fi

  if (( minor < 30 )); then return 1; fi
  if (( minor == 30 )); then (( patch >= 6 )); return; fi
  if (( minor == 31 )); then (( patch >= 7 )); return; fi
  return 0
}

echo "== NGINX version =="
if ! command -v nginx >/dev/null 2>&1; then
  echo "ERROR: nginx is not installed. Install a patched release before deployment."
  fail=1
else
  raw="$(nginx -v 2>&1 || true)"
  version="$(sed -nE 's#.*nginx/([0-9]+\.[0-9]+\.[0-9]+).*#\1#p' <<<"$raw")"
  if [[ -z "$version" ]]; then
    echo "ERROR: could not parse nginx version from: $raw"
    fail=1
  elif version_ok "$version"; then
    echo "PASS: nginx $version meets the current baseline."
  else
    echo "ERROR: nginx $version is below the current baseline."
    echo "       Require stable >=1.30.6 or mainline >=1.31.7."
    fail=1
  fi
fi

echo "== Bonjour/mDNS/ZeroConf =="
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet avahi-daemon 2>/dev/null; then
  echo "ERROR: avahi-daemon is active. Disable it on this server."
  fail=1
fi

if command -v pgrep >/dev/null 2>&1 && pgrep -x avahi-daemon >/dev/null 2>&1; then
  echo "ERROR: avahi-daemon process is running."
  fail=1
fi

if command -v ss >/dev/null 2>&1; then
  mdns="$(ss -H -lunp 2>/dev/null | awk '$5 ~ /:5353$/ {print}' || true)"
  if [[ -n "$mdns" ]]; then
    echo "ERROR: UDP/5353 is listening:"
    echo "$mdns"
    fail=1
  else
    echo "PASS: no UDP/5353 listener detected."
  fi
else
  echo "WARNING: ss command not available; verify UDP/5353 manually."
fi

if (( fail != 0 )); then
  echo "Security preflight FAILED."
  exit 1
fi

echo "Security preflight PASSED."
