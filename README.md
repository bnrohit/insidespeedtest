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

`ALLOWED_CLIENT_CIDRS` in `.env` should contain **only approved GMCS routed campus networks and your required admin/agent networks**; do not blindly leave the permissive private-network demonstration defaults. `TRUSTED_PROXY_CIDRS` should include loopback only when the reverse proxy actually overwrites both `X-Real-IP` and `X-Forwarded-Proto`. Health-check `/healthz` is exempt from CIDR checks but is reachable only on the loopback listener if deployed as instructed. VLAN mapping is reloaded on container restart.

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
