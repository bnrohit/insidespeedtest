# GMCS — VyOS measures locally; LibreNMS polls VyOS SNMP and owns the RRD graphs

**This is NOT the central SSH/iperf collector, NOT a LibreNMS polling-triggered speed test, and NOT an update to the NOC server.** The router itself performs the measurement, caches a small nonsecret JSON payload, and exposes it over VyOS's existing SNMP protocol. The central HTTPS `10.250.31.192:18443` VM acts only as the passive inside-test endpoint; it does not run a measurement or retrieve school results.

## Important compatibility with the old app

The GMCS LibreNMS screenshots show an **existing custom** `Vyos Speedtest` application (device 7613, router `10.7.8.10`), headings **Ookla - Bandwidth**, **Ookla - Ping**, **Local - inside - Bandwidth**, and `-nan` for missing datasets. We do **not** possess its custom PHP poller, SNMP extension schema, or previous RRD definitions. Therefore, this pilot installs a **separate** `gmcs_vyos_speedtest` application with equivalent graphs; **it does NOT overwrite** `vyos_speedtest`, modify its RRDs or make historical numbers appear. A lossless continuation of *exactly* the old graphs requires inspecting the old PHP+RRD schema on LibreNMS first.

### Supported paths

1. **Ookla → public Internet:** Optional pre-installed official Ookla `speedtest --format=json`. This is an uncapped external service and can saturate a school WAN. Do not schedule hourly without appropriate capacity/off-hours policy. Binary or EULA is **not installed or accepted automatically**; if unavailable, output is `null`/`not_installed`, not zero.
2. **Local - inside:** VyOS runs `school_agent.py` *locally*, initiating small HTTPS downloads/uploads against the GMCS server, and writes its own observed Mbps, latency, jitter and loss. An individual authorized router credential and source IP `/32` must be enrolled in the GMCS Admin UI. The server's role is to respond to HTTP(S) requests, not to measure; it may also keep a copy of the result for normal GMCS reporting. The measured endpoint is the VM **not** a separate `iperf3` target, and the output is not ISP line-rate speed.
3. **LibreNMS SNMP poller:** 5-minute polls call `NET-SNMP-EXTEND-MIB::nsExtendOutputFull."gmcs_vyos_speedtest"` on the VyOS router. The extend script only reads the cached JSON and has **no credentials or shell/net access**. Custom LibreNMS application PHP writes 10 GAUGE datasets to that **router device's** LibreNMS RRDs, with normal day/week/month/year graph controls.

## A. VyOS installation (one authorized test router; no automatic changes to VyOS configuration)

Stage this directory and `agent/school_agent.py` on the router. From a management workstation, after cloning/updating `bnrohit/insidespeedtest`:

```bash
scp -r integrations/vyos-snmp-direct nwadmin@YOUR_VERIFIED_VYOS_IP:/tmp/gmcs-vyos-snmp-direct
scp agent/school_agent.py nwadmin@YOUR_VERIFIED_VYOS_IP:/tmp/gmcs-school-agent.py
```

On the actual school VyOS router:

```bash
sudo sh /tmp/gmcs-vyos-snmp-direct/install.sh
sudo install -m 0755 /tmp/gmcs-school-agent.py /config/scripts/gmcs-speedtest/school_agent.py
sudo vi /config/auth/gmcs-speedtest/direct.json
```

Set `inside.enabled` to `true` ONLY after registering the router in GMCS Admin > Scheduled Linux school servers with a distinct agent ID and verified source `/32`; create `/config/auth/gmcs-speedtest/token` (0600, root-owned) by your approved secret-transfer method. Configure an approved district CA file and verify the certificate covers the name/IP in `inside.url`. No insecure HTTP fallback or `curl -k` is used for authenticated testing. If the code or certificate is wrong, an explicit error status appears.

For Internet measurement, first install and license the **official compatible Ookla binary through your change-management process** and verify it works in shell, then set `ookla.enabled=true`. Keep disabled at first if school links are limited; tests can heavily impact real users.

Check and run once BEFORE enabling any hourly task:

```bash
sudo python3 /config/scripts/gmcs-vyos-speedtest/collect.py --validate-only
sudo /config/scripts/gmcs-vyos-speedtest/runner.sh
sudo cat /config/user-data/gmcs-vyos-speedtest/latest.json
sudo /config/user-data/gmcs-vyos-speedtest/extend.py
```

The cached file has no admin passwords, bearer keys, arbitrary command output or hostname. It is regenerated atomically by each scheduled test. Reports older than 150 minutes are exposed with `null` measurements so stale values aren't mistaken for current measurements.

Only after the first successful local measurement, enter VyOS config mode:

```text
configure
set service snmp script-extensions extension-name gmcs_vyos_speedtest script '/config/user-data/gmcs-vyos-speedtest/extend.py'
set system task-scheduler task gmcs-vyos-direct crontab-spec '23 * * * *'
set system task-scheduler task gmcs-vyos-direct executable path '/config/scripts/gmcs-vyos-speedtest/runner.sh'
commit
save
exit
```

**Change the minute per router** and prevent duplicate scheduled tests from the prior `gmcs-speedtest` VyOS task or the optional NOC SSH collector. Never schedule the speed-test command as the SNMP extend: LibreNMS polls frequently, and doing so would overload school WAN. VyOS officially documents the persistent `service snmp script-extensions` configuration: https://docs.vyos.io/en/1.4/configuration/service/snmp.html

Confirm the SNMP agent's OS account can traverse `/config/user-data` and execute the extend; on some systems shell ACLs or ownership require adjustment. Test from the actual LibreNMS poller over your existing restricted SNMPv3/allowlisted management path. Do not add a public v2c community.

```bash
# On LibreNMS, with your existing authenticated SNMP options (do not paste secrets):
snmpget [YOUR_EXISTING_SNMPv3_OPTIONS] YOUR_VERIFIED_VYOS_IP \
  'NET-SNMP-EXTEND-MIB::nsExtendOutputFull."gmcs_vyos_speedtest"'
```

## B. New non-destructive LibreNMS application

From the GitHub checkout, copy only the **new** files from `integrations/librenms-app/gmcs_vyos_speedtest/` to the corresponding relative paths under `/opt/librenms/`. Review paths and backup the LibreNMS host before writing; do not overwrite any existing file. Example:

```bash
cd /path/to/insidespeedtest
SRC=integrations/librenms-app/gmcs_vyos_speedtest
# Confirm this is a NEW app; abort if it already exists:
test ! -e /opt/librenms/includes/polling/applications/gmcs_vyos_speedtest.inc.php || exit 1
sudo cp -vn "$SRC/includes/polling/applications/gmcs_vyos_speedtest.inc.php" \
  /opt/librenms/includes/polling/applications/
sudo cp -vn "$SRC/includes/html/pages/device/apps/gmcs_vyos_speedtest.inc.php" \
  /opt/librenms/includes/html/pages/device/apps/
sudo cp -vn "$SRC/includes/html/graphs/application/gmcs_vyos_speedtest_"*.inc.php \
  /opt/librenms/includes/html/graphs/application/
```

Validate all six PHP files with `php -l`. On LibreNMS, confirm Applications discovery and polling modules are enabled for the existing VyOS device. Then run discovery and polling **for that router only**, using your local LibreNMS CLI version (`./lnms device:discover` and `./lnms device:poll` or `./discovery.php -h` and `./poller.php -h`). Check LibreNMS's `Apps` tab for **GMCS VyOS Speedtest**. This app discovers the SNMP extend `gmcs_vyos_speedtest` and writes RRD GAUGE datasets: `ookla_down`, `ookla_up`, `ookla_ping`, `ookla_jitter`, `ookla_loss`, `inside_down`, `inside_up`, `inside_ping`, `inside_jitter`, `inside_loss`. It shows four panels matching the old headings, with a separate local ping panel.

Do not modify LibreNMS's core global discovery script. The existing `vyos_speedtest` application and RRDs remain untouched. If you need its *same* historical files, capture the old source using the non-mutating steps in section C and map the existing dataset names before an explicit cutover.

## C. Read-only old-application audit (preserve 2-year history)

On your LibreNMS host, run without modifying anything:

```bash
sudo find /opt/librenms/includes/polling/applications \
  /opt/librenms/includes/html/pages/device/apps \
  /opt/librenms/includes/html/graphs/application -maxdepth 1 \
  -type f -iname '*vyos*speed*' -print
sudo find /opt/librenms/rrd -type f -iname '*vyos*speed*.rrd' -print | head -40
```

The file names, poller code (after checking it contains no credentials), and `rrdtool info` **dataset names** allow an exact compatibility adapter instead of writing a new history. A graph marked `-nan` may be due to a missing SNMP extension, failed command, schema mismatch, stale RRD, or absent data: the screenshot alone cannot establish which one.

LibreNMS RRD archives commonly consolidate older data. Verify actual 2-year retention on this installation before claiming 2-year hourly-resolution history. Preserve backups and old RRD files.

## D. Troubleshooting and safeguards

- Local test missing => check `sudo /config/scripts/gmcs-vyos-speedtest/runner.sh`, private token, observed source-IP match, router CA certificate, VyOS outbound route/DNS and the GMCS service health.
- Ookla missing => explicitly check installation/license and configured `ookla.enabled`, and ensure firewall policy permits its normal external endpoints.
- SNMP empty => check VyOS `service snmp script-extensions` commit/save, restricted SNMPv3 view, `nsExtendOutputFull`, OS permissions to cache, and read-only execution of `extend.py`.
- LibreNMS app not detected => ensure its PHP poller file exists, applications module enabled, extension name matches `gmcs_vyos_speedtest`, and discovery/poller runs for the device.
- All-missing data are written as NULL (not zero), and stale tests older than 150 minutes are masked.
- Keep sample caps small on school WAN; external Ookla has **no enforced cap** in our wrapper. No HTTP tests to arbitrary hosts and no installation of unknown binaries.
