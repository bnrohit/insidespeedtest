# GMCS hourly VyOS → NOC metrics and LibreNMS graphs (v9)

## Design and scope

- **Single Debian central scheduler:** `10.250.31.192` runs the already-piloted SSH/VyOS collector. It does not require Windows, Linux, macOS or endpoint scripts on school devices, and does not configure routers.
- **One bounded test per enabled school per hour:** on minute 45, the existing collector uses an approved `nwadmin` SSH identity, fixed receiver `10.250.31.192:5201`, and **30 Mbps cap** from the existing private `/etc/gmcs-router-report/config.json`. Upload/download plus latency, packet loss and failure status are recorded. This measures the **router-to-NOC WAN path**, not a device's Internet speed, true ISP capacity or Wi-Fi throughput.
- **Explicit pilot only:** The default config enables the 17 schools previously verified. The existing 19 SSH-unreachable routers are **not called down**, and the `CORE/NOC/SHP`, `TOH/TST` exclusions remain excluded. School records without tests are `NOT_ENROLLED`, `NEEDS_VERIFICATION` or `SKIPPED_INFRA` with no invented measurements.
- **Two-year raw retention** in the existing SQLite data volume: 732-day rolling window, with deduplication by site/hour. CSV snapshots go under `/var/lib/gmcs-router-hourly/csv/` (permissions 0700). For long-term durability, include both in normal encrypted server backups.
- **Browser graphs** in Admin > Hourly school → NOC WAN history. Select a site and 6 hours, day, week, month, year or 2 years. Long windows are downsampled; gaps are missing data, not 0 Mbps.
- **LibreNMS graphs** through its existing services/Nagios performance-data RRDs. LibreNMS polls a read-only, fixed-site HTTPS JSON endpoint using a separate secret. LibreNMS never launches iperf3, polls the same hourly record up to twelve times between tests, and does not receive any SSH passwords or diagnostic endpoint details.

## 1. Update web server source (on `rohith@10.250.31.192`)

```bash
cd /home/rohith
git -C insidespeedtest-upstream pull --ff-only origin main
sudo bash /home/rohith/insidespeedtest-upstream/deploy/gmcs-safe-upgrade.sh
curl -fsS http://127.0.0.1:18080/healthz
```

This safe installer replaces only audited application files; it does not replace `.env`, current Nginx/Compose overrides, known-good VLAN/IPAM mappings, SMTP, router SSH credentials, or the SQLite volume. A rollback path is printed.

## 2. Install hourly systemd job **disabled**, then explicitly enable after review

```bash
sudo bash /home/rohith/insidespeedtest-upstream/integrations/vyos-hourly/install-hourly.sh
sudo cat /etc/gmcs-router-hourly/config.json
sudo systemctl enable --now gmcs-router-hourly.timer
sudo systemctl list-timers gmcs-router-hourly.timer
```

A controlled pilot run is possible with `sudo systemctl start gmcs-router-hourly.service`, followed by `sudo journalctl -u gmcs-router-hourly.service -n 60 --no-pager`. Do not enable a second hourly timer if a future per-router push collector is deployed; the test server must not run overlapping iperf3 jobs. This scheduler reuses the **morning collector's lock** by passing its existing output directory. The daily mail job remains separate, so hourly jobs never send an email.

To expand beyond the 17 pilots: first verify each router's IP and SSH host key, ensure approved credentials already exist, confirm WAN capacity, then add exact site codes to `/etc/gmcs-router-hourly/config.json`. Do not bulk-Trust-On-First-Use across unknown routers.

## 3. LibreNMS integration on the LibreNMS server (separate host)

LibreNMS documentation supports Nagios plugins and `|` performance-data storage with native per-service graphs: https://docs.librenms.org/Extensions/Services/

First, on the **GMCS Debian speed-test VM** generate the monitoring-only credential (not the admin password):

```bash
sudo bash /home/rohith/insidespeedtest-upstream/integrations/librenms/create-monitor-token.sh
```

Move the credential file **out-of-band through an approved secure administrator transfer** from the Docker `/data/gmcs-monitoring.token` mount to LibreNMS at `/etc/librenms/gmcs-monitoring.token`. Its contents must not be published to GitHub or pasted into chat/logs. Permission it to `librenms`, mode 0600, and back it up securely. Do not copy by logging it to the terminal.

On the **LibreNMS poller host**, install the plugin using an approved deployment mechanism:

```bash
sudo install -m 0755 check_gmcs_router.py /usr/lib/nagios/plugins/check_gmcs_router.py
sudo chown librenms:librenms /etc/librenms/gmcs-monitoring.token
sudo chmod 600 /etc/librenms/gmcs-monitoring.token
```

Ensure the HTTPS certificate of the GMCS server is trusted by LibreNMS and matches the URL (the self-signed-by-IP setup may need a district-CA certificate and DNS name). **Do not use `-k`, disable hostname checking, use HTTP, or send the token to a different endpoint.** Install a district CA chain if appropriate. Example after DNS/certificate configuration:

```bash
sudo -u librenms /usr/lib/nagios/plugins/check_gmcs_router.py \
  --site CDE --url https://speedtest.gmcs.k12.nm.us:18443 \
  --token-file /etc/librenms/gmcs-monitoring.token \
  --ca-file /etc/ssl/certs/gmcs-internal-ca.pem
```

Expected output on a recent successful sample resembles `OK - CDE router-to-NOC capped ... | download_mbps=...Mbps... upload_mbps=...Mbps ...` with exit status 0. Unenrolled/unreachable/stale schools return `UNKNOWN`, not a false claim of outage. Failure is not silently shown as zero bandwidth.

**LibreNMS UI**: For each *existing verified school router device* under Devices > [school router] > Services > Add Service, choose type **`gmcs_router.py`** (LibreNMS strips the `check_` prefix), description `GMCS CDE router-to-NOC capped throughput`, and parameters `--site CDE --url https://speedtest.gmcs.k12.nm.us:18443 --token-file /etc/librenms/gmcs-monitoring.token --ca-file /etc/ssl/certs/gmcs-internal-ca.pem`. Use the correct school code per device. Do not register a service under an unverified IP; validate LibreNMS's device-to-site mapping first. The plugin accepts **only** fixed site codes and needs no router credentials. Perform one pilot site first, then expand to all 17 validated schools.

LibreNMS's services poller normally runs every five minutes and writes RRD performance data for graphing (no extra speed test). Ensure the Services module and poller/dispatcher are enabled in your LibreNMS deployment. For long-term charts, **verify the RRA retention on the actual service RRD** (check `rrdtool info /opt/librenms/rrd/<device>/services-<ID>.rrd`, adjusting to your deployment); default LibreNMS RRD consolidation settings may retain long-range daily averages but should never be assumed. Extend/recreate with backup only if existing archives do not retain at least 730 days. Changing `rrd_purge` does **not** extend RRD resolution or archive duration: https://docs.librenms.org/Support/Cleanup-options/

LibreNMS service graph resolution is generally averaged/consolidated for older periods; exact original hourly observations remain in GMCS SQLite for 732 days.

## 4. Verification and limits

```bash
sudo journalctl -u gmcs-router-hourly.service -n 80 --no-pager
sudo docker exec gmcs-inside-speed-test printenv DB_PATH
curl -ksS -o /dev/null -w 'Site admin HTTP %{http_code}\n' https://127.0.0.1:18443/admin
```

After the first hourly sample, log into the admin dashboard, select CDE and each period. To prevent LibreNMS false negatives, the plugin reports `UNKNOWN` when no successful test is available or when the latest sample is older than 2.5 hours. Tune LibreNMS notifications so a bad/old sample is investigated separately from device availability.

## 5. Diagnostics roadmap

Future stages could combine link errors, Meraki Wi-Fi health, VyOS OSPF neighbor and interface counters, Nexus port drops, jitter/loss and client browser results in one correlated timeline. Such integration needs **read-only, scoped API/SNMP access**, and must not silently collect staff/student device secrets or issue privileged remediation commands.
