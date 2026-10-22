# GMCS VyOS-native HTTP speed test → LibreNMS Apps/RRD

**No Ookla, no central SSH/iperf speed-test scheduler, and no LibreNMS-triggered speed test.** Each school VyOS router runs the GMCS HTTPS transfer test itself. Its measured result is cached on that same router. LibreNMS retrieves only that result using the router's existing SNMPv3 management credentials, and writes new RRD datasets under **Apps → GMCS VyOS Speedtest**. The GMCS Debian server (`10.250.31.192:18443`) serves test bytes and accepts the normal authenticated result; it **does not initiate or calculate router-side measurements**.

A normal Linux machine can use the existing `agent/school_agent.py` scheduler, but to show *this* native LibreNMS Apps entry, the SNMP extend must be hosted on the VyOS router being monitored. This is deliberately separate from existing browser diagnostics, central VM egress tests, and the older VyOS SSH test collector.

## 1. Enroll one school VyOS router, then install the agent code

In [GMCS Admin](https://10.250.31.192:18443/admin) → **Scheduled Linux school servers**, register a unique ID like `CDE-VYOS01` with the router's **actual source IP `/32` as observed by the GMCS server**. Securely transfer its token to the router; do not paste it into chat, terminal logs or public GitHub.

On a management Linux workstation with this GitHub repository checked out:

```sh
scp -r integrations/vyos-snmp-direct nwadmin@VERIFIED_ROUTER_IP:/tmp/gmcs-vyos-snmp-direct
scp agent/school_agent.py nwadmin@VERIFIED_ROUTER_IP:/tmp/gmcs-school-agent.py
```

On the router:

```sh
sudo sh /tmp/gmcs-vyos-snmp-direct/install.sh
sudo install -m 0755 /tmp/gmcs-school-agent.py /config/scripts/gmcs-speedtest/school_agent.py
sudo vi /config/auth/gmcs-speedtest/direct.json
```

Set `inside.enabled` to `true`, set `inside.url` to `https://10.250.31.192:18443` if the HTTPS certificate is trusted and has that address in its subjectAltName, and replace the example agent ID with the enrolled router ID. Keep token and CA cert under `/config/auth/gmcs-speedtest/`. Token permissions must be `0600` root. No insecure HTTP fallback is supported when credentials are present; issue a correct GMCS district-trusted certificate instead of disabling TLS validation.

Run the test *on VyOS* once:

```sh
sudo python3 /config/scripts/gmcs-vyos-speedtest/collect.py --validate-only
sudo /config/scripts/gmcs-vyos-speedtest/runner.sh
sudo /config/user-data/gmcs-vyos-speedtest/extend.py
```

The first execution sends a bounded **24 MiB download / 8 MiB upload** to the GMCS HTTPS service, measures speeds/ping/jitter/loss *from the router*, and saves only safe numeric metrics. The SNMP extension **only reads cache**; it never runs a test. If the test fails or its cache becomes older than 150 minutes, the extend produces NULL measurements, not invented zero speeds.

When a pilot router returns valid numbers, configure the SNMP extension and independent hourly VyOS scheduler (choose staggered minutes for each school, **do not enable two different speed-test tasks on the same router**):

```text
configure
set service snmp script-extensions extension-name gmcs_vyos_speedtest script /config/user-data/gmcs-vyos-speedtest/extend.py
set system task-scheduler task gmcs-vyos-direct crontab-spec '23 * * * *'
set system task-scheduler task gmcs-vyos-direct executable path '/config/scripts/gmcs-vyos-speedtest/runner.sh'
commit
save
exit
```

If the old `gmcs-speedtest` VyOS task was previously enabled on this same router, review it and disable it before enabling the new scheduler to avoid duplicate hourly runs; leave unrelated tasks untouched. Keep the router SNMPv3 monitoring configuration and LibreNMS allowlists exactly as they already are. VyOS SNMP extend syntax is documented at https://docs.vyos.io/en/1.4/configuration/service/snmp.html.

## 2. Verify SNMP from LibreNMS, without triggering a speed test

The poller should use the existing router SNMPv3 auth/priv profile and view permissions:

```sh
snmpget YOUR_APPROVED_SNMPv3_OPTIONS VERIFIED_ROUTER_IP \
  'NET-SNMP-EXTEND-MIB::nsExtendOutputFull."gmcs_vyos_speedtest"'
```

Look for the JSON `version`, `error`, `data.status`, `data.download_mbps`, `data.upload_mbps`, `data.latency_ms`, `data.jitter_ms`, and `data.loss_pct`. SNMP only exposes the cached, nonsensitive numeric readings—no agent credentials, hostnames, router IPs or private commands. Make sure the SNMP daemon account can traverse `/config/user-data` and read `latest.json` (0644). Do not expose SNMP beyond management networks or add a new public community.

## 3. Install the NEW native LibreNMS application, without touching old graphs

The three graph panels appear under the existing VyOS device's **Apps** tab. This requires installing a *new* LibreNMS poller, page and 3 graph definitions on the LibreNMS host—not just registering the device by SNMP. The new module deliberately uses `gmcs_vyos_speedtest` to avoid replacing your older `vyos_speedtest` RRDs.

From a checked-out repository on LibreNMS (check your LibreNMS root instead of assuming `/opt/librenms`):

```sh
SRC=integrations/librenms-app/gmcs_vyos_speedtest
sudo test ! -e /opt/librenms/includes/polling/applications/gmcs_vyos_speedtest.inc.php || exit 1
sudo install -m 0644 "$SRC/includes/polling/applications/gmcs_vyos_speedtest.inc.php" /opt/librenms/includes/polling/applications/
sudo install -m 0644 "$SRC/includes/html/pages/device/apps/gmcs_vyos_speedtest.inc.php" /opt/librenms/includes/html/pages/device/apps/
sudo install -m 0644 "$SRC/includes/html/graphs/application/gmcs_vyos_speedtest_local_bandwidth.inc.php" /opt/librenms/includes/html/graphs/application/
sudo install -m 0644 "$SRC/includes/html/graphs/application/gmcs_vyos_speedtest_local_ping.inc.php" /opt/librenms/includes/html/graphs/application/
sudo install -m 0644 "$SRC/includes/html/graphs/application/gmcs_vyos_speedtest_local_loss.inc.php" /opt/librenms/includes/html/graphs/application/
```

Validate all new `.inc.php` files with `php -l`. Ensure Applications discovery/polling is enabled on this router, then discover and poll that single device using the commands appropriate to your LibreNMS installation, e.g. `sudo -u librenms ./lnms device:discover 10.7.8.10` and `sudo -u librenms ./lnms device:poll 10.7.8.10` when run inside LibreNMS root (use actual device hostname/ID). An existing router device such as 7613 / `10.7.8.10` is **not proof** that the correct agent is enrolled or installed on it.

Inspect **Apps → GMCS VyOS Speedtest** on the chosen device: download/upload Mbps, latency/jitter and packet-loss charts, with native LibreNMS day/week/month/year ranges. Missing cache or stale tests show gaps rather than false 0 Mbps. LibreNMS docs on SNMP-extend applications: https://docs.librenms.org/Extensions/Applications/.

## 4. Retention and historical graphs

RRDs only accumulate observations **from the date this new application first starts polling**. Historical Ookla graphs are not copied, modified or reused. For two-year graph views, inspect the **actual RRD archives** (`rrdtool info ...`) and change archive configuration through LibreNMS administration if they do not cover at least 732 days. Do not assume that hourly resolution will be retained for two years: older data may be consolidated.

## 5. Troubleshooting

- `disabled`: set `inside.enabled=true` after agent enrollment.
- `failed`: debug the router's CA trust, DNS, route, source NAT, agent token and the GMCS server's HTTPS port 18443. Only the router's local runner starts tests.
- `stale`: no successful *recent* scheduled run; inspect VyOS task scheduler and run the agent manually.
- Missing SNMP output: verify the VyOS extension is committed/saved, SNMPv3 view, execute permission and cache traversal as the SNMP runtime account.
- No **Apps** entry: verify LibreNMS PHP poller path, enable applications discovery and run discovery/polling on exactly this VyOS device.
- Blank RRD: first confirm a fresh local test and SNMP output, then validate the LibreNMS application poller and datapoint DS names (`inside_down`, `inside_up`, `inside_ping`, `inside_jitter`, `inside_loss`).
