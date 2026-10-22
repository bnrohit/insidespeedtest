## New: hourly school WAN trends and LibreNMS (v9)

A central scheduler extends the **existing** approved VyOS-to-NOC iperf3 pilot (17 verified schools) to hourly samples. It retains two years of hourly rows in the existing SQLite mount and adds 6h/day/week/month/year/2-year admin charts. A read-only bearer-protected fixed-site endpoint powers a LibreNMS Nagios check with native performance-data graphs. No Windows/macOS/Linux endpoint agent is needed for school-router WAN measurements.

**Run the separate opt-in installer only after reviewing school/site inventory and capped router test settings.** See [GMCS hourly WAN and LibreNMS integration](docs/GMCS-HOURLY-WAN-LIBRENMS.md). Private SSH keys, tokens, DB, SMTP and Nginx overrides remain untracked.

---

# GMCS Inside Speed Test

Secure-by-design, self-hosted **school-to-NOC network speed test** with a browser interface for any authorized school user, school/VLAN inference from observed client IP, and a daily scheduled Linux school-cache agent. **The source is public; the application is intended for a district-only network.** It is not an external Internet speed test.

> **Security:** No application can be guaranteed vulnerability-free. Restrict access to routed GMCS school/management networks, use verified TLS on HTTPS 443, use an approved authenticated SMTP relay, monitor logs, update dependencies and run the included automated tests and dependency scanners before production. Never commit district VLAN/subnet inventories, agents' API secrets, mail credentials or real client IPs to this public repository. No real GMCS subnet data is shipped.

## Who can use it?

- **Any student/staff on an approved GMCS school network** visits `https://<your-internal-speedtest-domain>` and presses **Start Speed Test**. No account, key or Linux agent is needed for the browser. The website records a result for every completed test (client IP, mapped school and VLAN, download/upload, HTTP latency/jitter, timestamp). Neither user name nor message history is collected.
- **School Linux caching servers** can run `agent/school_agent.py` on a staggered systemd timer every morning, with a unique per-server API key pinned to the server's expected source subnet. These results appear alongside browser tests as *Scheduled Linux agent*.
- **Email deduplication (default rolling 24 hours per school + VLAN):** the first successful completed browser **or** agent test queues one email to fixed admin recipients. The next 99 (or 999) tests for the same school/VLAN are recorded but marked `suppressed` for email. Different schools with the same VLAN ID each receive their own email. A failed SMTP attempt has a minimum 15-minute retry holdoff before another test may trigger a retry. School/VLAN *Unknown* is shown honestly and never guessed. Admins can view all results and email statuses at `/admin`.
- **Concurrency:** default max 20 active tests district-wide and 4 per school/VLAN group. Browser tests automatically retry a busy server for up to ~2.5 minutes; unauthorized users cannot bypass the approved client CIDR allowlist. Per-source-IP cooldown and data-transfer caps protect bandwidth. Rate limits can affect users behind the same source NAT address.

## VM setup (Ubuntu guest on XCP-ng)

Deploy on a **dedicated Ubuntu VM**, not on XCP-ng dom0. Suggested starting point: 2-4 vCPU, 4 GiB RAM, 30 GiB disk and a NIC/uplink sized for the anticipated aggregate school test traffic. Install Docker Engine and Docker Compose plugin, a reverse proxy (example Nginx in `deploy/nginx.conf.example`) and a valid internal-CA or publicly trusted TLS certificate for your internal DNS name. Permit school routing/ACLs to **TCP 443**, limit SSH/admin to the management network. Do **not** expose the test service to the public Internet.

```bash
git clone https://github.com/bnrohit/insidespeedtest.git
cd insidespeedtest
mkdir -p private
cp .env.example .env
cp config/networks.csv private/networks.csv
cp config/agents.csv private/agents.csv
chmod 600 .env private/*.csv
python3 -c 'import secrets; print(secrets.token_urlsafe(48))' # paste as ADMIN_PASSWORD in .env
nano .env
nano private/networks.csv
nano private/agents.csv
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
```

The app binds **127.0.0.1:8080** by default. Configure Nginx to forward HTTPS 443 to loopback 8080. The Nginx sample overwrites source-IP headers and is an *example*, not an automatically installed, production-ready certificate/firewall policy. The Docker container uses an unprivileged UID, read-only root filesystem, Linux host networking to preserve the observed source IP, and a persistent SQLite volume. `private/`, `.env` and `data/` are gitignored. The container requires `private/networks.csv` and `private/agents.csv` files.

### Configure accurate school / VLAN lookup

The `private/networks.csv` file must contain **real, administrator-verified school routing/DHCP subnet records**, for example with fictional values:

```csv
scope,school,vlan,cidr,label
school,EXAMPLE-HS,,10.44.0.0/20,Site network example only
vlan,EXAMPLE-HS,48,10.44.1.0/24,Staff example only
vlan,EXAMPLE-HS,56,10.44.2.0/24,Student example only
```

Don't use these examples as actual GMCS mappings. VLAN IDs are *not* included in normal HTTP packets. The application can identify VLAN only via a verified uniquely assigned source subnet and will show **Unknown** if no VLAN match is possible. If NOC proxies or NAT the traffic, the server sees the proxy/NAT IP and school/VLAN lookup may be wrong; fix routing or add a trusted per-school source observation path, rather than blindly trusting browser-submitted school names.

`ALLOWED_CLIENT_CIDRS` in `.env` should contain **only approved GMCS routed campus networks and your required admin/agent networks**; do not blindly leave the permissive private-network demonstration defaults. `TRUSTED_PROXY_CIDRS` should include loopback only when the reverse proxy actually overwrites both `X-Real-IP` and `X-Forwarded-Proto`. Health-check `/healthz` is exempt from CIDR checks but is reachable only on the loopback listener if deployed as instructed. The initial private inventory is copied into the persistent data volume on the first startup; after that, edit it in the admin GUI. A GUI save takes effect immediately, without rebuilding or restarting Docker.

### Set up SMTP / suppress duplicate emails

In `.env`, configure:

```dotenv
EMAIL_BROWSER_RESULTS=true
EMAIL_AGENT_RESULTS=true
EMAIL_DEDUPE_SECONDS=86400
MAX_ACTIVE_TESTS=20
MAX_ACTIVE_PER_VLAN=4
SMTP_HOST=<approved-district-SMTP-relay>
SMTP_PORT=587
SMTP_TLS_MODE=starttls
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=<approved-sender-address>
SMTP_TO=<one-or-more-admin-addresses-comma-separated>
```

With SMTP configured, the **first completed test** per school/VLAN in a rolling 24 hours triggers the admin email with school, VLAN, observed source IP, client type (browser or agent), latency/jitter and download/upload. Other test results are still available at `/admin` and downloadable as CSV, marked `suppressed`. If SMTP is absent, email status is `disabled` and no one is emailed. If SMTP is down, the first test status changes to `failed`, and the next attempt can be retried only after a 15-minute holdoff; watch the admin dashboard. This is not a daily aggregate digest; the email contains the first completed test's measurements. Scheduled agent/email delivery depends on actual connectivity to this server and SMTP relay.

### Install morning checks on each Linux school cache server

Each Linux cache server needs **a unique** random token and `agent_id`, configured both in `private/agents.csv` on the central server and in `/etc/gmcs-speedtest/token` on that school cache. Use a SHA-256 hash in the central CSV, **never a plaintext token** in Git:

```bash
# Locally generate one distinct token PER cache server:
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
# Compute its hash (replace <TOKEN> with the actual token only in a private local shell):
python3 -c 'import getpass,hashlib; print(hashlib.sha256(getpass.getpass("Agent token: ").encode()).hexdigest())'
```

Server CSV example (fictional IP only):

```csv
agent_id,token_sha256,allowed_cidr
EXAMPLE-HS-CACHE01,<64-hex-SHA256-of-the-token>,10.44.1.150/32
```

After setting the CSV, restart the central app: `docker compose up -d --force-recreate`. From the school cache server, copy/clone this repository and install:

```bash
git clone https://github.com/bnrohit/insidespeedtest.git
cd insidespeedtest
sudo sh agent/install.sh
# Store token securely (don't paste into a shared terminal recording):
sudo install -m 0640 -o root -g gmcs-speedtest /dev/null /etc/gmcs-speedtest/token
sudo nano /etc/gmcs-speedtest/token
sudo nano /etc/gmcs-speedtest/agent.env
sudo systemctl enable --now gmcs-speedtest.timer
sudo systemctl start gmcs-speedtest.service    # one initial controlled test
sudo journalctl -u gmcs-speedtest.service -n 40 --no-pager
sudo systemctl list-timers gmcs-speedtest.timer
```

`agent.env` needs `SPEEDTEST_URL=https://<real-internal-domain>` and `SPEEDTEST_AGENT_ID=<agent-id>`, with optional `SPEEDTEST_CA_FILE=...` for the district CA. The timer runs every morning at **06:15 + a stable randomized delay of up to 90 minutes**, staggering districts' WAN tests. Each successful result is submitted to the same server-side email deduplication path; it never emails directly from the school cache server. If another test already emailed for the same VLAN in the prior 24 hours, the morning result is saved but no duplicate email is sent.

## Admin dashboard, limitations and verification

Use `/admin` over HTTPS, preferably restrict to network admin management IPs at the proxy/firewall. An admin username/password is configured in `.env`; the website never exposes the password or keys. Protect the SQLite data volume, back it up, and apply security patches.

- Admin dashboard has every result, VLAN and school, observed IP, test source, email statuses `sent`, `queued`, `suppressed`, `failed` or `disabled`, school summary and CSV export.
- An authenticated school agent uses a per-server token, verified over TLS, and bound to its observed network IP range. Browsers need no key and cannot impersonate an agent without a valid token.
- Tests measure **between browser/cache and the VM**, not external Internet speed, and clients can falsify their own speed figures. This is an operational diagnostic tool, not a cryptographic measurement.
- A one-shot SMTP background task may be interrupted if the application process is stopped at just the wrong moment; review `queued`/`failed` statuses and SMTP logs. Delivery is not guaranteed until verified at the admin mailbox.
- Email suppression is *per school+VLAN*, across both agent and browser runs, not per student/device and not district-wide. Unknown school groups use observed source IP to avoid combining unrelated unmapped sites. Check mappings before relying on VLAN attribution.

Test locally (no real SMTP or district networks needed):

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
ADMIN_PASSWORD=TEST_ONLY_A_LONG_RANDOM_ADMIN_PASSWORD pytest -q
python -m compileall -q app agent
```

The included tests exercise IP spoofing rejection, internal CIDR allowlist, download/upload token budget, SMTP notification deduplication under 100 simultaneous results, failed-email backoff and session concurrency limits. CI is configured under `.github/workflows/` to run tests and dependency/static security checks. Before district production, validate a real switch/VLAN gateway, NAT behavior, group notification behavior, admin access restrictions, certificates, SMTP email arrival and actual school-to-VM throughput.


## GUI management (v2)

Once the app is deployed behind district HTTPS and the admin password has been configured, open **`https://<internal-domain>/admin`**. The Configuration center now provides:

1. **SMTP server** — configure hostname/IP, port, TLS mode, sender, fixed admin recipients, optional SMTP login/password, email source toggles, and per-school/VLAN notification cooldown. Select **Save SMTP settings**; no message is sent on saving. Then select **Send one test email** (limited to once per five minutes) and check the destination mailbox and relay logs. The test sends only to already-configured admins.
2. **School/VLAN mappings** — paste or edit the `scope,school,vlan,cidr,label` CSV, then select **Validate & save inventory**. Invalid overlapping VLAN identities and public ranges are rejected; valid changes are immediately used by subsequent tests. Use **Export private CSV** for a backup. The browser never invents VLAN IDs.
3. **Scheduled school servers** — register `SCHOOL-CACHE01` with the specific client-source address such as `10.x.y.z/32`. The application generates a random key and displays it **once**, then stores only a SHA-256 verifier. Install it on that server with `agent/install.sh`; revoke agents from the admin table. This is *optional*: all approved users may still click **Start Speed Test** without accounts.

**Durability & security:** The running container writes admin-edited SMTP settings, mappings, and server credentials into `/data/managed/` (the existing persistent Docker volume). Files have mode 0600 and live only inside the private VM, not inside Git or build images. SMTP passwords in `/data/managed/smtp.json` are **not encrypted at rest**; protect the VM and volume and consider an external secret manager for high-assurance environments. The initial `private/networks.csv` and `private/agents.csv` files are imported **once** at first startup. Editing them later has no effect until imported through the GUI. Updates to GitHub do not change your deployed configuration. The server uses one worker to keep in-process mappings synchronized with the GUI.

**GMCS-specific deployment:** Set the district's approved relay and routing in the admin GUI; the public repository deliberately ships with **no actual network inventory, SMTP relay address, senders, recipient addresses, or credentials**. Do not push the private deployment bundle or copy `.env`, `private/`, `/data/managed`, exported inventory, or agent credentials to GitHub. You must supply authoritative routing/DHCP/NetBox inventory to cover all district sites: example/pattern-based subnet guesses are not proof of live assignments. TLS settings and mail relay permissions must be verified on the VM. Admin access should be blocked from non-management networks at the reverse proxy/firewall and, ideally, protected by district SSO/MFA.


### Admin IP verification and one-row editing (v3)

The `/admin` dashboard includes an **Identify school/VLAN** lookup. Enter the real
client IP reported by DHCP/NetBox to check the currently *active* mapping. An
**Add school or VLAN subnet** form appends an appropriately escaped row to the
editable CSV; nothing changes until **Validate & save inventory** is selected.
School-wide prefixes are fallback identification only; they never establish
VLAN. Use the CIDR of each VLAN's actual SVI/DHCP allocation, not a pattern
based on the VLAN number. The app rejects conflicting overlapping VLAN IDs.

**Extra admin restriction:** `ADMIN_CLIENT_CIDRS` defaults to loopback only; before serving district administrators, configure the verified private NOC administrator subnet(s) in your local `.env` and retain equivalent Nginx/firewall restrictions. This restriction applies even when someone knows the administrator password.

**Public repository vs district configuration:** This repo contains application
source and generic sample CSVs, not verified GMCS internal subnet inventory or
SMTP sender/recipients. Import the provided private inventory file to the
server *only after* comparing candidate entries with NetBox and real school
routing. SMTP relay address alone cannot deliver mail without a permitted
sender, recipients and relay connectivity. `git push` cannot execute the app
or send mail; the live server is separate.

## Nginx security patch / Bonjour (mDNS) hardening (2026-10-21)

**Two different vulnerabilities:** Nginx HTTP reverse-proxy vulnerabilities are resolved by installing security-patched Nginx; Bonjour/mDNS discovery is a separate **host or network service**, commonly Avahi on Linux UDP/5353. The FastAPI speed-test service uses HTTPS/TCP and has no mDNS dependency. A source-code change cannot prove that a running VM or an upstream mDNS reflector is not responding. **Re-scan from a school or the Nessus scanning VLAN after deployment.**

### Recommended: verified Nginx stable 1.30.6 HTTPS container

The optional `compose.nginx.yaml` provides the official `nginx:1.30.6-alpine` image (newer than 1.28.2/1.29.5), a hardened TLS proxy, and a read-only container. Nginx 1.30.6 is the patched stable release as of October 21, 2026. Future vulnerabilities will still require updates. This does **not** replace, patch or restart the host's existing Nginx unless you deliberately switch over; **do not start two services on port 443**.

```bash
# On the Ubuntu speed-test VM after completing .env/private school configuration:
cd /opt/gmcs-speedtest/insidespeedtest  # adjust to your deployed project directory
sudo ss -ltnp '( sport = :443 )'        # must be empty before container proxy starts
sudo mkdir -p private/tls
# Install your GMCS-approved TLS certificate and key as:
# private/tls/fullchain.pem and private/tls/privkey.pem (do not commit them).
sudo chmod 700 private/tls
sudo chmod 600 private/tls/privkey.pem

docker compose -f compose.yaml -f compose.nginx.yaml config -q
docker compose -f compose.yaml -f compose.nginx.yaml pull nginx
docker compose -f compose.yaml -f compose.nginx.yaml up -d --build
docker compose -f compose.yaml -f compose.nginx.yaml exec nginx nginx -v
# Expected: nginx version: nginx/1.30.6
curl --fail --cacert /path/to/gmcs-root-ca.pem \
     https://your-internal-speedtest-domain/healthz
```

Nginx terminates **HTTPS 443**, forwards to application **127.0.0.1:8080** and overwrites untrusted source-IP headers. The certificate name must match the browser's DNS domain. Prefer a meaningful real server name instead of the `_` fallback in `deploy/nginx.container.conf`. Do not expose the VM publicly; use district ACLs and management-only administrator access. The container proxy is optional: if **host Nginx already handles TLS**, upgrade it via your OS's official Nginx stable repository and validate it with `sudo bash deploy/nginx-version-audit.sh`. On Ubuntu, follow [Nginx's official signed repository instructions](https://docs.nginx.com/nginx/admin-guide/installing-nginx/installing-nginx-open-source/#ubuntu-packages); confirm key fingerprints, back up existing configs, then `nginx -t` and perform a controlled reload. **Do not start the container proxy with an active host Nginx on 443.** Linux distribution-maintained packages may backport security fixes without displaying the upstream version; evaluate actual vendor advisories in that case.

### Detect and disable unnecessary VM multicast discovery

```bash
# Read-only checks before touching production services:
sudo bash deploy/mdns-audit.sh --check
sudo ss -lunp | grep -E '(:5353|\]:5353)' || echo 'No local UDP/5353 listener'

# Only after verifying that the VM does NOT need local printer/service discovery:
sudo bash deploy/mdns-audit.sh --apply

# Check for a patched host Nginx if you use host Nginx, not the Docker proxy:
sudo bash deploy/nginx-version-audit.sh
```

The `--apply` command stops/masks the **Avahi daemon and socket** when present and blocks inbound UDP/5353 using UFW **only if UFW is already active**. It does **not** automatically enable a firewall, restart DNS, alter school switches or install/upgrade Nginx. If `systemd-resolved` or another responder still advertises mDNS, disable `MulticastDNS` in an approved maintenance window and verify again. At the host / routed network firewall, deny unwanted IPv4 and IPv6 UDP/5353 inbound to this VM, including any inter-VLAN mDNS reflector exceptions. Never disable Avahi on **every school server** blindly; this script is intended for the dedicated speed-test VM.

Finally perform an **authorized external vantage-point scan** from a separate VLAN: check HTTPS/443, HTTP/8080 blocked externally, UDP/5353 absent, and any Nessus Bonjour findings. For UDP a generic port scanner can report `open|filtered` inconclusively; absence of a listening process and lack of mDNS responses from the scanner segment are stronger evidence. Nessus can report other vulnerabilities despite these controls, so review and patch findings continuously.


## District branding (admin only) and external Internet diagnostics

Branding is controlled **only in `/admin`** (authenticated admin cookie, CSRF and network allowlist):
organization name (default **GMCS**), tab title, subtitle, heading, description and
shared PNG logo. A signed-in admin can upload a 2 MB-or-smaller PNG/JPEG/WebP,
which the browser converts to a bounded PNG, or restore the bundled district logo.
The settings and logo are stored in the **existing SQLite data volume** so upgrades
and container recreations preserve them. Regular school visitors can only read
`/api/branding` and `/api/branding/logo`. The previous browser-only personal
logo picker was intentionally **removed**.

Three paths are deliberately kept distinct:
1. Existing internal browser throughput test: school device → GMCS NOC VM (`10.250.31.192`).
2. External speed test link: school device → third-party Internet test in a new tab.
3. Admin-only NOC egress check: NOC VM → Cloudflare edge over verified HTTPS
   with 4 MiB down, 1 MiB up, DNS/TLS time and a two-minute district-wide limit.

The bounded egress probe is diagnostic only; it cannot establish the throughput
of a particular school's ISP uplink or prove traversal of either Nexus core.
External service reachability and egress filtering can affect results. See
`docs/GMCS-V5-DEPLOY.md` for deployment and security details.

## Client troubleshooting (v7)

Each completed browser speed test now attaches small browser/network context and shows a rule-based evidence report to authorized admins in the **Client Troubleshooting Center**. Optional Windows and macOS *read-only* diagnostic scripts gather hostname, IP/DNS/gateway, route, fixed-target ping, traceroute and nslookup, plus opt-in MAC/ARP/netstat/DNS cache observations. The user must review and explicitly upload the local JSON; the website **cannot** remotely run those OS commands. See [client troubleshooting, consent, retention and upgrade instructions](docs/GMCS-CLIENT-TROUBLESHOOTING.md). Private GMCS IP ranges, Nginx settings and SMTP credentials remain server-side.

### Windows diagnostics: client-approved direct upload

After a browser speed test, clients may explicitly create a 10-minute, one-use upload code and execute the GMCS-approved signed Windows diagnostics script. The report is saved locally and, after confirming submission, sent directly to the matching admin troubleshooting result. A normal download never auto-runs, and unsigned downloaded scripts are **not** guaranteed compatible with Smart App Control. Trusted signing and a Windows-trusted HTTPS certificate are required for secure deployment. See [Client Troubleshooting / Smart App Control](docs/GMCS-CLIENT-TROUBLESHOOTING.md).
