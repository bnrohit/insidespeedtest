# GMCS Inside Speed Test v5 — login/logout and client-requested admin email

Features:
- Administrators authenticate with existing `ADMIN_USERNAME`/`ADMIN_PASSWORD` from **private** `.env`. Each browser receives its own secure, HttpOnly, eight-hour cookie; its Logout button revokes only that cookie. All state-changing admin API requests require same-origin controls and CSRF token.
- Optional client-side **Email my results to GMCS admins** action is available after a completed browser test, to the configured SMTP recipients only. Duplicate and high-volume requests are throttled. Automatic email continues working.
- The SQLite schema migrates in place without dropping existing test records.

## GMCS Debian safe upgrade

**Do not run `git reset --hard` or `git pull` directly in `/home/rohith/insidespeedtest` if it contains local site settings.** Preserve existing `.env`, `private/`, `data/`, `config/`, Nginx ACL files, and all Compose override files.

From the Debian host `rohith@10.250.31.192`:

```sh
sudo apt-get install -y git
cd /home/rohith
# Upstream source checkout stays separate from the running production directory.
if [ -d insidespeedtest-upstream/.git ]; then
  git -C insidespeedtest-upstream pull --ff-only origin main
else
  git clone --depth 1 -b main https://github.com/bnrohit/insidespeedtest.git insidespeedtest-upstream
fi
# Check source revision and review if desired.
git -C insidespeedtest-upstream log -1 --oneline
# Upgrade only 12 app files; auto-backup the live database and old source.
sudo bash /home/rohith/insidespeedtest-upstream/deploy/gmcs-safe-upgrade.sh
```

The upgrade script:
1. Resolves the **exact existing** Compose files from the running `gmcs-inside-speed-test` container labels.
2. Creates a source backup and a SQLite online backup (works even during a container restart loop).
3. Replaces only 12 versioned `app/` source/static files using permission `0644`; fixes the root-owned `0600` permission issue from the first v5 installer.
4. Rebuilds only `gmcs-inside-speed-test` and checks both localhost FastAPI `/healthz` and HTTPS Nginx on port `18443`.
5. Verifies byte-for-byte preservation of `.env`, private network/agent mapping files, and `deploy/nginx.gmcs-alt-18443.conf`.
6. Prints a rollback command. If build or health validation fails, attempts to restore previous source.

Existing Nginx admin allowlists, such as `10.250.0.0/16`, `10.64.0.0/16`, `10.35.0.0/16`, and `10.200.0.0/16`, are **not** replaced by this upgrade. The speed-test website continues to use existing client allowlists. Any site-specific local mapping source files, including managed `/data/managed` inventory, remain private.

Verify:

```sh
curl -sS -i http://127.0.0.1:18080/healthz
curl -ksS -o /dev/null -w 'HTTPS %{http_code}\n' https://127.0.0.1:18443/
sudo docker exec gmcs-speedtest-nginx-1 nginx -T 2>&1 | grep -E 'allow |deny all'
```

Use a private browser window for first sign-in at `https://10.250.31.192:18443/admin` and test Logout. Test client email through a **newly completed test** and confirm SMTP delivery through the dashboard; only the configured recipient list receives it.

Security: keep private credentials, actual school mapping files, and `.env` **out of public GitHub**. Rotate any admin password previously pasted into logs or chat. Limit admin-network access to authorized staff networks where possible. Keep `ALLOW_LEGACY_BASIC_API=false` for reliable logout.

Local unit/integration tests: `python -m pytest -q` with dependencies from `requirements-dev.txt`. Passing tests do not substitute for a live SMTP relay and client-browser test on the Debian host.

## Client logo upload (GMCS branding update)

The client-facing homepage now displays the supplied Gallup-McKinley County Schools
logo by default. Every client may choose **Upload logo**, select a PNG/JPEG/WebP
image up to 2 MB, and restore the GMCS logo using **Restore GMCS logo**. Images are
converted in the browser into a small PNG; only that browser stores the image in
`localStorage`. No image is uploaded to the server, other browsers do not see it,
and uploads never alter official GMCS or other clients' branding.

To upgrade a running customized GMCS installation, use the same separate checkout
plus `sudo bash .../deploy/gmcs-safe-upgrade.sh` described above. This revision
adds only `app/static/branding.js` and `app/static/gmcs-logo.png` to the audited
file allowlist. Existing private IP mappings, Nginx rules, SMTP, `.env`, and Compose
overrides are neither imported from GitHub nor overwritten.
