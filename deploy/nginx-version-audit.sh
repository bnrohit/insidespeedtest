#!/usr/bin/env bash
# Verify a patched open-source Nginx version (as of 2026-10-21).
# Packaged vendor distro releases may backport fixes; verify vendor CVE
# advisories when version string appears lower than these upstream releases.
set -euo pipefail
if ! command -v nginx >/dev/null 2>&1; then
    echo 'UNVERIFIED: Host Nginx not installed. If using the optional container proxy, run:'
    echo '  docker compose -f compose.yaml -f compose.nginx.yaml exec nginx nginx -v'
    exit 2
fi
v=$(nginx -v 2>&1 | sed -nE 's@.*nginx/([0-9]+\.[0-9]+\.[0-9]+).*@\1@p')
if [[ -z "$v" ]]; then echo 'FAIL: Could not parse Nginx version.'; exit 2; fi
IFS=. read -r major minor patch <<< "$v"
pass=1
if (( major > 1 )); then pass=0
elif (( major == 1 )); then
    if (( minor > 31 )); then pass=0
    elif (( minor == 31 && patch >= 7 )); then pass=0
    elif (( minor == 30 && patch >= 6 )); then pass=0
    fi
fi
if (( pass == 0 )); then
  echo "PASS: Nginx $v satisfies 2026-10-21 security floor (stable 1.30.6 / mainline 1.31.7)."
else
  echo "FAIL: Nginx $v is below the upstream October 2026 security floor."
  echo 'Install a patched version from the official Nginx repository, or verify your distribution has backported all applicable fixes.'
  exit 1
fi
nginx -t
