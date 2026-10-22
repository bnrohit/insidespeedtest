#!/bin/sh
# Opt-in only; no SNMP changes, router config changes or scheduler changes by installer.
set -eu
umask 077
[ "$(id -u)" -eq 0 ] || { echo 'Root required' >&2; exit 1; }
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
[ -d /config/scripts ] && [ -d /config/auth ] && [ -d /config/user-data ] || {
  echo 'Expected persistent VyOS /config directories not present' >&2; exit 1;
}
for binary in /usr/bin/flock /usr/bin/nice /usr/bin/python3; do
  [ -x "$binary" ] || { echo "Missing $binary" >&2; exit 1; }
done
install -d -m 0755 /config/scripts/gmcs-vyos-speedtest /config/user-data/gmcs-vyos-speedtest
install -d -m 0700 /config/auth/gmcs-speedtest
install -m 0755 "$HERE/collect.py" /config/scripts/gmcs-vyos-speedtest/collect.py
install -m 0755 "$HERE/runner.sh" /config/scripts/gmcs-vyos-speedtest/runner.sh
install -m 0755 "$HERE/extend.py" /config/user-data/gmcs-vyos-speedtest/extend.py
if [ ! -f /config/auth/gmcs-speedtest/direct.json ]; then
  install -m 0600 "$HERE/direct.example.json" /config/auth/gmcs-speedtest/direct.json
fi
chmod 0600 /config/auth/gmcs-speedtest/direct.json
cat <<'EOF'
Installed WITHOUT enabling tests or changing SNMP/ VyOS config.
1. Review /config/auth/gmcs-speedtest/direct.json; enable only the GMCS inside test.
2. Check trusted CA, per-router agent ID and private agent token.
3. Test once: sudo /config/scripts/gmcs-vyos-speedtest/runner.sh
4. Read cached SNMP output: /config/user-data/gmcs-vyos-speedtest/extend.py
5. In VyOS configure mode (ONLY after review):
   set service snmp script-extensions extension-name gmcs_vyos_speedtest script /config/user-data/gmcs-vyos-speedtest/extend.py
   set system task-scheduler task gmcs-vyos-direct crontab-spec '23 * * * *'
   set system task-scheduler task gmcs-vyos-direct executable path '/config/scripts/gmcs-vyos-speedtest/runner.sh'
   commit
   save
6. Configure LibreNMS new application files; test the SNMP extend before discovery.
This does not overwrite an older vyos_speedtest app or its RRD files.
EOF
