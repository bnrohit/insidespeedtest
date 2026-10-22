#!/usr/bin/env bash
# Upgrade only the GMCS web application from a separate public GitHub checkout.
# Never overwrite private site mappings, credentials, SMTP data or local Compose/Nginx files.
set -Eeuo pipefail
umask 077
ROOT=/home/rohith/insidespeedtest
TARGET=gmcs-inside-speed-test
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if (( EUID != 0 )); then echo 'Run with sudo bash' >&2; exit 1; fi
for tool in docker python3 git curl; do command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }; done
[[ "$SOURCE" != "$ROOT" ]] || { echo 'Use a separate GitHub checkout, not the production directory' >&2; exit 1; }
[[ -f "$ROOT/.env" && -f "$ROOT/app/main.py" && -f "$SOURCE/app/main.py" ]] || {
  echo 'Expected production or GitHub source missing: no changes made' >&2; exit 1;
}
# The source is a git clone; do not run git pull in the live private deployment.
[[ -d "$SOURCE/.git" ]] || { echo 'Source must be a GitHub checkout' >&2; exit 1; }
SOURCE_REV="$(git -C "$SOURCE" rev-parse HEAD)"

# Explicit application allowlist. Everything else stays exactly as configured on this server.
FILES=(
 app/admin_auth.py app/client_email.py app/database.py app/emailer.py app/main.py
 app/static/admin.html app/static/admin.js app/static/index.html
 app/static/login.html app/static/login.js app/static/style.css app/static/test.js
)
for rel in "${FILES[@]}"; do
  [[ -f "$SOURCE/$rel" && "$rel" == app/* ]] || { echo "Missing safe source file: $rel" >&2; exit 1; }
done

# Locate exact current Compose files, including custom override(s).
readarray -d '' COMPOSE < <(python3 - "$ROOT" "$TARGET" <<'PY'
import json, os, subprocess, sys
from pathlib import Path
root, target = sys.argv[1:]
c = json.loads(subprocess.check_output(['docker', 'inspect', target]))[0]
labels = c['Config'].get('Labels') or {}
project, service = labels.get('com.docker.compose.project'), labels.get('com.docker.compose.service')
workdir, filenames = labels.get('com.docker.compose.project.working_dir'), labels.get('com.docker.compose.project.config_files')
if not all([project, service, workdir, filenames]) or Path(workdir).resolve() != Path(root).resolve():
    raise SystemExit('Unable to identify current production Compose project')
cmd=['docker','compose','-p',project]
for value in filenames.split(','):
    p=Path(value.strip())
    if not p.is_absolute(): p=Path(workdir)/p
    if not p.is_file(): raise SystemExit('Missing production Compose override: ' + str(p))
    cmd += ['-f', str(p)]
cmd += ['up','-d','--build','--no-deps','--force-recreate', service]
for word in cmd: sys.stdout.buffer.write(os.fsencode(word)+b'\0')
PY
)
(( ${#COMPOSE[@]} > 0 )) || { echo 'Cannot resolve Compose command: no changes made' >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/home/rohith/gmcs-speedtest-upgrades/github-v5-$STAMP"
mkdir -p "$BACKUP/source"
printf '%s\n' "${FILES[@]}" > "$BACKUP/files.txt"
printf '%s\n' "$SOURCE_REV" > "$BACKUP/git-commit.txt"
for rel in "${FILES[@]}"; do
  if [[ -f "$ROOT/$rel" ]]; then
    mkdir -p "$BACKUP/source/$(dirname "$rel")"
    cp -p "$ROOT/$rel" "$BACKUP/source/$rel"
  fi
done

# SQLite online backup using the actual Docker /data mount; works even if app is crash-looping.
python3 - "$TARGET" "$BACKUP/results-before.sqlite3" <<'PY'
import json, sqlite3, subprocess, sys
from pathlib import Path
container, output = sys.argv[1:]
c=json.loads(subprocess.check_output(['docker','inspect',container]))[0]
mounts=[m for m in c['Mounts'] if m['Destination']=='/data']
if len(mounts)!=1: raise SystemExit('Unable to identify existing result database volume')
db=Path(mounts[0]['Source'])/'results.sqlite3'
if not db.is_file(): raise SystemExit('Live database was not found; refusing to upgrade')
with sqlite3.connect(str(db)) as source, sqlite3.connect(output) as dest:
    source.backup(dest)
with sqlite3.connect(output) as verify:
    status=verify.execute('PRAGMA integrity_check').fetchone()[0]
    if status != 'ok': raise SystemExit('Database backup integrity check failed')
print('SQLite backup verified; original volume untouched.')
PY

# Preserve the exact existing private settings with SHA-256 before/after comparisons.
PRIVATE=(.env private/networks.csv private/agents.csv config/networks.csv config/agents.csv deploy/nginx.gmcs-alt-18443.conf)
( cd "$ROOT"; for rel in "${PRIVATE[@]}"; do
  if [[ -f "$rel" ]]; then sha256sum "$rel"; fi
done ) > "$BACKUP/private.sha256"

printf -v RECREATE '%q ' "${COMPOSE[@]}"
cat > "$BACKUP/rollback.sh" <<ROLLBACK
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT='$ROOT'
BACKUP='$BACKUP'
while IFS= read -r rel; do
  if [[ ! -f "\$BACKUP/source/\$rel" ]]; then rm -f "\$ROOT/\$rel"; fi
done < "\$BACKUP/files.txt"
cp -a "\$BACKUP/source/." "\$ROOT/"
# Normalize readable application code after historical installer permission issue.
while IFS= read -r rel; do
  if [[ -f "\$ROOT/\$rel" ]]; then chmod 644 "\$ROOT/\$rel"; fi
done < "\$BACKUP/files.txt"
cd "\$ROOT"
$RECREATE
ROLLBACK
chmod 700 "$BACKUP/rollback.sh"

# No broad rsync or git reset. Only the audited app files are replaced.
for rel in "${FILES[@]}"; do
  mkdir -p "$ROOT/$(dirname "$rel")"
  install -m 0644 "$SOURCE/$rel" "$ROOT/$rel"
done
chmod 755 "$ROOT/app" "$ROOT/app/static"

cd "$ROOT"
if ! "${COMPOSE[@]}"; then
  echo 'Build failed. Restoring previous application.' >&2
  bash "$BACKUP/rollback.sh" || true
  exit 1
fi

healthy=false
for attempt in {1..60}; do
  if curl -fsS --max-time 3 http://127.0.0.1:18080/healthz >/dev/null 2>&1 &&
     [[ "$(curl -ksS -o /dev/null -w '%{http_code}' --max-time 4 https://127.0.0.1:18443/)" == 200 ]]; then
    healthy=true
    break
  fi
  sleep 1
done
if [[ "$healthy" != true ]]; then
  echo 'Health verification failed; restoring previous application source.' >&2
  docker logs --tail 40 "$TARGET" >&2 || true
  bash "$BACKUP/rollback.sh" || true
  echo "Manual rollback if needed: sudo bash $BACKUP/rollback.sh" >&2
  exit 1
fi

if ! (cd "$ROOT" && sha256sum -c "$BACKUP/private.sha256" >/dev/null); then
  echo 'WARNING: At least one private file changed unexpectedly. Inspect before continuing.' >&2
  exit 1
fi

echo "SUCCESS: GMCS speed-test v5 backend and HTTPS website healthy."
echo "GitHub commit: $SOURCE_REV"
echo "Private IP, Nginx and SMTP files unchanged."
echo "Database backup: $BACKUP/results-before.sqlite3"
echo "Rollback: sudo bash $BACKUP/rollback.sh"
echo 'Website: https://10.250.31.192:18443/'
echo 'Admin:   https://10.250.31.192:18443/admin'
