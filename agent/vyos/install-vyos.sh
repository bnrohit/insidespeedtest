#!/bin/sh
# Install from an authorized staging copy of the GMCS repository ON a VyOS router.
# Does not modify VyOS running/startup configuration or schedule a task automatically.
set -eu
umask 077
if [ "$(id -u)" -ne 0 ]; then echo 'Use sudo on VyOS' >&2; exit 1; fi
for bin in /usr/bin/python3 /usr/bin/flock /usr/bin/nice; do
  if [ ! -x "$bin" ]; then echo "Required VyOS binary unavailable: $bin" >&2; exit 1; fi
done
SOURCE=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
[ -r "$SOURCE/school_agent.py" ] && [ -r "$SOURCE/vyos/runner.sh" ] || {
  echo 'Stage school_agent.py and agent/vyos/runner.sh together' >&2; exit 1;
}
[ -d /config/scripts ] && [ -d /config/auth ] || {
  echo 'VyOS persistent /config/scripts and /config/auth required' >&2; exit 1;
}
install -d -m 0755 /config/scripts/gmcs-speedtest
install -m 0755 "$SOURCE/school_agent.py" /config/scripts/gmcs-speedtest/school_agent.py
install -m 0755 "$SOURCE/vyos/runner.sh" /config/scripts/gmcs-speedtest/runner.sh
install -d -m 0700 /config/auth/gmcs-speedtest
if [ ! -f /config/auth/gmcs-speedtest/agent.env ]; then
  cat > /config/auth/gmcs-speedtest/agent.env <<'EOF'
# Root-only: replace placeholders and verify the TLS name against the certificate.
SPEEDTEST_URL='https://speedtest.example.edu:18443'
SPEEDTEST_AGENT_ID='EXAMPLE-VYOS01'
# District CA bundle; omit when already trusted by VyOS system trust store.
# SPEEDTEST_CA_FILE='/config/auth/gmcs-speedtest/ca.pem'
EOF
fi
chmod 0600 /config/auth/gmcs-speedtest/agent.env
# NEVER overwrite a configured secret during software upgrades.
if [ ! -e /config/auth/gmcs-speedtest/token ]; then
  install -m 0600 /dev/null /config/auth/gmcs-speedtest/token
fi
chmod 0600 /config/auth/gmcs-speedtest/token
cat <<'EOF'
Installed code only. NO TASK SCHEDULED, NO ROUTER CONFIGURATION CHANGED.
Next: register this router in GMCS Admin > Scheduled Linux school servers,
      with a unique agent ID and its VERIFIED source IP /32.
Securely provision its one-time token to /config/auth/gmcs-speedtest/token
and edit /config/auth/gmcs-speedtest/agent.env for URL/ID/trusted CA.
Pilot: sudo /config/scripts/gmcs-speedtest/runner.sh
Then in VyOS configure mode (select a different minute per school):
 configure
 set system task-scheduler task gmcs-speedtest crontab-spec '17 * * * *'
 set system task-scheduler task gmcs-speedtest executable path '/config/scripts/gmcs-speedtest/runner.sh'
 commit
 save
 exit
Never put credentials in the VyOS task arguments or in GitHub.
EOF
