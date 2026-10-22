#!/usr/bin/env bash
# GMCS Client Troubleshooting v1. No remote execution, no automatic uploads.
# Requires python3 to produce reviewed JSON; does NOT change network settings.
set -u
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 is needed to save JSON. Run python3 --version or ask GMCS IT.' >&2; exit 1
fi
printf '%s\n' 'GMCS diagnostic data remains on this Mac until you review and upload the JSON.'
folder="${HOME}/Desktop"
[ -d "$folder" ] || folder="$HOME"
tmp=$(mktemp -d) || exit 1
trap 'rm -rf "$tmp"' EXIT
out="$folder/gmcs-client-diagnostics-$(date +%Y%m%d-%H%M%S).json"
run_cmd() {
  name=$1; shift
  "$@" > "$tmp/$name" 2>&1 || true
  # Drop potentially unbounded outputs before creating JSON.
  head -c 3500 "$tmp/$name" > "$tmp/short-$name"
}
run_cmd hostname hostname
run_cmd ifconfig ifconfig
run_cmd gateway route -n get default
run_cmd dns_servers scutil --dns
# Discover DNS from this Mac's actual resolver configuration. No private IPs
# are baked into the publicly downloadable script.
dns1=$(scutil --dns 2>/dev/null | awk '/nameserver\[[0-9]+\][[:space:]]*:/ {print $3; exit}')
dns2=$(scutil --dns 2>/dev/null | awk '/nameserver\[[0-9]+\][[:space:]]*:/ {if (!seen[$3]++) {n++; if(n==2){print $3; exit}}}')
if [ -n "$dns1" ]; then
  run_cmd ping_internal ping -c 3 -W 1000 "$dns1"
  run_cmd nslookup_internal nslookup google.com "$dns1"
  run_cmd traceroute_internal /usr/sbin/traceroute -n -m 8 -w 1 -q 1 "$dns1"
fi
if [ -n "$dns2" ]; then
  run_cmd ping_internal_backup ping -c 3 -W 1000 "$dns2"
fi
run_cmd ping_external ping -c 3 -W 1000 8.8.8.8
run_cmd nslookup_google nslookup google.com 8.8.8.8
run_cmd traceroute_external /usr/sbin/traceroute -n -m 8 -w 1 -q 1 8.8.8.8
if [ "${1:-}" = "--include-sensitive" ]; then
  run_cmd interfaces networksetup -listallhardwareports
  run_cmd arp arp -an
  run_cmd netstat netstat -an
  run_cmd dns_cache dscacheutil -cachedump
fi
python3 - "$tmp" "$out" <<'PY'
import json, pathlib, socket, sys
source, out = map(pathlib.Path, sys.argv[1:])
commands = {}
for f in source.glob('short-*'):
    commands[f.name[6:]] = f.read_text(errors='replace')[:3500]
report = {'platform':'macOS','hostname':socket.gethostname()[:100], 'commands':commands}
out.write_text(json.dumps(report, indent=2), encoding='utf-8')
PY
printf 'Diagnostic report saved: %s\n' "$out"
printf '%s\n' 'Review all details before uploading. No network changes were made.'
printf '%s\n' 'Optional authorized DNS cache reset: sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder'
