"""Local web console: one page plus a small token-protected JSON API over a LiveHub."""
import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import threading
import weakref
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from obd_reader.hub import DEFAULT_PIDS, HubBusy, LiveHub
from obd_reader.live import LiveLimitError
from obd_reader.replay_run import MAX_FILE_BYTES, list_runs, load_run, read_run_file
from obd_reader.session import AdapterBusy, Config, NoAdapterError, Session
from obd_reader.simulator import SimPort
from obd_reader.stat_help import HELP, MODE06

MAX_BODY = 4096
_HOSTNAME = re.compile(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*")
MAX_UPLOAD = MAX_FILE_BYTES  # the replay upload route only
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_POST_ROUTES = ("/api/start", "/api/stop", "/api/save", "/api/sim", "/api/replay", "/api/replay/control")
_CSP_JSON = "default-src 'none'"
_SOURCES = ("examples", "mine")   # replay sources: the public example runs, and the user's own runs/


def default_examples_dir() -> Path | None:
    """examples/runs at the repo root when running from a checkout (a wheel does not ship it)."""
    d = Path(__file__).resolve().parents[2] / "examples" / "runs"
    return d if d.is_dir() else None


def _page_csp(page: bytes) -> str:
    """The page's one inline script is pinned by hash, so injected markup (an inline event
    handler, a second script) cannot run even if untrusted text ever reached the DOM."""
    script = re.search(rb"<script>(.*?)</script>", page, re.S)
    digest = base64.b64encode(hashlib.sha256(script.group(1)).digest()).decode() if script else ""
    return (f"default-src 'self'; script-src 'sha256-{digest}'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'")


def guess_lan_ip() -> str | None:
    """Best-effort address other devices can use (a UDP connect sends no packets)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


class ConsoleServer:
    def __init__(self, hub: LiveHub, *, host: str = "127.0.0.1", port: int = 0,
                 token: str | None = None, allow_lan: bool = False, allow_hosts=(), examples_dir=None,
                 scenarios=None):
        self.examples_dir = None if examples_dir is None else Path(examples_dir)
        self.scenarios: list[dict] = list(scenarios or [])
        self.public_hosts: set[str] = set()   # names a tunnel serves us under (https): the page is still bound to loopback
        for h in allow_hosts:
            if not isinstance(h, str) or not _HOSTNAME.fullmatch(h):
                raise ValueError(f"--allow-host needs a plain host name such as shadetree.example.com, got {h!r}")
            self.public_hosts.add(h.lower())
        if host not in _LOOPBACK and not allow_lan:
            raise ValueError("binding to a non-loopback address needs allow_lan=True (--allow-lan)")
        self.hub, self.token = hub, token or secrets.token_urlsafe(16)
        self.httpd = ThreadingHTTPServer((host, port), self._handler())
        self.host, self.port = self.httpd.server_address[0], self.httpd.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        if host not in _LOOPBACK:
            self.allowed_hosts.add(f"{host}:{self.port}")  # LAN: the user opens it by the address it is bound to
        self._wildcard = host in ("0.0.0.0", "::")
        self._page_bytes: bytes | None = None
        self._page_csp = ""
        self._thread: threading.Thread | None = None

    def _host_ok(self, hostport: str) -> bool:
        """Loopback names, the bound address, or (wildcard bind only) any IP literal on our port.
        An IP literal cannot be DNS-rebound, so it is safe to accept; a name is not."""
        if hostport in self.allowed_hosts or hostport.lower() in self.public_hosts:
            return True
        if not self._wildcard:
            return False
        host, _, port = hostport.rpartition(":")
        if not host or port != str(self.port):
            return False
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return False
        return True

    def _origin_ok(self, origin: str) -> bool:
        if origin.startswith("https://"):   # only a name we were told to serve, never an arbitrary https site
            return origin[len("https://"):].lower() in self.public_hosts
        if not origin.startswith("http://"):
            return False
        rest = origin[len("http://"):]
        return rest.lower() not in self.public_hosts and self._host_ok(rest)   # a public name is https only

    def _page(self) -> tuple[bytes, str]:
        if self._page_bytes is None:
            self._page_bytes = resources.files("obd_reader.web").joinpath("console.html").read_bytes()
            self._page_csp = _page_csp(self._page_bytes)
        return self._page_bytes, self._page_csp

    @property
    def url(self) -> str:
        return f"http://{'127.0.0.1' if self.host in ('0.0.0.0', '::') else self.host}:{self.port}/?t={self.token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            if self._thread is not None:
                self.httpd.shutdown()
        finally:
            self.httpd.server_close()

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "shadetree-console"
            sys_version = ""

            def log_message(self, *args):  # request lines carry the token: never log them
                pass

            # ---- plumbing ----
            def _send(self, status: int, body: bytes, ctype: str, csp: str = _CSP_JSON) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", csp)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, obj: dict) -> None:
                self._send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

            def _guard(self, post: bool) -> tuple[bool, dict]:
                if not outer._host_ok(self.headers.get("Host", "")):
                    self._json(403, {"error": "forbidden"})
                    return False, {}
                if post:
                    origin = self.headers.get("Origin")
                    if origin is not None and not outer._origin_ok(origin):
                        self._json(403, {"error": "forbidden"})
                        return False, {}
                q = parse_qs(urlparse(self.path).query)
                supplied = (q.get("t") or [self.headers.get("X-Console-Token", "")])[0]
                if not hmac.compare_digest(supplied.encode(), outer.token.encode()):
                    self._json(401, {"error": "unauthorized"})
                    return False, {}
                return True, q

            def _body(self, limit: int = MAX_BODY) -> dict | None:
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    self._json(415, {"error": "send application/json"})
                    return None
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = -1
                if n < 0 or n > limit:
                    self._json(413, {"error": "body too large"})
                    return None
                try:
                    data = json.loads(self.rfile.read(n) or b"{}")
                except (ValueError, RecursionError):
                    self._json(400, {"error": "body is not valid JSON"})
                    return None
                if not isinstance(data, dict):
                    self._json(400, {"error": "body must be a JSON object"})
                    return None
                return data

            # ---- routes ----
            def do_GET(self):
                path = urlparse(self.path).path
                if path not in ("/", "/api/state", "/api/help", "/api/runs", "/api/scenarios"):
                    if path in _POST_ROUTES:
                        return self._json(405, {"error": "use POST"})
                    return self._json(404, {"error": "not found"})
                ok, q = self._guard(post=False)
                if not ok:
                    return
                if path == "/":
                    html, csp = outer._page()
                    return self._send(200, html, "text/html; charset=utf-8", csp)
                if path == "/api/help":
                    return self._json(200, {"pids": HELP, "mode06": MODE06})
                if path == "/api/scenarios":
                    return self._json(200, {"scenarios": outer.scenarios})
                if path == "/api/runs":
                    ex = outer.examples_dir
                    return self._json(200, {"runs": list_runs(outer.hub.runs_dir), "examples": list_runs(ex) if ex else []})
                try:
                    after = max(0, int((q.get("after") or ["0"])[0]))
                except ValueError:
                    return self._json(400, {"error": "after must be an integer"})
                self._json(200, outer.hub.state(after))

            def do_POST(self):
                path = urlparse(self.path).path
                if path not in _POST_ROUTES:
                    if path in ("/", "/api/state", "/api/help", "/api/runs", "/api/scenarios"):
                        return self._json(405, {"error": "use GET"})
                    return self._json(404, {"error": "not found"})
                ok, _ = self._guard(post=True)
                if not ok:
                    return
                body = self._body(MAX_UPLOAD if path == "/api/replay" else MAX_BODY)
                if body is None:
                    return
                try:
                    if path == "/api/start":
                        outer.hub.start(body.get("pids"), hz=body.get("hz", 2.5), seconds=body.get("seconds", 600.0),
                                        capture=body.get("capture", "default"))
                        return self._json(200, {"ok": True})
                    if path == "/api/stop":
                        outer.hub.stop()
                        return self._json(200, {"ok": True})
                    if path == "/api/save":
                        return self._json(200, {"ok": True, "path": str(outer.hub.save_run(str(body.get("label", "run"))))})
                    if path == "/api/replay":
                        if "run" in body:
                            label = body.get("name")
                            name = re.sub(r"[^A-Za-z0-9._ -]", "_", label)[:80] if isinstance(label, str) and label else "upload"
                            run = load_run(body["run"])
                        else:
                            source = body.get("source", "mine")
                            if not isinstance(source, str) or source not in _SOURCES:
                                raise ValueError("source must be examples or mine")
                            folder = outer.hub.runs_dir if source == "mine" else outer.examples_dir
                            if folder is None:
                                raise FileNotFoundError(source)
                            name = str(body.get("name", ""))
                            run = load_run(read_run_file(folder, name))
                        outer.hub.start_replay(run, name)
                        return self._json(200, {"ok": True})
                    if path == "/api/replay/control":
                        if body.get("action") == "exit":
                            outer.hub.exit_replay()
                        else:
                            outer.hub.replay_control(body.get("action"), pos=body.get("pos"), speed=body.get("speed"))
                        return self._json(200, {"ok": True})
                    outer.hub.set_sim(scenario=body.get("scenario"), rev=body.get("rev"))
                    return self._json(200, {"ok": True})
                except FileNotFoundError:
                    return self._json(404, {"error": "no such saved run"})
                except (HubBusy, AdapterBusy) as e:
                    return self._json(409, {"error": str(e)})
                except (LiveLimitError, ValueError, TypeError, NoAdapterError) as e:
                    return self._json(400, {"error": str(e)})

            def _not_allowed(self):
                self._json(405, {"error": "method not allowed"})

            do_PUT = do_DELETE = do_PATCH = _not_allowed

        return Handler


_services: "weakref.WeakSet[ConsoleService]" = weakref.WeakSet()


class ConsoleService:
    """Owns one hub and one server for a Session (or a private simulated one for --demo)."""

    def __init__(self, session: Session, *, demo: bool = False, host: str = "127.0.0.1",
                 http_port: int = 0, allow_lan: bool = False, scenario: str = "rich", allow_hosts=(), examples_dir=None,
                 scenarios=None):
        self._scenarios = scenarios
        self.demo, self._host, self._port, self._lan, self._scenario = demo, host, http_port, allow_lan, scenario
        self._examples = default_examples_dir() if examples_dir is None else Path(examples_dir)
        self._allow_hosts = tuple(allow_hosts)
        self._session = session
        self.hub: LiveHub | None = None
        self.server: ConsoleServer | None = None
        _services.add(self)

    def ensure(self) -> ConsoleServer:
        if self.server is not None:
            return self.server
        if self.demo:
            sim = SimPort(self._scenario)
            session = Session(Config(port="sim", home=self._session.config.home, timeout=1.0),
                              port_factory=lambda: sim)
            self.hub = LiveHub(session, sim=sim)
        else:
            if not self._session.config.port:
                raise NoAdapterError("SHADETREE_PORT is not set; use demo=True to try the console without a car")
            self.hub = LiveHub(self._session)
        self.server = ConsoleServer(self.hub, host=self._host, port=self._port, allow_lan=self._lan, allow_hosts=self._allow_hosts,
                                    examples_dir=self._examples, scenarios=self._scenarios)
        self.server.start()
        return self.server

    def start_sampling(self, pids: list[str] | None = None, hz: float = 2.5, seconds: float = 600.0) -> None:
        self.ensure()
        if not self.hub.running:
            self.hub.start(pids or DEFAULT_PIDS, hz=hz, seconds=seconds)

    def stop(self) -> None:
        if self.hub is not None:
            self.hub.stop()
        if self.server is not None:
            self.server.stop()
        self.hub = self.server = None

    @staticmethod
    def shutdown_all() -> None:
        for svc in list(_services):
            svc.stop()
