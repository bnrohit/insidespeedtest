# Security policy

This website is intended for GMCS **internal networks only**, even though its source code is public.

## Reporting a vulnerability

Report security issues privately using this repository's **Security > Report a vulnerability** workflow (GitHub private vulnerability reporting) when available. If unavailable, contact the district's authorized IT/security team through its established incident channel. Do not post credentials, real student/client IP addresses, network diagrams or exploit traces publicly. Do not attempt unauthorized scans or tests on the production district deployment.

## Administration checklist

- Restrict inbound HTTPS/443 to authorized school/admin subnets at the network firewall. Expose no 8080 listener publicly; the container is loopback-bound.
- Use a trusted TLS certificate and preserve real client IP only through a designated and trusted Nginx reverse proxy. Require NGINX stable **1.30.6+** or mainline **1.31.7+** and keep `server_tokens off;`.
- Keep `private/` subnet mapping and agent hashes, `.env` SMTP credentials, admin password and SQLite data out of Git. Never deploy the example subnet rows as facts.
- Limit `/admin` and `/api/admin/` to administrators on management networks. Rotate secrets when staff or servers change. Use a unique agent token per school cache server.
- Disable Avahi/Bonjour/ZeroConf on this dedicated server and verify that nothing is listening on **UDP/5353**. Run `sudo bash deploy/security-preflight.sh` after OS or proxy changes.\n- Monitor email statuses, security logs, test volume, bandwidth and application errors. Back up the SQLite volume.
- Review weekly dependency scanning and CodeQL results. Test fixes in staging before redeploying school production.
- Understand limits: browser-reported speeds can be fabricated; a source IP behind NAT does **not** prove a VLAN; email suppression does not prevent all SMTP operational failures.

No automated test or scanner can establish that an application has no security flaws.
