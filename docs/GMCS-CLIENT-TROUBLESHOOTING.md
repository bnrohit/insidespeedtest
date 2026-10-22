# GMCS speed-test troubleshooting reports (v7)

## What's collected

A completed speed test records client source IP (already required for school/VLAN mapping), throughput, ten HTTP round-trip samples, latency/jitter, plus **limited** browser context: coarse platform/browser name, Network Information API effective connection type/estimated RTT when available, `navigator.onLine`, and a best-effort HTTPS response-time sample to `/api/identity`. These are **not** hardware adapter, MAC-address, DHCP, physical Wi-Fi or operating-system command results.

Administrators select **Diagnose** next to each result under Admin > Results History or enter a result ID in the **Client Troubleshooting Center**. Heuristics flag HTTP probe failures, high internal latency/jitter, very low relative throughput and diagnostic command failure hints. They present possible causes and next checks rather than pretending to prove a root cause. Compare to known-good local wired devices and VyOS WAN/OSPF, Nexus uplinks, Meraki port errors, DNS servers and NOC VM capacity.

## Optional advanced Windows / macOS reports

Web browsers **cannot** execute `ipconfig`, `getmac`, `tracert`, `netstat`, `arp`, `ifconfig`, `scutil` or privileged DNS cache operations, or identify a NIC MAC address. The site does not attempt to bypass these boundaries, remotely execute commands, install an agent or scan arbitrary destinations.

The homepage provides **downloadable, human-readable, read-only** scripts:

- Windows PowerShell: `gmcs-diagnostics-windows.ps1` (optional `-IncludeSensitive` for `getmac`, ARP, netstat sockets, DNS cache). For staff working with PowerShell execution-policy restrictions, follow their IT organization's script-signing policy; do not disable organizational controls. By default the script includes `ipconfig /all`, hostname, local gateways, configured DNS and limited ping/traceroute/nslookup checks.
- macOS bash: `gmcs-diagnostics-macos.sh` (optional `--include-sensitive` for adapters/ARP/netstat/cache). macOS requires Python 3 for its local JSON serializer.

Each script uses the **device's actual configured resolver IPs** (not the server's resolver or hardcoded private infrastructure), and fixed public target `8.8.8.8`. It saves a JSON file on the client's Desktop and **does not upload** anything. The user reviews its contents, opts in with the checkbox, and manually chooses the JSON to attach to the completed speed-test result. Sensitive reports may contain hostname, hardware addresses, internal IPs, ARP peers or active socket endpoints. Obtain district approval before gathering or uploading those data, particularly from student/personal devices. No browser-run scripts read unrelated files.

Do **not** automatically flush DNS, change DHCP leases, restart adapters, route packets or clear caches during diagnostics. For a deliberate remediating action after approval: Windows `ipconfig /flushdns`; macOS `sudo dscacheutil -flushcache` and `sudo killall -HUP mDNSResponder`. These are **not performed** by the diagnostic scripts and may affect current sessions.

## Storage/security and limitations

- New SQLite table in the *existing mounted database*; no database replacement or private IP mapping changes. Client data is pruned at startup after 30 days, not indefinitely; this is opportunistic startup pruning, not a guaranteed per-day deletion schedule.
- Advanced uploads are restricted to fixed command label keys, total 34k JSON characters and 3,600 characters per command. Only one report is accepted for a completed browser test, within 24 hours, authenticated by the client's test token and the observed source IP. HTTPS is mandatory. Admins require network-restricted login and CSRF-protected sessions to modify configuration; detailed reports are read-only and admin-only.
- A client who visits the site but does not run a speed test has no report. A person who completes a test but does not opt into advanced collection has no native data; don't characterize it as missing/failed.
- Internet egress from the NOC VM and the separate Cloudflare browser link remain independently measured. The app cannot attribute path problems to specific Nexus, VyOS, ISP or Wi-Fi components without corroborating device counters and path testing. No arbitrary scans or remote device control are provided.

## Install/update

From Debian VM `rohith@10.250.31.192`, use **separate** GitHub checkout (existing v6 install):

```bash
cd /home/rohith
git -C insidespeedtest-upstream pull --ff-only origin main
sudo bash /home/rohith/insidespeedtest-upstream/deploy/gmcs-safe-upgrade.sh
curl -fsS http://127.0.0.1:18080/healthz
curl -kfsS https://127.0.0.1:18443/api/identity
```

The safe deploy replaces only explicitly listed application files and preserves `.env`, private Nginx config, school/VLAN mappings, SMTP, and the existing SQLite mount. It creates a fresh backup and prints an exact rollback command. The admin login page and website remain on port `18443`. Test optional report upload from a permitted management/staff device and confirm the **Diagnose** view before enabling broad operational use.
