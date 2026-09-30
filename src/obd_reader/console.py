"""Local web console: one page plus a small token-protected JSON API over a LiveHub."""
import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from obd_reader.hub import HubBusy, LiveHub
from obd_reader.live import LiveLimitError
from obd_reader.session import AdapterBusy, NoAdapterError

MAX_BODY = 4096
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_POST_ROUTES = ("/api/start", "/api/stop", "/api/save", "/api/sim")
_CSP = ("default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'")


class ConsoleServer:
    def __init__(self, hub: LiveHub, *, host: str = "127.0.0.1", port: int = 0,
                 token: str | None = None, allow_lan: bool = False):
        if host not in _LOOPBACK and not allow_lan:
            raise ValueError("binding to a non-loopback address needs allow_lan=True (--allow-lan)")
        self.hub, self.token = hub, token or secrets.token_urlsafe(16)
        self.httpd = ThreadingHTTPServer((host, port), self._handler())
        self.host, self.port = self.httpd.server_address[0], self.httpd.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        if host not in _LOOPBACK:
            self.allowed_hosts.add(f"{host}:{self.port}")  # LAN: the user opens it by the address it is bound to
        self._thread: threading.Thread | None = None

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
            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", _CSP)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, obj: dict) -> None:
                self._send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

            def _guard(self, post: bool) -> tuple[bool, dict]:
                if self.headers.get("Host", "") not in outer.allowed_hosts:
                    self._json(403, {"error": "forbidden"})
                    return False, {}
                if post:
                    origin = self.headers.get("Origin")
                    if origin is not None and origin not in {f"http://{h}" for h in outer.allowed_hosts}:
                        self._json(403, {"error": "forbidden"})
                        return False, {}
                q = parse_qs(urlparse(self.path).query)
                supplied = (q.get("t") or [self.headers.get("X-Console-Token", "")])[0]
                if not hmac.compare_digest(supplied.encode(), outer.token.encode()):
                    self._json(401, {"error": "unauthorized"})
                    return False, {}
                return True, q

            def _body(self) -> dict | None:
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    self._json(415, {"error": "send application/json"})
                    return None
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = -1
                if n < 0 or n > MAX_BODY:
                    self._json(413, {"error": "body too large"})
                    return None
                try:
                    data = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    self._json(400, {"error": "body is not valid JSON"})
                    return None
                if not isinstance(data, dict):
                    self._json(400, {"error": "body must be a JSON object"})
                    return None
                return data

            # ---- routes ----
            def do_GET(self):
                path = urlparse(self.path).path
                if path not in ("/", "/api/state"):
                    if path in _POST_ROUTES:
                        return self._json(405, {"error": "use POST"})
                    return self._json(404, {"error": "not found"})
                ok, q = self._guard(post=False)
                if not ok:
                    return
                if path == "/":
                    html = resources.files("obd_reader.web").joinpath("console.html").read_bytes()
                    return self._send(200, html, "text/html; charset=utf-8")
                try:
                    after = max(0, int((q.get("after") or ["0"])[0]))
                except ValueError:
                    return self._json(400, {"error": "after must be an integer"})
                self._json(200, outer.hub.state(after))

            def do_POST(self):
                path = urlparse(self.path).path
                if path not in _POST_ROUTES:
                    if path in ("/", "/api/state"):
                        return self._json(405, {"error": "use GET"})
                    return self._json(404, {"error": "not found"})
                ok, _ = self._guard(post=True)
                if not ok:
                    return
                body = self._body()
                if body is None:
                    return
                try:
                    if path == "/api/start":
                        outer.hub.start(body.get("pids"), hz=body.get("hz", 2.5), seconds=body.get("seconds", 600.0))
                        return self._json(200, {"ok": True})
                    if path == "/api/stop":
                        outer.hub.stop()
                        return self._json(200, {"ok": True})
                    if path == "/api/save":
                        return self._json(200, {"ok": True, "path": str(outer.hub.save_run(str(body.get("label", "run"))))})
                    outer.hub.set_sim(scenario=body.get("scenario"), rev=body.get("rev"))
                    return self._json(200, {"ok": True})
                except (HubBusy, AdapterBusy) as e:
                    return self._json(409, {"error": str(e)})
                except (LiveLimitError, ValueError, TypeError, NoAdapterError) as e:
                    return self._json(400, {"error": str(e)})

            def _not_allowed(self):
                self._json(405, {"error": "method not allowed"})

            do_PUT = do_DELETE = do_PATCH = _not_allowed

        return Handler
