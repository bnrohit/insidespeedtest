# Security policy

This website is intended for GMCS **internal networks only**, even though its source code is public.

## Reporting a vulnerability

Report security issues privately using this repository's **Security > Report a vulnerability** workflow (GitHub private vulnerability reporting) when available. If unavailable, contact the district's authorized IT/security team through its established incident channel. Do not post credentials, real student/client IP addresses, network diagrams or exploit traces publicly. Do not attempt unauthorized scans or tests on the production district deployment.

## Administration checklist

- Restrict inbound HTTPS/443 to authorized school/admin subnets at the network firewall. Expose no 8080 listener publicly; the container is loopback-bound.
- Use a trusted TLS certificate and preserve real client IP only through a designated and trusted Nginx reverse proxy.
- Keep `private/` subnet mapping and agent hashes, `.env` SMTP credentials, admin password and SQLite data out of Git. Never deploy the example subnet rows as facts.
- Limit `/admin` and `/api/admin/` to administrators on management networks. Rotate secrets when staff or servers change. Use a unique agent token per school cache server.
- Monitor email statuses, security logs, test volume, bandwidth and application errors. Back up the SQLite volume.
- Review weekly dependency scanning and CodeQL results. Test fixes in staging before redeploying school production.
- Understand limits: browser-reported speeds can be fabricated; a source IP behind NAT does **not** prove a VLAN; email suppression does not prevent all SMTP operational failures.

No automated test or scanner can establish that an application has no security flaws.


Admin GUI access is additionally restricted by `ADMIN_CLIENT_CIDRS` (public-source default loopback only; set verified NOC admin CIDRs in the private VM .env), independent of Nginx ACLs. SMTP passwords
are rejected and cleared when the selected mail mode is unencrypted. Never
commit the private district mapping inventory, tokens, mail settings or logs.
No automated scanner can prove that software has zero vulnerabilities; test
and patch regularly.

## October 2026 Nginx and Bonjour hardening

- Nginx stable security baseline **1.30.6** (or mainline **1.31.7+**) as of 2026-10-21; versions 1.28.2 / 1.29.5 solve an *older* CVE but are not fully current. Use `compose.nginx.yaml` to run a pinned official image on the dedicated VM, or patch host Nginx separately. Review newer advisories before each deployment.
- The Python application has no mDNS functionality, but host OS processes and VLAN reflectors can expose Bonjour/ZeroConf metadata on **UDP/5353**. Run `sudo bash deploy/mdns-audit.sh --check`. With explicit approval, `--apply` disables host Avahi where present. Inspect `systemd-resolved`, other responders, and network-firewall/relay rules separately.
- Do not push TLS private keys or cert files in `private/tls/` to the public repository. Prefer signed/pinned Nginx images and verify the running server version after deployment. Never infer from GitHub code that production Nginx or Avahi was upgraded.
- Perimeter validation must include TCP 443 accessible from approved subnets, TCP 8080 blocked remotely, and no observable mDNS response on UDP 5353 from a Nessus vantage point. Complete an authorized re-scan, rather than promising a vulnerability-free result.
