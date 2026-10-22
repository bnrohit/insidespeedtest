"""Self-hosted GMCS internal speed test; no Internet-dependent assets or services."""
from __future__ import annotations

import csv
import base64
import hashlib
import io
import ipaddress
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .agents import Agents, AGENT_ID_RE
from .database import (admin_blocked, admin_failure, admin_success, connect, create_session,
                       init_db, reserve_transfer, save_result, valid_session, set_email_status,
                       notification_group, claim_notification)
from .emailer import send_result, send_client_result
from .admin_auth import COOKIE_NAME, SESSION_SECONDS, new_session as new_admin_session, find_session, revoke_session
from .client_email import claim_email, EmailClaimError
from .branding_config import (DEFAULT_BRAND, init_branding, read_branding, write_branding,
                              read_logo, store_logo, clear_logo)
from .external_diag import init_external, history as egress_history, run_external
from .router_history import initialize as init_router_history, latest as latest_routers, latest_site, trend as router_trend, WINDOWS as GRAPH_WINDOWS
from .school_agent_history import initialize as init_school_history, listed as listed_school_agents, most_recent as recent_school_agent, graph as school_agent_graph
from .diagnostics import (init_diagnostics, record_browser, submit_advanced, fetch_report,
                          validate_advanced, issue_upload_code, submit_paired)
from .identity import IdentityMatcher
from .management import (SMTPForm, CSVForm, AgentForm, setup_managed, load_smtp,
                         smtp_public_config, save_smtp, put_mappings, list_agents,
                         put_agent, remove_agent, validate_mapping_csv)

log = logging.getLogger(__name__)
APP_ROOT = Path(__file__).resolve().parent
CHUNK = os.urandom(256 * 1024)  # incompressible for useful throughput measurement


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).lower().strip()
    if raw not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"Invalid boolean for {name}")
    return raw in {"true", "1", "yes"}


@dataclass(frozen=True)
class Settings:
    db_path: str
    mapping_path: str
    admin_username: str
    admin_password: str
    agents_path: str = str(APP_ROOT.parent / "config" / "agents.csv")
    allowed_client_cidrs: str = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128"
    trusted_proxy_cidrs: str = ""
    admin_require_https: bool = True
    allow_legacy_basic_api: bool = False  # Off by default: Basic Auth defeats reliable browser logout
    admin_client_cidrs: str = "127.0.0.0/8,::1/128"
    agent_require_https: bool = True
    email_browser_results: bool = True
    email_agent_results: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_tls_mode: str = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: tuple[str, ...] = ()
    cooldown_seconds: int = 120
    max_sessions_per_hour: int = 6
    max_session_mib: int = 384
    max_download_mib: int = 256
    max_upload_mib: int = 128
    email_dedupe_seconds: int = 86400
    max_active_tests: int = 20
    max_active_per_vlan: int = 4

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.getenv("DB_PATH", str(APP_ROOT.parent / "data" / "results.sqlite3")),
            mapping_path=os.getenv("MAPPING_PATH", str(APP_ROOT.parent / "config" / "networks.csv")),
            agents_path=os.getenv("AGENTS_PATH", str(APP_ROOT.parent / "config" / "agents.csv")),
            admin_username=os.getenv("ADMIN_USERNAME", "gmcsadmin"),
            admin_password=os.getenv("ADMIN_PASSWORD", ""),
            allowed_client_cidrs=os.getenv("ALLOWED_CLIENT_CIDRS", cls.allowed_client_cidrs),
            trusted_proxy_cidrs=os.getenv("TRUSTED_PROXY_CIDRS", ""),
            admin_require_https=env_bool("ADMIN_REQUIRE_HTTPS", True),
            allow_legacy_basic_api=env_bool("ALLOW_LEGACY_BASIC_API", False),
            admin_client_cidrs=os.getenv("ADMIN_CLIENT_CIDRS", cls.admin_client_cidrs),
            agent_require_https=env_bool("AGENT_REQUIRE_HTTPS", True),
            email_browser_results=env_bool("EMAIL_BROWSER_RESULTS", True),
            email_agent_results=env_bool("EMAIL_AGENT_RESULTS", True),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_tls_mode=os.getenv("SMTP_TLS_MODE", "starttls").lower(),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_from=os.getenv("SMTP_FROM", ""),
            smtp_to=tuple(s.strip() for s in os.getenv("SMTP_TO", "").split(",") if s.strip()),
            cooldown_seconds=int(os.getenv("SESSION_COOLDOWN_SECONDS", "120")),
            max_sessions_per_hour=int(os.getenv("MAX_SESSIONS_PER_HOUR_PER_IP", "6")),
            max_session_mib=int(os.getenv("MAX_SESSION_MIB", "384")),
            max_download_mib=int(os.getenv("MAX_DOWNLOAD_MIB", "256")),
            max_upload_mib=int(os.getenv("MAX_UPLOAD_MIB", "128")),
            email_dedupe_seconds=int(os.getenv("EMAIL_DEDUPE_SECONDS", "86400")),
            max_active_tests=int(os.getenv("MAX_ACTIVE_TESTS", "20")),
            max_active_per_vlan=int(os.getenv("MAX_ACTIVE_PER_VLAN", "4")),
        )


class AdminLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class ClientEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=30, max_length=150)


class BrandingForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_name: str = Field(min_length=1, max_length=60)
    site_name: str = Field(min_length=1, max_length=90)
    tagline: str = Field(min_length=1, max_length=80)
    heading: str = Field(min_length=1, max_length=90)
    description: str = Field(min_length=1, max_length=320)


class BrandingLogo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    png_data: str = Field(min_length=100, max_length=650000)


class BrowserDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str = Field(default="Unknown", max_length=45)
    browser: str = Field(default="Unknown", max_length=35)
    network_type: str = Field(default="Unknown", max_length=20)
    network_estimated_rtt_ms: int | None = Field(default=None, ge=0, le=100000)
    online: bool | None = None
    https_rtt_ms: float | None = Field(default=None, ge=0, le=30000, allow_inf_nan=False)


class AdvancedDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=30, max_length=150)
    platform: str = Field(min_length=1, max_length=32)
    hostname: str = Field(default="", max_length=100)
    commands: dict[str, str]


class PairedDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_code: str = Field(min_length=30, max_length=80)
    platform: str = Field(min_length=1, max_length=32)
    hostname: str = Field(default="", max_length=100)
    commands: dict[str, str]


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=30, max_length=150)
    download_mbps: float = Field(ge=0, le=100000, allow_inf_nan=False)
    upload_mbps: float = Field(ge=0, le=100000, allow_inf_nan=False)
    latency_ms: float = Field(ge=0, le=60000, allow_inf_nan=False)
    jitter_ms: float = Field(ge=0, le=60000, allow_inf_nan=False)
    packet_loss_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    download_bytes: int = Field(ge=1, le=100_000_000_000)
    upload_bytes: int = Field(ge=1, le=100_000_000_000)
    browser_diagnostics: BrowserDiagnostic | None = None


def parse_cidrs(value: str):
    return tuple(ipaddress.ip_network(item.strip(), strict=False) for item in value.split(",") if item.strip())


def peer_ip(request: Request):
    try:
        peer = ipaddress.ip_address(request.client.host if request.client else "")
        return peer.ipv4_mapped if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped else peer
    except ValueError:
        raise HTTPException(403, "Unable to identify client address")


def trusted_peer(request: Request) -> bool:
    return any(peer_ip(request) in n for n in request.app.state.trusted_proxy_cidrs)


def secure_transport(request: Request) -> bool:
    # No client can forge X-Forwarded-Proto: only a matching trusted proxy is consulted.
    if request.url.scheme == "https":
        return True
    return trusted_peer(request) and request.headers.get("x-forwarded-proto", "").lower() == "https"


def get_ip(request: Request) -> str:
    """Use observed socket IP; trust proxy IP only if proxy is specifically allowlisted."""
    ip = peer_ip(request)
    if trusted_peer(request):
        claimed = request.headers.get("x-real-ip", "")
        if not claimed:
            raise HTTPException(403, "Trusted reverse proxy must supply X-Real-IP")
        try:
            ip = ipaddress.ip_address(claimed.strip())
        except ValueError:
            raise HTTPException(400, "Invalid proxy client IP")
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
    if not any(ip in net for net in request.app.state.allowed_client_cidrs):
        raise HTTPException(403, "Internal GMCS clients only")
    return str(ip)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if len(settings.admin_password) < 16 or settings.admin_password.startswith("CHANGE_THIS_"):
        raise RuntimeError("Set ADMIN_PASSWORD to a unique, random value at least 16 characters long")
    if settings.smtp_tls_mode not in {"ssl", "starttls", "none"}:
        raise RuntimeError("Invalid SMTP_TLS_MODE")
    if settings.smtp_tls_mode == "none" and settings.smtp_username:
        raise RuntimeError("SMTP credentials require encrypted transport")
    if not (30 <= settings.cooldown_seconds <= 3600 and 1 <= settings.max_sessions_per_hour <= 100
            and 32 <= settings.max_session_mib <= 1024
            and 16 <= settings.max_download_mib <= settings.max_session_mib
            and 16 <= settings.max_upload_mib <= settings.max_session_mib
            and 300 <= settings.email_dedupe_seconds <= 604800
            and 1 <= settings.max_active_per_vlan <= settings.max_active_tests <= 100):
        raise RuntimeError("Invalid session limits")
    init_db(settings.db_path)
    init_branding(settings.db_path)
    init_external(settings.db_path)
    init_diagnostics(settings.db_path)
    init_router_history(settings.db_path)
    init_school_history(settings.db_path)
    managed = setup_managed(settings.db_path, settings.mapping_path, settings.agents_path)
    mapping = IdentityMatcher.from_csv(managed['mappings'])
    agents = Agents(str(managed['agents']))
    app = FastAPI(title="GMCS Inside Speed Test", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.managed = managed
    app.state.mapping = mapping
    app.state.agents = agents
    app.state.trusted_proxy_cidrs = parse_cidrs(settings.trusted_proxy_cidrs)
    app.state.allowed_client_cidrs = parse_cidrs(settings.allowed_client_cidrs)
    app.state.admin_client_cidrs = parse_cidrs(settings.admin_client_cidrs)
    app.mount("/static", StaticFiles(directory=str(APP_ROOT / "static")), name="static")

    @app.middleware("http")
    async def secure_headers(request: Request, call_next):
        # Public GitHub does not imply a publicly exposed server.
        if request.url.path != "/healthz":
            try:
                get_ip(request)
            except HTTPException as exc:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        # State-changing admin calls must originate from this exact origin.
        # Authenticated browser Basic credentials must not be sufficient for CSRF.
        if request.url.path.startswith('/api/admin/') and request.method in {'POST','PUT','PATCH','DELETE'}:
            site = request.headers.get('sec-fetch-site', '').lower()
            origin = request.headers.get('origin', '')
            if site not in {'', 'none', 'same-origin'}:
                return Response(status_code=403, content='Cross-site admin changes are not allowed')
            if origin:
                from urllib.parse import urlsplit
                try:
                    parsed = urlsplit(origin)
                    host = request.headers.get('host', '')
                    if (parsed.scheme not in {'https','http'} or
                        parsed.netloc.lower() != host.lower() or
                        (parsed.scheme != 'https' and secure_transport(request))):
                        return Response(status_code=403, content='Admin origin mismatch')
                except ValueError:
                    return Response(status_code=403, content='Invalid admin origin')
        # A cookie-authenticated admin action must also carry its session CSRF
        # token. Basic credentials from old browser caches are not accepted.
        if (request.url.path.startswith('/api/admin/') and
                request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and
                request.url.path != '/api/admin/login' and
                not (settings.allow_legacy_basic_api and request.headers.get('authorization', '').startswith('Basic '))):
            ip = get_ip(request)
            session = find_session(settings.db_path, request.cookies.get(COOKIE_NAME, ''),
                                   ip, settings.admin_password)
            csrf = request.headers.get('x-csrf-token', '')
            if not session:
                return Response(status_code=401, content='Admin login required')
            if not csrf or not secrets.compare_digest(csrf, session['csrf_token']):
                return Response(status_code=403, content='Admin CSRF/session token required')
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if secure_transport(request):
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def check_admin_network(request: Request) -> str:
        ip = get_ip(request)
        if not any(ipaddress.ip_address(ip) in net for net in app.state.admin_client_cidrs):
            raise HTTPException(403, "Admin interface is restricted to approved management networks")
        if settings.admin_require_https and not secure_transport(request):
            raise HTTPException(403, "Admin access requires HTTPS")
        return ip

    def admin_session(request: Request):
        ip = check_admin_network(request)
        return find_session(settings.db_path, request.cookies.get(COOKIE_NAME, ''),
                            ip, settings.admin_password)

    def legacy_basic_authorized(request: Request) -> bool:
        # Opt-in only for pre-existing CLI API integrations. Disabling this is
        # required for robust browser logout: Basic credentials are browser-cached.
        if not settings.allow_legacy_basic_api:
            return False
        authorization = request.headers.get('authorization', '')
        if not authorization.startswith('Basic '):
            return False
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode('utf-8')
            user, password = decoded.split(':', 1)
        except (ValueError, UnicodeError):
            return False
        return (secrets.compare_digest(user.encode(), settings.admin_username.encode()) and
                secrets.compare_digest(password.encode(), settings.admin_password.encode()))

    def require_admin(request: Request):
        if admin_session(request) is not None:
            return True
        check_admin_network(request)
        if legacy_basic_authorized(request):
            return True
        raise HTTPException(401, "Admin login required")

    def session_token(request: Request) -> tuple[str, str]:
        ip = get_ip(request)
        token = request.headers.get("x-speedtest-token", "")
        if not 30 <= len(token) <= 150:
            raise HTTPException(401, "Start a test session first")
        hashed = hashlib.sha256(token.encode()).hexdigest()
        if not valid_session(settings.db_path, hashed, ip):
            raise HTTPException(401, "Invalid, expired or completed session")
        return ip, hashed

    @app.get("/")
    def home():
        return FileResponse(APP_ROOT / "static" / "index.html")

    @app.get("/admin")
    def admin(request: Request):
        return FileResponse(APP_ROOT / "static" /
                            ("admin.html" if (admin_session(request) or legacy_basic_authorized(request)) else "login.html"))

    @app.post("/api/admin/login")
    def admin_login(request: Request, data: AdminLogin):
        ip = check_admin_network(request)
        if admin_blocked(settings.db_path, ip):
            raise HTTPException(429, "Too many failed admin logins", headers={"Retry-After": "900"})
        if not (secrets.compare_digest(data.username.encode(), settings.admin_username.encode()) and
                secrets.compare_digest(data.password.encode(), settings.admin_password.encode())):
            admin_failure(settings.db_path, ip)
            raise HTTPException(401, "Invalid username or password")
        admin_success(settings.db_path, ip)
        token, _ = new_admin_session(settings.db_path, ip, settings.admin_password)
        response = Response(status_code=204)
        response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS,
                            path="/", secure=True, httponly=True, samesite="strict")
        return response

    @app.get("/api/admin/session", dependencies=[Depends(require_admin)])
    def current_admin_session(request: Request):
        session = admin_session(request)
        return {"username": settings.admin_username, "csrf_token": session['csrf_token'],
                "expires_at": session['expires_at']}

    @app.post("/api/admin/logout", dependencies=[Depends(require_admin)])
    def admin_logout(request: Request):
        revoke_session(settings.db_path, request.cookies.get(COOKIE_NAME, ''))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get('/api/branding')
    def public_branding():
        return read_branding(settings.db_path)

    @app.get('/api/branding/logo')
    def public_logo():
        logo = read_logo(settings.db_path)
        if logo:
            return Response(logo, media_type='image/png', headers={'Content-Disposition':'inline'})
        return FileResponse(APP_ROOT / 'static' / 'gmcs-logo.png', media_type='image/png')

    @app.get('/api/admin/branding', dependencies=[Depends(require_admin)])
    def admin_branding():
        return read_branding(settings.db_path)

    @app.put('/api/admin/branding', dependencies=[Depends(require_admin)])
    def admin_update_branding(form: BrandingForm):
        fields = {k: v.strip() for k, v in form.model_dump().items()}
        if any(not v or any(ord(ch) < 32 or ord(ch) == 127 for ch in v) for v in fields.values()):
            raise HTTPException(422, 'Branding must contain printable, nonempty text only')
        return write_branding(settings.db_path, fields)

    @app.put('/api/admin/branding/logo', dependencies=[Depends(require_admin)])
    def admin_update_logo(form: BrandingLogo):
        try:
            store_logo(settings.db_path, form.png_data)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {'status':'saved', 'custom_logo':True}

    @app.delete('/api/admin/branding/logo', dependencies=[Depends(require_admin)])
    def admin_clear_logo():
        clear_logo(settings.db_path)
        return {'status':'restored','custom_logo':False}

    @app.get('/api/admin/diagnostics/egress', dependencies=[Depends(require_admin)])
    def admin_egress_history():
        return {'point': 'GMCS NOC speed-test VM → Cloudflare HTTPS',
                'samples': egress_history(settings.db_path)}

    @app.post('/api/admin/diagnostics/egress', dependencies=[Depends(require_admin)])
    def admin_run_egress(request: Request):
        # This runs from the VM, not the end user's browser or each school's WAN path.
        result = run_external(settings.db_path, get_ip(request))
        if result['status'] == 'cooldown':
            raise HTTPException(429, 'A district egress test ran recently. Retry after '+
                                str(result['retry_after_seconds'])+' seconds')
        return result

    @app.get('/api/admin/router-hourly', dependencies=[Depends(require_admin)])
    def admin_hourly_routers():
        return {'sites': latest_routers(settings.db_path),
                'windows':['6h','day','week','month','year','2years']}

    @app.get('/api/admin/router-hourly/{site}', dependencies=[Depends(require_admin)])
    def admin_hourly_graph(site: str, window: str = 'day'):
        try:
            return router_trend(settings.db_path, site.upper(), window)
        except ValueError:
            raise HTTPException(400, 'Invalid school code or chart window')

    @app.get('/api/admin/school-agents', dependencies=[Depends(require_admin)])
    def admin_school_agents():
        return {'agents': listed_school_agents(settings.db_path, list(app.state.agents.rows)),
                'windows': list(GRAPH_WINDOWS)}

    @app.get('/api/admin/school-agents/{agent_id}', dependencies=[Depends(require_admin)])
    def admin_school_agent_graph(agent_id: str, window: str = 'day'):
        if agent_id not in app.state.agents.rows:
            raise HTTPException(404, 'Agent not registered')
        try:
            return school_agent_graph(settings.db_path, agent_id, window)
        except ValueError:
            raise HTTPException(400, 'Invalid agent ID or chart window')

    @app.get('/api/monitoring/school-agent/{agent_id}')
    def librenms_school_agent(agent_id: str, request: Request):
        # Separate read-only monitoring credential; school agents NEVER see it.
        import hmac
        if not secure_transport(request):
            raise HTTPException(403, 'HTTPS required')
        get_ip(request)
        p = Path(settings.db_path).parent / 'gmcs-monitoring.token'
        try:
            expected=p.read_text(encoding='utf-8').strip()
        except OSError:
            raise HTTPException(503, 'Monitoring integration not configured')
        header=request.headers.get('authorization','')
        provided=header[7:] if header.startswith('Bearer ') else ''
        if len(expected)<32 or not hmac.compare_digest(expected,provided):
            raise HTTPException(401, 'Monitoring token required')
        if not AGENT_ID_RE.fullmatch(agent_id):
            raise HTTPException(400, 'Invalid agent ID')
        if agent_id not in app.state.agents.rows:
            raise HTTPException(404, 'Unregistered agent')
        data=recent_school_agent(settings.db_path,agent_id)
        if data is None:
            raise HTTPException(404, 'No measurement yet')
        # Deliberately omit hostname and private IP from the read-only metrics API.
        return {'agent_id':agent_id,'at':data['completed_at'], 'status':data['status'],
                'school':data['school'], 'down_mbps':data['download_mbps'],
                'up_mbps':data['upload_mbps'],'latency_ms':data['latency_ms'],
                'jitter_ms':data['jitter_ms'],'loss_pct':data['packet_loss_pct']}

    @app.get('/api/monitoring/router-hourly/{site}')
    def librenms_site(site: str, request: Request):
        # Monitoring access is disabled until an operator provisions a secret in
        # the persistent private /data volume. Never disclose the credential.
        import hmac
        p = Path(settings.db_path).parent / 'gmcs-monitoring.token'
        if not secure_transport(request):
            raise HTTPException(403, 'HTTPS required')
        get_ip(request)
        try:
            expected = p.read_text(encoding='utf-8').strip()
        except OSError:
            raise HTTPException(503, 'Monitoring integration not configured')
        token = request.headers.get('authorization', '')
        supplied = token.removeprefix('Bearer ') if token.startswith('Bearer ') else ''
        if len(expected) < 32 or not hmac.compare_digest(expected, supplied):
            raise HTTPException(401, 'Monitoring token required')
        try:
            data = latest_site(settings.db_path, site.upper())
        except ValueError:
            raise HTTPException(400, 'Invalid school code')
        if data is None:
            raise HTTPException(404, 'No school-router sample recorded')
        return {'site': data['site'], 'at':data['at'], 'status':data['status'],
                'down_mbps':data['down_mbps'], 'up_mbps':data['up_mbps'],
                'latency_ms':data['latency_ms'], 'ping_loss':data['ping_loss'],
                'cap_mbps':data['cap_mbps']}

    @app.get("/api/identity")
    def identity(request: Request):
        ip = get_ip(request)
        return {"client_ip": ip, **app.state.mapping.lookup(ip)}

    @app.get("/api/ping")
    def ping(request: Request):
        session_token(request)
        return Response(status_code=204)

    @app.get("/api/download")
    def download(request: Request, bytes: int = Query(default=8_388_608, ge=1, le=33_554_432)):
        ip, hashed = session_token(request)
        if not reserve_transfer(settings.db_path, hashed, ip, bytes, "download", settings.max_session_mib * 1048576,
                                settings.max_download_mib * 1048576):
            raise HTTPException(429, "Session transfer allowance exhausted")

        def payload():
            remaining = bytes
            while remaining:
                n = min(remaining, len(CHUNK))
                yield CHUNK[:n]
                remaining -= n

        return StreamingResponse(payload(), media_type="application/octet-stream",
                                 headers={"Content-Length": str(bytes), "Content-Encoding": "identity", "X-Accel-Buffering": "no"})

    @app.post("/api/upload")
    async def upload(request: Request):
        ip, hashed = session_token(request)
        # Require Content-Length to reserve credit before accepting any body.
        try:
            size = int(request.headers.get("content-length", ""))
        except ValueError:
            raise HTTPException(411, "Content-Length required")
        if size <= 0 or size > 8_388_608:
            raise HTTPException(413, "Upload chunk must be 1 to 8 MiB")
        if not reserve_transfer(settings.db_path, hashed, ip, size, "upload", settings.max_session_mib * 1048576,
                                settings.max_upload_mib * 1048576):
            raise HTTPException(429, "Session transfer allowance exhausted")
        total = 0
        async for part in request.stream():
            total += len(part)
            if total > size:
                raise HTTPException(413, "Upload exceeds declared Content-Length")
        if total != size:
            raise HTTPException(400, "Upload length mismatch")
        return {"bytes_received": total}

    @app.post("/api/session")
    def new_session(request: Request):
        ip = get_ip(request)
        agent_id = request.headers.get("x-agent-id", "")
        agent_key = request.headers.get("x-agent-key", "")
        if agent_id or agent_key:
            if (not AGENT_ID_RE.fullmatch(agent_id) or
                (settings.agent_require_https and not secure_transport(request)) or
                    not app.state.agents.authenticate(agent_id, agent_key, ip)):
                raise HTTPException(401, "Invalid automated agent credentials or transport")
        token = secrets.token_urlsafe(32)
        hashed = hashlib.sha256(token.encode()).hexdigest()
        source_group = notification_group(app.state.mapping.lookup(ip), ip)
        outcome = create_session(settings.db_path, hashed, ip, settings.cooldown_seconds,
                                 settings.max_sessions_per_hour, agent_id=agent_id,
                                 group_key=source_group, max_active=settings.max_active_tests,
                                 max_group_active=settings.max_active_per_vlan)
        if outcome != "created":
            if outcome == "busy":
                raise HTTPException(429, "The speed-test server is busy. Please retry shortly.",
                                    headers={"Retry-After": "10"})
            raise HTTPException(429, "Test cooldown reached. Try again later.",
                                headers={"Retry-After": str(settings.cooldown_seconds)})
        return {"token": token, "identity": {"client_ip": ip, **app.state.mapping.lookup(ip)},
                "agent_id": agent_id}

    @app.post("/api/results")
    def result(request: Request, data: Report, bg: BackgroundTasks):
        ip = get_ip(request)
        record = {**data.model_dump(exclude={"token", "browser_diagnostics"}), "client_ip": ip, **app.state.mapping.lookup(ip)}
        hashed = hashlib.sha256(data.token.encode()).hexdigest()
        saved = save_result(settings.db_path, hashed, ip, record)
        if saved is None:
            raise HTTPException(400, "Invalid, expired, already used, or inconsistent test session")
        result_id, agent_id = saved
        # Browser metadata is bounded and does not include MAC, hostname or
        # hardware identifiers. Native diagnostics need separate user consent.
        record_browser(settings.db_path, result_id, data.token, ip,
                       data.browser_diagnostics.model_dump(exclude_none=True)
                       if data.browser_diagnostics and not agent_id else {})
        record["agent_id"] = agent_id
        mail_settings = load_smtp(managed['smtp'], settings)
        should_email = mail_settings.email_agent_results if agent_id else mail_settings.email_browser_results
        smtp_ready = bool(mail_settings.smtp_host and mail_settings.smtp_to and mail_settings.smtp_from)
        email_status = "disabled"
        if should_email and smtp_ready:
            group = notification_group(record, ip)
            if claim_notification(settings.db_path, group, result_id, mail_settings.email_dedupe_seconds):
                bg.add_task(send_result, mail_settings, result_id, record)
                email_status = "queued"
            else:
                email_status = "suppressed"
        else:
            set_email_status(settings.db_path, result_id, "disabled")
        return {"result_id": result_id, "school": record["school"], "vlan": record["vlan"],
                "agent_id": agent_id, "email_notification": email_status,
                "client_email_available": bool(smtp_ready and not agent_id),
                "client_email_already_notified": email_status in {'queued', 'sent'}}

    @app.post("/api/results/{result_id}/email")
    def request_client_email(result_id: int, data: ClientEmailRequest, request: Request, bg: BackgroundTasks):
        if result_id < 1 or not secure_transport(request):
            raise HTTPException(403, "A completed result and HTTPS are required")
        current = load_smtp(managed['smtp'], settings)
        if not (current.smtp_host and current.smtp_to and current.smtp_from):
            raise HTTPException(503, "Admin email delivery is not configured")
        try:
            record = claim_email(settings.db_path, result_id, data.token, get_ip(request))
        except EmailClaimError as exc:
            raise HTTPException(exc.status_code, exc.message)
        bg.add_task(send_client_result, current, result_id, record)
        return {"status": "queued", "message": "Your result was queued for the configured administrators"}

    @app.post('/api/results/{result_id}/diagnostics/advanced')
    def upload_client_diagnostics(result_id: int, data: AdvancedDiagnostics, request: Request):
        if result_id < 1 or not secure_transport(request):
            raise HTTPException(403, 'HTTPS and a completed speed test are required')
        report = data.model_dump(exclude={'token'})
        try:
            validate_advanced(report)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not submit_advanced(settings.db_path, result_id, data.token, get_ip(request), report):
            raise HTTPException(403, 'Report expired, already submitted, or not your test')
        return {'status':'saved','message':'Reviewed diagnostics attached to this result for GMCS administrators'}

    @app.post('/api/results/{result_id}/diagnostics/pair')
    def create_diagnostic_pair(result_id: int, data: ClientEmailRequest, request: Request):
        if result_id < 1 or not secure_transport(request):
            raise HTTPException(403, 'HTTPS and a completed speed test are required')
        pair = issue_upload_code(settings.db_path, result_id, data.token, get_ip(request))
        if pair is None:
            raise HTTPException(403, 'Only the original test device can request an upload code')
        return pair

    @app.post('/api/diagnostics/submit-pair')
    def upload_paired_diagnostics(data: PairedDiagnostics, request: Request):
        if not secure_transport(request):
            raise HTTPException(403, 'HTTPS is required')
        try:
            result_id = submit_paired(settings.db_path, data.upload_code, get_ip(request),
                                      data.model_dump(exclude={'upload_code'}))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if result_id is None:
            raise HTTPException(403, 'Code expired, already used, or source IP differs from speed test')
        return {'status':'saved', 'result_id':result_id}

    @app.get('/api/admin/results/{result_id}/diagnostics', dependencies=[Depends(require_admin)])
    def admin_result_diagnostics(result_id: int):
        if result_id < 1:
            raise HTTPException(404, 'Unknown result')
        report = fetch_report(settings.db_path, result_id)
        if report is None:
            raise HTTPException(404, 'Unknown result')
        return report

    @app.get("/api/admin/config/smtp", dependencies=[Depends(require_admin)])
    def get_smtp_config():
        return smtp_public_config(managed['smtp'], settings)

    @app.put("/api/admin/config/smtp", dependencies=[Depends(require_admin)])
    def update_smtp_config(form: SMTPForm):
        return save_smtp(managed['smtp'], form, settings)

    @app.post("/api/admin/config/smtp/test", dependencies=[Depends(require_admin)])
    def test_smtp_config():
        # Explicit, rate-limited test email to preconfigured admins, never arbitrary recipients.
        from .emailer import send_test_message
        from .database import allow_smtp_probe
        current = load_smtp(managed['smtp'], settings)
        if not (current.smtp_host and current.smtp_from and current.smtp_to):
            raise HTTPException(400, 'Configure SMTP sender, server and recipients first')
        if not allow_smtp_probe(settings.db_path):
            raise HTTPException(429, 'SMTP test limited to once every 5 minutes')
        try:
            send_test_message(current)
        except Exception:
            log.warning('Admin SMTP test failed', exc_info=True)
            raise HTTPException(502, 'SMTP relay rejected the test; inspect server logs')
        return {'status': 'sent_to_relay', 'message': 'Relay accepted SMTP test; verify it arrived in the admin inbox.'}

    @app.get("/api/admin/config/networks", dependencies=[Depends(require_admin)])
    def get_network_config():
        data = managed['mappings'].read_text(encoding='utf-8')
        return {'csv_text': data, 'count': len(app.state.mapping.entries)}

    @app.put("/api/admin/config/networks", dependencies=[Depends(require_admin)])
    def update_network_config(form: CSVForm):
        try:
            new_mapping = put_mappings(managed['mappings'], form.csv_text)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc))
        app.state.mapping = new_mapping
        return {'status': 'saved', 'count': len(new_mapping.entries)}

    @app.get("/api/admin/config/lookup", dependencies=[Depends(require_admin)])
    def lookup_configured_ip(ip: str = Query(min_length=3, max_length=45)):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            raise HTTPException(422, "Enter a valid IPv4 or IPv6 client address")
        if addr.is_global or addr.is_multicast or addr.is_unspecified:
            raise HTTPException(422, "Lookup only internal network addresses")
        return {"client_ip": str(addr), **app.state.mapping.lookup(str(addr))}

    @app.get("/api/admin/config/networks.csv", dependencies=[Depends(require_admin)])
    def download_network_config():
        return Response(managed['mappings'].read_text(encoding='utf-8'), media_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="gmcs-private-networks.csv"'})

    @app.get("/api/admin/config/agents", dependencies=[Depends(require_admin)])
    def get_agent_config():
        return {'agents': list_agents(managed['agents'])}

    @app.post("/api/admin/config/agents", dependencies=[Depends(require_admin)])
    def create_agent_config(form: AgentForm):
        try:
            new_agents, key = put_agent(managed['agents'], form)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        app.state.agents = new_agents
        # Return the secret exactly once. Admin should save it to the chosen school machine.
        return {'agent_id': form.agent_id, 'allowed_cidr': form.allowed_cidr, 'one_time_token': key}

    @app.delete("/api/admin/config/agents/{agent_id}", dependencies=[Depends(require_admin)])
    def delete_agent_config(agent_id: str):
        if not AGENT_ID_RE.fullmatch(agent_id):
            raise HTTPException(422, 'Invalid agent ID')
        try:
            app.state.agents = remove_agent(managed['agents'], agent_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return {'status': 'revoked'}

    @app.get("/api/admin/results", dependencies=[Depends(require_admin)])
    def results(limit: int = Query(100, ge=1, le=500), school: str | None = None, vlan: str | None = None):
        sql = "SELECT * FROM results WHERE 1=1"
        args: list = []
        if school:
            sql += " AND school=?"
            args.append(school)
        if vlan:
            sql += " AND vlan=?"
            args.append(vlan)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with connect(settings.db_path) as con:
            return {"results": [dict(r) for r in con.execute(sql, args).fetchall()]}

    @app.get("/api/admin/summary", dependencies=[Depends(require_admin)])
    def summary():
        with connect(settings.db_path) as con:
            total = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
            sites = con.execute("""SELECT school, COUNT(*) AS tests, ROUND(AVG(download_mbps), 1) AS avg_down,
              ROUND(AVG(upload_mbps), 1) AS avg_up FROM results GROUP BY school ORDER BY tests DESC""").fetchall()
            emails = con.execute("SELECT email_status, COUNT(*) AS count FROM results GROUP BY email_status").fetchall()
        return {"total_tests": total, "schools": [dict(row) for row in sites], "emails": [dict(row) for row in emails]}

    @app.get("/api/admin/export.csv", dependencies=[Depends(require_admin)])
    def export_csv():
        with connect(settings.db_path) as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM results ORDER BY id DESC LIMIT 10000")]
        names = ["id", "completed_at", "client_ip", "school", "vlan", "network_label", "agent_id",
                 "download_mbps", "upload_mbps", "latency_ms", "jitter_ms", "packet_loss_pct",
                 "download_bytes", "upload_bytes", "email_status", "client_email_status"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=names)
        writer.writeheader()
        for row in rows:
            safe = {k: ("'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v)
                    for k, v in row.items()}
            writer.writerow(safe)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="inside-speed-test-results.csv"'})

    return app


app = create_app()
