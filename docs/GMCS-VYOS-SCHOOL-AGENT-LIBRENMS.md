# Run the GMCS HTTPS speed test **on the school's VyOS router or Linux machine**; graph it under that VyOS router in LibreNMS

This is **not** the NOC SSH/iperf3 collector. The router/host initiates an outbound test to the GMCS server itself, then LibreNMS only reads the saved measurements. Adding a router in LibreNMS by SNMP alone does **not** automatically graph custom speed tests: add **one Nagios service** on that router device.

## Architecture

```
CDE VyOS / Linux host -- at most hourly HTTPS download/upload --> 10.250.31.192:18443
                         (using unique GMCS agent ID)       |
                                              GMCS /api/results, SQLite
                                                             |
LibreNMS existing CDE VyOS device --> Nagios gmcs_school_agent.py
    (read-only HTTPS query to GMCS; NEVER runs speed tests during polls)
    --> service graphs: download/upload Mbps, latency/jitter ms, loss %
```

The HTTPS destination is the GMCS VM. This is a router/host-to-NOC **internal path test**, not the ISP's public Internet speed. Results reflect the actual source interface/route selected by VyOS/Linux. Confirm observed source IP in GMCS admin; source NAT/PBR may change it. Browser/Windows user diagnostics and the optional central VyOS SSH collector remain separate.

## Step 1: main server and credentials

On the NOC VM, pull and run the existing safe deployment (private Nginx, custom IP mappings, SMTP, secrets and database preserved):

```
cd /home/rohith
git -C insidespeedtest-upstream pull --ff-only origin main
sudo bash /home/rohith/insidespeedtest-upstream/deploy/gmcs-safe-upgrade.sh
curl -fsS http://127.0.0.1:18080/healthz
```

From GMCS Admin > **Scheduled Linux school servers**, create an identity such as `CDE-VYOS01` or `CDE-LINUX01`. Use the **actual source IPv4 /32** shown to the GMCS server (not an invented campus subnet); retrieve its one-time secret. One unique agent per source router/host, bound to the observed source address. If both a router and Linux machine are enabled at the same school, schedule at different minutes and check server-wide test concurrency/cooldown.

## Step 2A: VyOS router agent (persistent across router reboots/image updates)

Stage the full `agent/` directory from the GitHub checkout to the router through your approved SSH/SCP administration process. From a Linux management workstation where the repo is cloned, e.g.:

```
scp -r agent vyos-user@VERIFIED_ROUTER_MGMT_IP:/tmp/gmcs-agent
```

SSH to the **verified, authorized** VyOS management IP, then:

```
sudo sh /tmp/gmcs-agent/vyos/install-vyos.sh
sudo vi /config/auth/gmcs-speedtest/agent.env
```

Set `SPEEDTEST_URL` to the DNS name/IP and port that the router reaches, e.g. `https://10.250.31.192:18443` **only if the HTTPS certificate SAN contains that IP**; otherwise use your actual, district-trusted DNS name. Set `SPEEDTEST_AGENT_ID='CDE-VYOS01'`. If the CA is not in the VyOS trust store, put the **trusted** CA cert at `/config/auth/gmcs-speedtest/ca.pem` and set `SPEEDTEST_CA_FILE` accordingly. Use HTTPS only for authenticated uploads; do **not** set `verify=False`, `-k`, or transmit agent keys over plain HTTP.

Securely provision the one-time agent token to `/config/auth/gmcs-speedtest/token` (root-owned mode `0600`, no shell history/log paste). Install overwrites neither configured token nor private .env. Verify one manual test without publishing credentials:

```
sudo /config/scripts/gmcs-speedtest/runner.sh
```

In **VyOS configuration mode**, create the persistent hourly task, with a **different scheduled minute at each school** (the example `17` is a placeholder to stagger, not mandatory):

```
configure
set system task-scheduler task gmcs-speedtest crontab-spec '17 * * * *'
set system task-scheduler task gmcs-speedtest executable path '/config/scripts/gmcs-speedtest/runner.sh'
commit
save
exit
```

The task runs **on the router**, once per hour, and does not SSH back into itself from NOC. VyOS task-scheduler runs as root, so only trusted operators should install/edit the root-owned script or credentials. The runner limits the load (24 MiB max down, 8 MiB max up, low CPU priority, non-overlapping executions). Do not enable on busy routers until one pilot confirms CPU and WAN headroom. On systems missing the required `/usr/bin/python3`, `/usr/bin/flock` or `/usr/bin/nice`, this installer stops rather than modifying the platform. VyOS docs: https://docs.vyos.io/en/1.4/configuration/system/task-scheduler.html

To undo **only** the scheduled task (preserve the files/record history):

```
configure
delete system task-scheduler task gmcs-speedtest
commit
save
exit
```

## Step 2B: Linux school server alternative

Run `sudo sh agent/install.sh` from the GitHub checkout on the school Linux server, configure `/etc/gmcs-speedtest/agent.env` and per-host token; run `sudo systemctl start gmcs-speedtest.service` once, then `sudo systemctl enable --now gmcs-speedtest.timer`. These are **separate agents** from router-based deployments, but submit to exactly the same GMCS HTTPS API and can be graphed on the associated VyOS device when the service's agent ID is correctly assigned.

## Step 3: LibreNMS **router device** graphs

On the LibreNMS poller (not the VyOS router), install the plugin and grant it a **monitoring-only** token (provisioned once from the NOC VM with `integrations/librenms/create-monitor-token.sh`), trusted HTTPS CA, and access to the NOC VM. The secret stays on LibreNMS, not VyOS:

```
sudo install -m 0755 integrations/librenms/check_gmcs_school_agent.py \
  /usr/lib/nagios/plugins/check_gmcs_school_agent.py
sudo -u librenms /usr/lib/nagios/plugins/check_gmcs_school_agent.py \
  -H CDE_ROUTER_DEVICE_IP --agent-id CDE-VYOS01 \
  --url https://YOUR_TRUSTED_GMCS_DNS_NAME:18443 \
  --token-file /etc/librenms/gmcs-monitoring.token \
  --ca-file /etc/ssl/certs/YOUR_GMCS_CA.pem
```

After at least one successful school-side speed test, this should emit e.g. `OK ... | download_mbps=...;;;0; upload_mbps=...;;;0; ...`. In LibreNMS, open the **existing CDE VyOS router device** -> **Services -> Add Service**:

- Type: `gmcs_school_agent.py` (LibreNMS removes `check_` prefix).
- Description: `CDE-VYOS01 school-router to NOC HTTPS speed`.
- Parameters: `--agent-id CDE-VYOS01 --url https://YOUR_TRUSTED_GMCS_DNS_NAME:18443 --token-file /etc/librenms/gmcs-monitoring.token --ca-file /etc/ssl/certs/YOUR_GMCS_CA.pem`.
- Service host/IP: the selected **CDE router device**. The plugin accepts LibreNMS-supplied `-H CDE_ROUTER_DEVICE_IP`; it does **not** use that IP to run a test or infer the agent ID.

When LibreNMS polls the router's services (usually 5-minute intervals), it fetches the latest cached result and writes its performance-data RRDs. The `*_mbps` field names encode Mbps; their Nagios performance values deliberately have no `Mbps` unit suffix because LibreNMS recognizes only standardized Nagios suffixes. Browse the graphs on the **VyOS device's service page**, and select 6h, day, week, month, year, etc. Full stored NOC history is also shown in GMCS admin's School Agents panel (6h/day/week/month/year/2years). For two years of **LibreNMS** graphs, verify the *actual RRD archive retention/aggregation* (`rrdtool info`); the default may downsample older periods. The NOC's result DB and routine backups are the source of full historical records.

**Caution:** A separate agent with a distinct ID exists at each school. Simply adding an SNMP router to LibreNMS does not mean it is running an HTTPS test. Only enable the agent explicitly on authorized, verified routers; do not conflate its speed-test results with LibreNMS native interface graphs or with the optional NOC-controlled VyOS iperf3 collector.
