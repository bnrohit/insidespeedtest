#!/usr/bin/env bash
# Run on GMCS Debian VM. Existing secrets untouched, token never printed.
set -Eeuo pipefail
umask 077
[[ $EUID == 0 ]] || exit 1
python3 - <<'PY'
import json,secrets,subprocess
from pathlib import Path
c=json.loads(subprocess.check_output(['docker','inspect','gmcs-inside-speed-test']))[0]
m=[v for v in c['Mounts'] if v['Destination']=='/data']
if len(m)!=1:raise SystemExit('Ambiguous /data mount')
p=Path(m[0]['Source'])/'gmcs-monitoring.token'
if p.exists():
 print('Token already exists. No replacement. Use a controlled rotation procedure.')
else:
 fd=p.open('x');fd.write(secrets.token_urlsafe(48)+'\n');fd.close()
 p.chmod(0o600)
 import os
 os.chown(p,10001,10001)
 print('Generated root-provisioned read-only monitoring token (not displayed).')
print('Copy the token securely into the LibreNMS host /etc/librenms/gmcs-monitoring.token, mode 0600, owner librenms.')
PY
