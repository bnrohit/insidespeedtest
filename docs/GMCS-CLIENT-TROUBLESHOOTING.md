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

## v8: One-time pairing for automatic submission after local launch (Windows)

A website **cannot automatically execute downloaded PowerShell files**. Users must explicitly launch a GMCS-approved signed diagnostic package, or IT must deploy it via supported endpoint management such as Intune. Downloads **must not** disable Smart App Control, Defender, App Control for Business, PowerShell policy, browser safety checks or TLS certificate validation.

After completing a browser speed test, a client can tick the device-data consent box and select **Create secure upload code**. The website shows a random one-time code valid for 10 minutes. Download the *GMCS IT-approved, signed* `gmcs-diagnostics-windows.ps1` to the client. Once it is explicitly executed, the script saves a local JSON on the Desktop, asks for the code, displays what will be sent, and asks for **YES** confirmation. It then uploads the report **directly** to the existing admin troubleshooting result. No manual JSON upload is necessary after a successful transfer. The manual upload fallback remains available. Sensitive MAC/ARP/netstat/DNS-cache fields still require explicitly passing `-IncludeSensitive` and consent.

**Privacy/security:** The paired upload is allowed only via HTTPS, from the same source IP as the completed speed test, to a single result, before code expiry. Codes are stored hashed, invalidated when regenerated or redeemed, and submissions are rejected for unmatched IP, reuse or malformed reports. The web cannot access local MACs or netstat. Reports may identify a person/device and should only be gathered according to district policy, particularly for students and personal devices. The admin dashboard limits visibility to authorized IT accounts. Captured reports are pruned at application startup after 30 days; implement a scheduled retention job if strict automated deletion is required.

**Certificate dependency:** `https://10.250.31.192:18443` must have a TLS certificate **trusted on Windows and valid for the host/IP used**. If the current Nginx certificate is self-signed or the hostname does not match, `Invoke-RestMethod` will **fail securely** and leave the local JSON intact. Provision a district PKI/trusted certificate with correct SAN (prefer a district-owned DNS name), then change the script's configured `-ServerUrl` appropriately. Never use `-SkipCertificateCheck`, certificate-validation callbacks, HTTP, or execution-policy bypasses for the upload.

**Smart App Control:** Microsoft does not offer a per-file allow exception. Unsigned scripts downloaded from the web can be rejected. A GMCS release process must produce a genuine Authenticode signature with a trusted code-signing certificate and test the entire signed artifact on a pilot Windows 11 device with Smart App Control/App Control policies in the actual enforced configuration. Do not claim that a GitHub-distributed unsigned `.ps1` is SAC-approved. For managed endpoints, deploy the signed script using Intune and district-approved App Control for Business rules, or develop and sign a packaged Win32 client. Do not distribute the certificate private key or commit signed-device secrets to GitHub.

Example *IT release procedure* on an authorized Windows signing workstation (replace `$thumbprint` only with the actual approved code-signing certificate thumbprint; **do not** run these lines on student devices):

```powershell
$script = '.\gmcs-diagnostics-windows.ps1'
$thumbprint = '<ACTUAL_GMCS_CODESIGN_CERT_THUMBPRINT>'
$cert = Get-Item "Cert:\CurrentUser\My\$thumbprint"
if (-not $cert.HasPrivateKey -or -not ($cert.EnhancedKeyUsageList | Where-Object { $_.FriendlyName -eq 'Code Signing' })) { throw 'Trusted code signing certificate required' }
Set-AuthenticodeSignature -FilePath $script -Certificate $cert -TimestampServer 'http://timestamp.digicert.com'
Get-AuthenticodeSignature $script | Format-List Status,SignerCertificate,TimeStamperCertificate
```

A `Status` other than `Valid` means **do not deploy**. Test trust and execution on managed Windows endpoints separately; valid Authenticode signing alone does not guarantee every App Control policy will allow it. The signed artifact is a separate deployment/release step and **is not created by the GitHub source push**.
