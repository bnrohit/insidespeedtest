# Network-service security baseline

This application does not bundle NGINX. The deployment VM's reverse proxy is an external host package and must be maintained by the administrator.

Current minimum baseline (reviewed 2026-10-21):

- Use **NGINX stable 1.30.6 or later**, or a mainline release **1.31.7 or later**.
- Keep `server_tokens off;` in the reverse-proxy configuration.
- Do not install or enable Avahi, Bonjour, ZeroConf, an mDNS repeater, or another multicast DNS responder on the dedicated speed-test VM.
- Do not expose **UDP/5353** from the VM or through container/host firewall rules.
- Keep the application backend on loopback as documented and expose only the intended HTTPS listener to approved internal networks.

Recommended host verification after OS/proxy updates:

```bash
nginx -v
sudo systemctl disable --now avahi-daemon 2>/dev/null || true
sudo ss -lun | grep ':5353 ' && echo "Review UDP/5353 exposure" || true
sudo nginx -t
```

If another approved service requires mDNS on the same host, move this application to a dedicated VM or document and firewall the exception rather than silently exposing multicast discovery.
