> **VyOS router as the school agent?** Use [VyOS on-router installer and LibreNMS router-device graphs](GMCS-VYOS-SCHOOL-AGENT-LIBRENMS.md) instead of Linux systemd setup.

# GMCS: school-host hourly measurements, independently graphed in LibreNMS

## The **separate** measurement paths

1. **School machine (recommended):** a dedicated Linux VM/cache at *each school* runs `agent/school_agent.py` from its campus LAN, using HTTPS **outbound** to `10.250.31.192:18443`. Its credential is individually created under Admin > Configuration > Scheduled school agents (VyOS / Linux) and bound to its observed source IP. The HTTP application measures throughput itself, so no iperf3 SSH access to VyOS is needed. The school agent schedules one test per hour, from `:05` with up to 25 minutes stable per-host offset, limiting traffic spikes. A specific site's agent must have connectivity to the NOC server; machines that cannot reach it do not get fake zeros.
2. **Existing VyOS router SSH collector (separate/optional):** centrally SSHs to some VyOS routers and runs capped iperf3 to NOC. Its history table (`vyos_hourly`), timers, dashboard and LibreNMS plugin are **different** and remain unchanged. Do **not** call these tests school-host measurements.
3. **LibreNMS (read-only pull):** polls a tiny authenticated endpoint on central GMCS and saves one Nagios service's performance data per registered *school host* in LibreNMS RRD files. It **does not connect to school agents** or trigger the tests. Do not distribute LibreNMS tokens onto school agents.
4. **Browser speed test:** student/staff measurements and troubleshooting upload remain independent and are not used for scheduled agent graphs.

```
School CDE Linux VM -- hourly outbound HTTPS test --> GMCS 10.250.31.192:18443
                                                        | SQLite results (agent_id)
LibreNMS poller -- read-only HTTPS (cached latest) ------+
   | Per-agent Nagios service graphs, e.g. CDE-CACHE01  |
GMCS admin dashboard -- read-only 6h/day/week/…/2yrs ---+

Existing central VyOS hourly SSH/iperf3 collector ------> Separate vyos_hourly table
```

## 1. Server installation (preserves private config)

On the GMCS NOC Debian VM:

```bash
cd /home/rohith
git -C insidespeedtest-upstream pull --ff-only origin main
sudo bash /home/rohith/insidespeedtest-upstream/deploy/gmcs-safe-upgrade.sh
curl -fsS http://127.0.0.1:18080/healthz
```

In Admin > Configuration > Scheduled school agents (VyOS / Linux), create `CDE-CACHE01` with its verified **source IP `/32`** (example: `10.21.1.25/32` is **illustrative**, not an assertion of CDE's real IP). Save the one-time token on the school machine privately; register each site individually. Existing VLAN/IP mappings are not modified.

## 2. School Linux VM installation

On the **school VM**, use the same public repository (do **not** install the central collector there):

```bash
git clone --depth 1 https://github.com/bnrohit/insidespeedtest.git
cd insidespeedtest
sudo sh agent/install.sh
```

Configuration:

```bash
sudoedit /etc/gmcs-speedtest/agent.env
# SPEEDTEST_URL=https://10.250.31.192:18443
# SPEEDTEST_AGENT_ID=CDE-CACHE01
# SPEEDTEST_TOKEN_FILE=/etc/gmcs-speedtest/token
# SPEEDTEST_CA_FILE=/etc/ssl/certs/gmcs-district-ca.pem
```

Place the previously issued one-time secret into `/etc/gmcs-speedtest/token` (with a secure root-managed mechanism; never in shell history, `curl` URLs, tickets or GitHub):

```bash
sudo chown root:gmcs-speedtest /etc/gmcs-speedtest/token
sudo chmod 0640 /etc/gmcs-speedtest/token
```

The HTTPS certificate **must** match the URL and be trusted. On the current self-signed-by-IP deployment, import the *correct* district CA into the VM trust store (or configure the agent `SPEEDTEST_CA_FILE` accordingly); do not use `--insecure` or `verify=False`.

Pilot run and then opt in to hourly service:

```bash
sudo systemctl start gmcs-speedtest.service
sudo journalctl -u gmcs-speedtest.service -n 40 --no-pager
sudo systemctl enable --now gmcs-speedtest.timer
systemctl list-timers gmcs-speedtest.timer
```

The installer **does not** enable the timer by itself. Timer schedules hourly from minute :05, with stable per-host randomized delay up to 25 minutes (not a burst across the whole district); `Persistent=false` prevents a backlog of catch-up tests after power loss. The systemd service uses an unprivileged account, no remote shell, and only outbound HTTPS. If deploying at more sites, enroll one verified source/IP per host; watch NOC aggregate load before expanding.

## 3. LibreNMS poller installation (one service per school agent)

Provision the NOC **monitoring-only** token (if it does not already exist):

```bash
sudo bash /home/rohith/insidespeedtest-upstream/integrations/librenms/create-monitor-token.sh
```

Transfer it through an approved encrypted administrator channel to `/etc/librenms/gmcs-monitoring.token` (owner `librenms`, mode `0600`) on the LibreNMS poller, **not school agents**. Use a district-trusted HTTPS certificate/hostname for the GMCS VM.

On the LibreNMS host:

```bash
sudo install -m 0755 integrations/librenms/check_gmcs_school_agent.py \
  /usr/lib/nagios/plugins/check_gmcs_school_agent.py
sudo -u librenms /usr/lib/nagios/plugins/check_gmcs_school_agent.py \
  --agent-id CDE-CACHE01 --url https://speedtest.gmcs.k12.nm.us:18443 \
  --token-file /etc/librenms/gmcs-monitoring.token \
  --ca-file /etc/ssl/certs/gmcs-internal-ca.pem
```

The example DNS name and CA path must actually resolve/be installed in your GMCS environment; do not invent certs or skip certificate validation. For each school VM, attach Nagios service type **`gmcs_school_agent.py`** with `--agent-id ...` to a corresponding *verified* LibreNMS device. Its performance fields: `download_mbps`, `upload_mbps`, `latency_ms`, `jitter_ms`, `loss_pct`. LibreNMS polls the cached data only and graphs the history with RRD; typical 5-minute polls repeat the most recent hourly sample. If more than 2.5 hours old, output is `UNKNOWN`, not 0 Mbps or proof of router outage.

LibreNMS official docs: https://docs.librenms.org/Extensions/Services/ and https://docs.librenms.org/API/Devices/ . The latter documents its per-service graph API `/api/v0/devices/:hostname/services/:service_id/graphs/:datasource` with `from` and `to` timestamps. You can view **6 hours, day, week, month, year** via LibreNMS service graph controls or API by selecting the corresponding period. Graph data is aggregated and archives may vary. Check actual RRD `rrdtool info` settings to ensure **at least two years** of older consolidated values; do not assume all hourly-resolution samples survive that long. The GMCS SQLite database retains complete stored agent results unless deliberately purged by an administrator.

## 4. Data separation and access boundaries

- `/api/admin/school-agents` and `/api/admin/school-agents/{agent_id}?window=...` require GMCS admin session; graphs cover 6h/day/week/month/year/2years.
- `/api/monitoring/school-agent/{agent_id}` is GET-only, HTTPS-only and requires the separate read-only token; response has no private client IP or hostname.
- The existing `/api/monitoring/router-hourly/{site}` remains separate.
- School agent uses pre-existing `/api/session` -> `/api/download` / `/api/upload` -> `/api/results` (source IP and per-host token bound, volume-budgeted); no LibreNMS token, no SSH to VyOS, no modification to student or staff PCs.
- School agents are independent of the Windows user troubleshooting consent process.

## 5. Troubleshooting

- `NO_SAMPLE`: agent registered but no successful completed test; check the local systemd logs and TLS reachability.
- `STALE`: last completed test is older than 150 minutes; not proof WAN is down.
- `401` agent start: check token and registered host `/32` seen by GMCS reverse proxy, without disclosing token.
- `403`: check the school agent's source IP matches GMCS district allowlist and trusted CA/HTTPS.
- Empty LibreNMS graph: inspect plugin execution user, service poller, TLS validation, token permissions, device/service mapping, and actual RRD archive.
- Avoid scheduling the old VyOS `gmcs-router-hourly.timer` if you want **only** school-agent measurements. Disabling that optional timer leaves school agents and the existing morning report untouched.
