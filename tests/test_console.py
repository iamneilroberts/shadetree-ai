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


def _run_obj(n=10):
    ts = [round(0.4 * k, 3) for k in range(1, n + 1)]
    return {"kind": "live_run", "demo": False, "adapter": {"protocol": "ISO 15765-4 (CAN 29/500)"},
            "live_sample": {"duration_s": ts[-1], "rate_hz": 2.5, "series": {
                "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[t, 700 + i] for i, t in enumerate(ts)]}}}}


def test_runs_are_listed_and_loaded_by_name_and_controlled(srv):
    server, hub, _ = srv
    hub.runs_dir.mkdir()
    (hub.runs_dir / "a-run.json").write_text(json.dumps(_run_obj()))
    status, body = call(server, "GET", "/api/runs")
    assert status == 200 and [r["name"] for r in body["runs"]] == ["a-run.json"] and body["runs"][0]["duration"] == 4.0
    assert call(server, "POST", "/api/replay", {"name": "a-run.json"}) == (200, {"ok": True})
    st = call(server, "GET", "/api/state")[1]
    assert st["replay"]["name"] == "a-run.json" and st["status"] == "running"
    assert call(server, "POST", "/api/replay/control", {"action": "pause"})[0] == 200
    assert call(server, "POST", "/api/replay/control", {"action": "seek", "pos": 2})[0] == 200
    assert call(server, "GET", "/api/state")[1]["replay"]["pos"] == 2.0
    assert call(server, "POST", "/api/replay/control", {"action": "speed", "speed": 3})[0] == 400
    assert call(server, "POST", "/api/replay/control", {"action": "exit"})[0] == 200
    assert call(server, "GET", "/api/state")[1]["replay"] is None
    assert call(server, "POST", "/api/replay/control", {"action": "pause"})[0] == 400


def test_replay_names_and_files_are_validated(srv):
    server, hub, _ = srv
    hub.runs_dir.mkdir()
    (hub.runs_dir / "bad.json").write_text(json.dumps({"kind": "snapshot"}))
    (hub.runs_dir / "nan.json").write_text('{"kind": "live_run", "live_sample": {"series": {"0C": {"name": "x", "unit": null, "samples": [[1, NaN]]}}}}')
    for name in ("../x.json", "a/b.json", "x.txt", "", "bad.json", "nan.json"):
        assert call(server, "POST", "/api/replay", {"name": name})[0] == 400, name
    assert call(server, "POST", "/api/replay", {"name": "missing.json"})[0] == 404
    assert call(server, "GET", "/api/state")[1]["replay"] is None


def test_an_uploaded_run_is_replayed_from_memory_and_writes_nothing(srv):
    server, hub, _ = srv
    status, body = call(server, "POST", "/api/replay", {"run": _run_obj(), "name": "my<b>file.json"})
    assert (status, body) == (200, {"ok": True})
    st = call(server, "GET", "/api/state")[1]
    assert st["replay"]["name"] == "my_b_file.json", "the label is reduced to safe characters"
    assert not hub.runs_dir.exists()
    assert call(server, "POST", "/api/replay", {"run": {"kind": "live_run"}})[0] == 400
    assert call(server, "POST", "/api/replay", {"run": [1, 2]})[0] == 400


def test_the_upload_route_alone_accepts_a_large_body(srv, monkeypatch):
    server, _, _ = srv
    big = {"run": _run_obj(), "pad": "x" * 6000}
    assert call(server, "POST", "/api/replay", big)[0] == 200, "6 KB is over the 4 KB default and fine here"
    assert call(server, "POST", "/api/stop", {"pad": "x" * 6000})[0] == 413, "every other route keeps the small cap"
    monkeypatch.setattr("obd_reader.console.MAX_UPLOAD", 1000)
    assert call(server, "POST", "/api/replay", {"run": _run_obj(), "pad": "x" * 2000})[0] == 413


def test_replay_routes_need_the_token_and_the_origin_and_are_not_gettable(srv):
    server, hub, _ = srv
    hub.runs_dir.mkdir()
    (hub.runs_dir / "a-run.json").write_text(json.dumps(_run_obj()))
    assert call(server, "GET", "/api/runs", token=None)[0] == 401
    assert call(server, "POST", "/api/replay", {"name": "a-run.json"}, token=None)[0] == 401
    assert call(server, "POST", "/api/replay", {"name": "a-run.json"}, headers={"Origin": "http://evil.example"})[0] == 403
    assert call(server, "GET", "/api/replay")[0] == 405 and call(server, "GET", "/api/replay/control")[0] == 405
    assert call(server, "POST", "/api/runs", {})[0] == 405


def test_replay_and_live_sampling_refuse_each_other_over_http(srv):
    server, hub, _ = srv
    assert call(server, "POST", "/api/replay", {"run": _run_obj()})[0] == 200
    assert call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10})[0] == 409
    assert call(server, "POST", "/api/save", {"label": "x"})[0] == 400
    assert call(server, "POST", "/api/replay/control", {"action": "exit"})[0] == 200
    assert call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10})[0] == 200
    assert wait_seq(server, 2)
    assert call(server, "POST", "/api/replay", {"run": _run_obj()})[0] == 409


def test_deep_nesting_and_huge_numbers_get_a_400_not_a_dropped_connection(srv):
    server, _, _ = srv
    assert call(server, "POST", "/api/replay", raw='{"run": ' + "[" * 100000 + "]" * 100000 + "}")[0] == 400
    assert call(server, "POST", "/api/replay", {"run": _run_obj()})[0] == 200
    assert call(server, "POST", "/api/replay/control", raw='{"action": "seek", "pos": ' + "9" * 400 + "}")[0] == 400
    assert call(server, "GET", "/api/state")[1]["replay"]["name"] == "upload"


@pytest.fixture
def public_srv(tmp_path):
    sim = SimPort("rich")
    session = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(session, sim=sim)
    server = ConsoleServer(hub, token="tok123", allow_hosts=["Shadetree.Voygent.ai"])
    server.start()
    yield server
    hub.stop()
    server.stop()


def test_a_named_public_host_needs_its_name_https_origin_and_the_token(public_srv):
    s, name = public_srv, "shadetree.voygent.ai"
    assert call(s, "GET", "/api/state", host=name)[0] == 200
    assert call(s, "GET", "/api/state", host=name, token="wrong")[0] == 401
    assert call(s, "GET", "/api/state", host=name, token=None)[0] == 401
    assert call(s, "POST", "/api/stop", {}, host=name, headers={"Origin": f"https://{name}"})[0] == 200
    for origin in (f"http://{name}", "https://evil.example", f"https://{name}.evil.example", f"https://evil.example/{name}"):
        assert call(s, "POST", "/api/stop", {}, host=name, headers={"Origin": origin})[0] == 403, origin
    for host in ("evil.example", f"{name}.evil.example", f"{name}:8443", "voygent.ai"):
        assert call(s, "GET", "/api/state", host=host)[0] == 403, host
    assert call(s, "GET", "/api/state", host=f"localhost:{s.port}")[0] == 200, "loopback still works"
    assert call(s, "POST", "/api/stop", {}, host=f"localhost:{s.port}", headers={"Origin": f"http://localhost:{s.port}"})[0] == 200


def test_an_https_origin_is_refused_when_no_public_host_was_allowed(srv):
    server, _, _ = srv
    assert call(server, "POST", "/api/stop", {}, headers={"Origin": f"https://127.0.0.1:{server.port}"})[0] == 403
    assert call(server, "GET", "/api/state", host="shadetree.voygent.ai")[0] == 403


@pytest.mark.parametrize("bad", ["", "a b", "x/y", "https://a.b", "a.b:443", "-bad.com", "bad-.com", "a..b", "x" * 254, "über.example", "*.voygent.ai", 5, None])
def test_bad_allow_host_values_are_refused_before_any_socket_opens(tmp_path, bad):
    session = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: SimPort("rich"))
    with pytest.raises(ValueError):
        ConsoleServer(LiveHub(session), allow_hosts=[bad])


def test_allow_host_reaches_the_server_from_the_command_line(tmp_path):
    from obd_reader.__main__ import build_parser, console_main
    args = build_parser().parse_args(["console", "--demo", "--http-port", "0", "--no-start", "--out-dir", str(tmp_path),
                                      "--allow-host", "a.example.com", "--allow-host", "B.example.com"])
    assert args.allow_host == ["a.example.com", "B.example.com"]
    svc = console_main(args, block=False)
    try:
        assert svc.server.public_hosts == {"a.example.com", "b.example.com"}
        assert call(svc.server, "GET", "/api/state", host="b.example.com", token=svc.server.token)[0] == 200
    finally:
        svc.stop()
