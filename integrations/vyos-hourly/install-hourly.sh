#!/usr/bin/env bash
# Separate opt-in installer: does not alter the existing daily timer, SSH router
# configuration, Docker Compose, Nginx, .env, school mappings or SMTP settings.
set -Eeuo pipefail
umask 077
[[ $EUID == 0 ]] || { echo 'Run using sudo bash' >&2; exit 1; }
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for file in /opt/gmcs-router-report/morning_report.py /etc/gmcs-router-report/config.json /etc/gmcs-router-report/sites.csv; do
  [[ -f "$file" ]] || { echo "Missing existing collector prerequisite: $file" >&2; exit 1; }
done
# Validate /data location before writing a monitoring token or installing schedules.
python3 - <<'PY'
import json,subprocess
from pathlib import Path
c=json.loads(subprocess.check_output(['docker','inspect','gmcs-inside-speed-test']))[0]
m=[v for v in c['Mounts'] if v['Destination']=='/data']
if len(m)!=1 or not (Path(m[0]['Source'])/'results.sqlite3').is_file():
    raise SystemExit('Existing Docker results volume is not identifiable')
PY
install -d -m 700 /opt/gmcs-router-hourly /etc/gmcs-router-hourly /var/lib/gmcs-router-hourly/csv
install -m 0644 "$SOURCE/run_hourly.py" /opt/gmcs-router-hourly/run_hourly.py
if [[ ! -f /etc/gmcs-router-hourly/config.json ]]; then
  install -m 0600 "$SOURCE/config.example.json" /etc/gmcs-router-hourly/config.json
fi
install -m 0644 "$SOURCE/gmcs-router-hourly.service" /etc/systemd/system/gmcs-router-hourly.service
install -m 0644 "$SOURCE/gmcs-router-hourly.timer" /etc/systemd/system/gmcs-router-hourly.timer
python3 /opt/gmcs-router-hourly/run_hourly.py --dry-run
systemctl daemon-reload
# Actual tests begin only after operator explicitly enables the timer.
echo 'Installed but NOT ENABLED. Review /etc/gmcs-router-hourly/config.json first.'
echo 'Enable: sudo systemctl enable --now gmcs-router-hourly.timer'
echo 'Test once: sudo systemctl start gmcs-router-hourly.service'
echo 'Check: sudo journalctl -u gmcs-router-hourly.service -n 45 --no-pager'
