import http.client
import json
import time

import pytest

from obd_reader.console import ConsoleServer
from obd_reader.hub import DEFAULT_PIDS, LiveHub
from obd_reader.session import Config, Session
from obd_reader.simulator import SimPort

from conftest import ScriptedPort


@pytest.fixture
def srv(tmp_path):
    sim = SimPort("rich")
    session = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(session, sim=sim)
    server = ConsoleServer(hub, token="tok123")
    server.start()
    yield server, hub, session
    hub.stop()
    server.stop()


def call(server, method, path, body=None, headers=None, token="tok123", host=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    sep = "&" if "?" in path else "?"
    url = path + (f"{sep}t={token}" if token is not None else "")
    h = {"Host": host or f"127.0.0.1:{server.port}"}
    h.update(headers or {})
    payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
    if payload is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    c.request(method, url, body=payload, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, data.decode("utf-8", "replace")


def wait_seq(server, n):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if call(server, "GET", "/api/state")[1]["seq"] >= n:
            return True
        time.sleep(0.03)
    return False


def test_page_and_state_need_the_token(srv):  # Review Focus 1
    server, _, _ = srv
    assert call(server, "GET", "/", token=None)[0] == 401
    assert call(server, "GET", "/api/state", token="wrong")[0] == 401
    status, body = call(server, "GET", "/api/state", token=None)
    assert status == 401 and "channels" not in json.dumps(body)  # a refusal leaks nothing
    assert call(server, "GET", "/")[0] == 200
    assert call(server, "GET", "/api/state", token=None, headers={"X-Console-Token": "tok123"})[0] == 200


def test_wrong_host_header_is_refused(srv):  # Review Focus 1 (DNS rebinding)
    server, _, _ = srv
    for host in ("evil.example", "evil.example:80", f"attacker.test:{server.port}", "127.0.0.1"):
        assert call(server, "GET", "/api/state", host=host)[0] == 403, host
    assert call(server, "GET", "/api/state", host=f"localhost:{server.port}")[0] == 200


def test_foreign_origin_on_post_is_refused(srv):  # Review Focus 1 (CSRF)
    server, hub, _ = srv
    st, _ = call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS}, headers={"Origin": "http://evil.example"})
    assert st == 403 and not hub.running
    own = f"http://127.0.0.1:{server.port}"
    assert call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10}, headers={"Origin": own})[0] == 200


def test_start_stop_and_state_flow(srv):
    server, hub, _ = srv
    assert call(server, "GET", "/api/state")[1]["status"] == "idle"
    st, body = call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10, "seconds": 30})
    assert st == 200 and body["ok"] is True
    assert wait_seq(server, 4)
    state = call(server, "GET", "/api/state?after=0")[1]
    assert state["status"] == "running" and state["demo"] is True and state["channels"]["0C"]["samples"]
    assert call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS})[0] == 409  # already sampling
    assert call(server, "POST", "/api/stop", {})[0] == 200
    assert call(server, "GET", "/api/state")[1]["status"] == "stopped"


@pytest.mark.parametrize("body", [
    {"pids": ["0C\r04"]}, {"pids": ["ZZ"]}, {"pids": [f"{i:02X}" for i in range(9)]}, {"pids": []},
    {"pids": ["0C"], "hz": 0}, {"pids": ["0C"], "hz": 1e-9}, {"pids": ["0C"], "seconds": 99999},
    {"pids": ["0C"], "hz": "fast"}, {"pids": "0C"}, {"pids": [None]}, {},
])
def test_bad_start_requests_are_400_and_nothing_starts(srv, body):  # Review Focus 2
    server, hub, _ = srv
    assert call(server, "POST", "/api/start", body)[0] == 400
    assert not hub.running and hub.state()["status"] == "idle"


def test_body_and_content_type_rules(srv):  # Review Focus 2
    server, hub, _ = srv
    assert call(server, "POST", "/api/start", raw="x" * 5000)[0] == 413
    assert call(server, "POST", "/api/start", raw="{not json")[0] == 400
    assert call(server, "POST", "/api/start", raw="[1,2]")[0] == 400
    assert call(server, "POST", "/api/start", raw="{}", headers={"Content-Type": "text/plain"})[0] == 415
    assert not hub.running


def test_routes_and_methods(srv):
    server, _, _ = srv
    assert call(server, "GET", "/nope")[0] == 404
    assert call(server, "GET", "/api/start")[0] == 405
    assert call(server, "POST", "/api/state", {})[0] == 405
    assert call(server, "DELETE", "/api/state")[0] == 405
    assert call(server, "GET", "/..%2f..%2fetc/passwd")[0] == 404


def test_save_and_sim_endpoints(srv, tmp_path):
    server, hub, _ = srv
    assert call(server, "POST", "/api/save", {"label": "early"})[0] == 400  # nothing sampled
    call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10, "seconds": 30})
    assert wait_seq(server, 3)
    call(server, "POST", "/api/stop", {})
    st, body = call(server, "POST", "/api/save", {"label": "bench"})
    assert st == 200 and body["path"].endswith("-bench.json")
    assert call(server, "POST", "/api/save", {"label": "../x"})[0] == 400
    assert call(server, "POST", "/api/sim", {"scenario": "lean", "rev": True})[0] == 200
    assert call(server, "POST", "/api/sim", {"scenario": "bogus"})[0] == 400


def test_sim_is_refused_when_not_in_demo(tmp_path):
    session = Session(Config(port="x", home=tmp_path), port_factory=lambda: ScriptedPort({}))
    server = ConsoleServer(LiveHub(session), token="tok123")
    server.start()
    try:
        assert call(server, "POST", "/api/sim", {"rev": True})[0] == 400
    finally:
        server.stop()


def test_a_second_tool_using_the_adapter_does_not_crash_the_server(srv):
    server, hub, session = srv
    with session.connection("holder"):
        st, body = call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10})
    assert st in (200, 409)  # the hub thread reports the lock error as status "error", not a crash
    time.sleep(0.3)
    hub.stop()
    assert call(server, "GET", "/api/state")[0] == 200


def test_binding_off_loopback_needs_the_explicit_flag(tmp_path):
    session = Session(Config(port="x", home=tmp_path), port_factory=lambda: ScriptedPort({}))
    with pytest.raises(ValueError):
        ConsoleServer(LiveHub(session), host="0.0.0.0")
    ConsoleServer(LiveHub(session), host="0.0.0.0", allow_lan=True).stop()


def test_security_headers_and_no_cors(srv):
    server, _, _ = srv
    c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    c.request("GET", "/?t=tok123", headers={"Host": f"127.0.0.1:{server.port}"})
    r = c.getresponse()
    r.read()
    hdr = {k.lower(): v for k, v in r.getheaders()}
    assert hdr["cache-control"] == "no-store" and hdr["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in hdr["content-security-policy"]
    assert not any(k.startswith("access-control-") for k in hdr)
    c.close()


def test_help_needs_the_token_and_is_get_only(srv):
    server, _, _ = srv
    assert call(server, "GET", "/api/help", token=None)[0] == 401
    assert call(server, "GET", "/api/help", host="evil.example")[0] == 403
    status, body = call(server, "GET", "/api/help")
    assert status == 200 and "06" in body["pids"] and "evap" in body["mode06"]
    assert call(server, "POST", "/api/help", {})[0] == 405


def test_help_carries_no_vin_shaped_text(srv):
    import re
    text = json.dumps(call(srv[0], "GET", "/api/help")[1])
    assert not re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", text)
