#!/bin/sh
# Opt-in installer: does NOT activate schedules, alter firewall or edit SNMP.
set -eu
umask 077
[ "$(id -u)" -eq 0 ] || { echo 'Use sudo to run installer' >&2; exit 1; }
command -v systemctl >/dev/null || { echo 'systemd is required' >&2; exit 1; }
command -v useradd >/dev/null || { echo 'useradd is required' >&2; exit 1; }
[ -x /usr/bin/python3 ] || { echo 'Python 3 missing at /usr/bin/python3' >&2; exit 1; }
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH='' cd -- "$HERE/../.." && pwd)
[ -f "$ROOT/agent/school_agent.py" ] || { echo 'Must run from full GitHub checkout' >&2; exit 1; }
[ -f "$ROOT/integrations/vyos-snmp-direct/collect.py" ] || exit 1
id gmcs-speedtest >/dev/null 2>&1 ||
    useradd --system --no-create-home --shell /usr/sbin/nologin gmcs-speedtest
install -d -m 0755 /opt/gmcs-speedtest-direct
install -m 0755 "$ROOT/agent/school_agent.py" /opt/gmcs-speedtest-direct/school_agent.py
install -m 0755 "$ROOT/integrations/vyos-snmp-direct/collect.py" /opt/gmcs-speedtest-direct/collect.py
install -m 0755 "$ROOT/integrations/vyos-snmp-direct/extend.py" /opt/gmcs-speedtest-direct/extend.py
install -d -m 0750 -o root -g gmcs-speedtest /etc/gmcs-speedtest
install -d -m 0755 -o gmcs-speedtest -g gmcs-speedtest /var/lib/gmcs-speedtest-direct
if [ ! -e /etc/gmcs-speedtest/direct.json ]; then
  install -m 0640 -o root -g gmcs-speedtest "$HERE/direct.example.json" /etc/gmcs-speedtest/direct.json
fi
install -m 0644 "$HERE/gmcs-speedtest-direct.service" /etc/systemd/system/gmcs-speedtest-direct.service
install -m 0644 "$HERE/gmcs-speedtest-direct.timer" /etc/systemd/system/gmcs-speedtest-direct.timer
systemctl daemon-reload
cat <<'EOF'
Linux direct speed test INSTALLED, NOT ENABLED.
1. Edit /etc/gmcs-speedtest/direct.json (enabled, URL and enrolled agent ID).
2. Provision root:gmcs-speedtest mode 0640 /etc/gmcs-speedtest/token.
3. Provision your trusted CA at /etc/gmcs-speedtest/ca.pem if needed.
4. Test: sudo systemctl start gmcs-speedtest-direct.service
5. Read: sudo -u Debian-snmp /usr/bin/python3 /opt/gmcs-speedtest-direct/extend.py /var/lib/gmcs-speedtest-direct/latest.json
   (replace Debian-snmp with the actual snmpd user).
6. Add to EXISTING /etc/snmp/snmpd.conf (without replacing other lines):
   extend gmcs_vyos_speedtest /usr/bin/python3 /opt/gmcs-speedtest-direct/extend.py /var/lib/gmcs-speedtest-direct/latest.json
7. Restart SNMP ONLY after reviewing your existing SNMP security settings.
8. Enable: sudo systemctl enable --now gmcs-speedtest-direct.timer
Old gmcs-speedtest.timer (if installed) is not automatically disabled.
Do not leave BOTH timers enabled on the same host.
EOF
