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
# Upgrade only the audited app files; auto-backup the live database and old source.
sudo bash /home/rohith/insidespeedtest-upstream/deploy/gmcs-safe-upgrade.sh
```

The upgrade script:
1. Resolves the **exact existing** Compose files from the running `gmcs-inside-speed-test` container labels.
2. Creates a source backup and a SQLite online backup (works even during a container restart loop).
3. Replaces only the audited versioned `app/` source/static files using permission `0644`; fixes the root-owned `0600` permission issue from the first v5 installer.
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

## Admin-only district branding and Internet-path comparison (v6)

Visitors cannot personalize the production website. Only signed-in, approved-network admins
may upload or restore the logo, change the organization name (default `GMCS`), change
browser title, organization subtitle, main heading, and description. Changes are
stored in the **existing results SQLite volume** in the `site_branding` table and
immediately become visible to all clients on refresh. The supplied GMCS PNG is the
fallback. The admin browser converts PNG/JPEG/WebP images to a small safe PNG, and
the server enforces a 450 KB PNG/1200x600 ceiling; arbitrary SVG or HTML is not accepted.
No additional externally writable asset directory exists. Security relies on existing
admin cookie, same-origin and CSRF enforcement; public clients have read-only access
through `/api/branding` and `/api/branding/logo`.

New **separate measurement points**:
- **Client → GMCS NOC VM:** existing internal throughput/latency measurement from
  the school client to `10.250.31.192` (retained unchanged).
- **Client → Internet (outside GMCS):** the client-facing **External Internet test**
  link opens `https://speed.cloudflare.com/` in a new browser tab. This tests the
  client's own direct egress path through Cloudflare's service; the provider's
  results are not silently imported, stored or claimed as GMCS server measurements.
- **GMCS NOC VM → Internet:** logged-in admins can run an on-demand bounded HTTPS
  test against a fixed trusted public host (`speed.cloudflare.com`) with **4 MiB
  download and 1 MiB upload**, DNS resolution and TLS connection timing. DNS must
  resolve to globally routable addresses and connections pin to those IPs while
  validating the hostname certificate; redirects and arbitrary user-supplied
  destinations are never followed. Runs are limited to **one district-wide every
  120 seconds** and stored in `external_checks`, which is included in DB backups.
  These small sample Mbps readings are **NOT accurate gigabit/line-rate benchmarks**
  and do not prove the traffic path through a specific Nexus switch or firewall.
  A blocked or rate-limited external service is displayed as a failed probe, not zero
  Internet throughput. Test output depends on firewall/proxy egress policies.

**Production upgrade:** from `/home/rohith` use the existing
`insidespeedtest-upstream` separate checkout and `git pull --ff-only origin main`,
then `sudo bash insidespeedtest-upstream/deploy/gmcs-safe-upgrade.sh`.
The safe upgrade installs only the explicitly audited `app/` files; it does not
copy `.env`, managed inventory, SMTP, Compose, Nginx, or private IP mappings.
It backs up existing SQLite and source before a single-backend rebuild. Verify
`/healthz`, website `HTTP 200`, and the four current Nginx admin CIDRs.

**Rollback** is printed by the production upgrade script and restores the
previous source while leaving the persistent database volume intact. The new
SQLite tables are backward-compatible with the prior application version.

**Live tests:** sign in at `/admin`, change organization name, upload and reset a
logo, sign out, verify clients cannot edit; run a VM → Cloudflare egress probe from
an approved admin IP. A browser's direct-Internet results and the VM egress
results will differ when network paths and ISPs differ.


## Admin dashboard triage and inventory audit

The admin results endpoint filters the full stored history before applying the display limit. Focus choices: unmapped school/VLAN, jitter >=30 ms, upload <10 Mbps, and upload-to-download ratio under 25% when download >=20 Mbps. Sort options use known safe expressions: newest, highest jitter, lowest upload, and worst ratio.

The school/VLAN lookup displays verified matching school and VLAN CIDRs, or explains what is absent. The Check mapping shortcut on unmapped results uses that authenticated endpoint. Diagnose #ID already fills the ID input and opens the report directly. Inventory changes classify new tests only; existing result history is not silently rewritten. A proposed subnet must be verified against routing and DHCP records. 10.64.241.0/21 is not aligned (the containing /21 is 10.64.240.0/21), but neither network nor school identity should be assumed without verification.

NOC egress and SMTP status indicators distinguish not configured, last checked successfully, failure, and configured but unverified. SMTP relay acceptance does not prove mailbox delivery. No SMTP password can be normal for an authorized relay. Asymmetric transfer speeds are investigation prompts, not proof of Wi-Fi, QoS, ISP, routing, or transceiver faults.

### Deployment notes

The controlled upgrade script deploy/gmcs-safe-upgrade.sh now includes app/identity.py along with app/main.py, admin JS/HTML and CSS. Use the existing separate upstream checkout, inspect the live Compose path, and run the audited upgrade only on the previously documented production host. Review and retain private inventories, tokens, database, nginx configurations, and rollback records.

Disk assessment: recent server output shows approximately 27 GB free, with zero Docker build cache and a healthy GMCS speed-test container. The old speed-test installer archives and extracted copies occupy less than 1 MB altogether; deleting them is unnecessary for disk capacity. Investigate why ~/insidespeedtest is shown as 4 KB despite being the Docker Compose working directory before moving or deleting that path.
