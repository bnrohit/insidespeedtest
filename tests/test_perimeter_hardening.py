"""Static defense-in-depth tests: production exposure still needs an external scan."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_nginx_image_is_october_2026_patched_stable():
    compose = read("compose.nginx.yaml")
    assert re.search(r"image:\s+nginx:1\.30\.6-alpine\b", compose)
    assert "network_mode: host" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "./private/tls:" in compose
    assert ":/etc/ssl/gmcs-speedtest:ro" in compose


def test_only_https_proxy_and_host_loopback_backend():
    config = read("deploy/nginx.container.conf")
    backend = read("Dockerfile")
    assert "listen 443 ssl;" in config
    assert "proxy_pass http://127.0.0.1:8080;" in config
    assert "--host\", \"127.0.0.1\"" in backend
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in config
    assert "server_tokens off;" in config
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in config


def test_no_mdns_ports_published_or_used_by_app():
    for rel in ("compose.yaml", "compose.nginx.yaml", "Dockerfile", "app/main.py", "deploy/nginx.container.conf"):
        assert not re.search(r"\b5353\b|\bavahi\b|\bzeroconf\b", read(rel), re.I)


def test_mdns_remediation_not_implicit():
    script = read("deploy/mdns-audit.sh")
    assert "--apply" in script and "--check" in script
    assert 'if [[ "$mode" == \'--apply\' ]]' in script
    assert "avahi-daemon.socket" in script
    assert "ufw deny in 5353/udp" in script
    assert "ufw enable" not in script
