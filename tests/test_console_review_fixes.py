"""Regression tests for the findings of the live-console whole-branch review."""
import base64
import hashlib
import http.client
import json
import re
import time
from collections import deque

import pytest

from obd_reader.console import ConsoleServer, ConsoleService
from obd_reader.hub import DEFAULT_PIDS, LiveHub
from obd_reader.session import Config, Session
from obd_reader.simulator import SimPort
from obd_reader.tools import build_tools

from conftest import ScriptedPort


def make_hub(tmp_path, port_factory=None, sim=None):
    sim = sim or SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=port_factory or (lambda: sim))
    return LiveHub(s, sim=sim), s, sim


def request(server, method, path, host=None, headers=None, body=None, token="tok123"):
    c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{server.port}"}
    h.update(headers or {})
    payload = json.dumps(body) if body is not None else None
    if payload is not None:
        h.setdefault("Content-Type", "application/json")
    c.request(method, f"{path}{'&' if '?' in path else '?'}t={token}", body=payload, headers=h)
    r = c.getresponse()
    data = r.read()
    hdr = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, data, hdr


@pytest.fixture
def srv(tmp_path):
    hub, session, sim = make_hub(tmp_path)
    server = ConsoleServer(hub, token="tok123")
    server.start()
    yield server, hub, session
    hub.stop()
    server.stop()


# ---- Important 1: adapter text must never become markup or script ---------------------------------

def test_csp_pins_the_inline_script_by_hash_and_drops_unsafe_inline_for_scripts(srv):
    server, _, _ = srv
    status, page, hdr = request(server, "GET", "/")
    assert status == 200
    script = re.search(rb"<script>(.*?)</script>", page, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(script).digest()).decode()
    csp = hdr["content-security-policy"]
    assert f"'sha256-{digest}'" in csp
    assert not re.search(r"script-src[^;]*'unsafe-inline'", csp)
    assert "default-src 'self'" in csp and "object-src 'none'" in csp


# ---- Important 2: only whole sweeps are ever published ---------------------------------------------

def test_state_never_returns_a_partially_written_sweep(tmp_path):
    hub, _, _ = make_hub(tmp_path)
    hub.seq = 3  # sweep 4 is still being written: some channels have it, `seq` has not moved yet
    hub._ch = {"0C": deque([(1, 0.4, 700), (2, 0.8, 701), (3, 1.2, 702), (4, 1.6, 703)]),
               "05": deque([(1, 0.4, 41), (2, 0.8, 41), (3, 1.2, 41)])}
    ch = hub.state(after=0)["channels"]
    assert [s[0] for s in ch["0C"]["samples"]] == [1, 2, 3]
    assert [s[0] for s in hub.state(after=3)["channels"]["0C"]["samples"]] == []


def test_a_slow_adapter_never_makes_a_viewer_ingest_a_sample_twice(tmp_path):
    class Slow(SimPort):
        def write(self, data):
            time.sleep(0.02)  # a realistic per-command round trip
            super().write(data)

    sim = Slow("rich")
    hub, _, _ = make_hub(tmp_path, port_factory=lambda: sim, sim=sim)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    seen, after, end = [], 0, time.monotonic() + 2.5
    while time.monotonic() < end:
        st = hub.state(after)
        for s in st["channels"]["0C"]["samples"]:
            seen.append(s[0])
        after = st["seq"]
        time.sleep(0.031)
    hub.stop()
    assert seen and len(seen) == len(set(seen)), "a sweep was delivered twice"


def test_state_carries_a_run_id_that_changes_on_every_start(tmp_path):
    hub, _, _ = make_hub(tmp_path)
    assert hub.state()["run"] == 0
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    first = hub.state()["run"]
    hub.stop()
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert first >= 1 and hub.state()["run"] == first + 1
    hub.stop()


# ---- Important 3: LAN mode must work from another device --------------------------------------------

def test_wildcard_bind_accepts_ip_literal_hosts_on_the_right_port_only(tmp_path):
    hub, _, _ = make_hub(tmp_path)
    server = ConsoleServer(hub, host="0.0.0.0", allow_lan=True, token="tok123")
    server.start()
    try:
        ok = f"192.168.1.50:{server.port}"
        assert request(server, "GET", "/api/state", host=ok)[0] == 200
        assert request(server, "GET", "/api/state", host=f"10.0.0.5:{server.port + 1}")[0] == 403
        assert request(server, "GET", "/api/state", host=f"evil.example:{server.port}")[0] == 403
        assert request(server, "GET", "/api/state", host="192.168.1.50")[0] == 403
        own = f"http://{ok}"
        assert request(server, "POST", "/api/stop", host=ok, headers={"Origin": own}, body={})[0] == 200
        assert request(server, "POST", "/api/stop", host=ok, headers={"Origin": "http://evil.example"}, body={})[0] == 403
    finally:
        server.stop()


def test_a_loopback_only_server_still_refuses_lan_ip_hosts(srv):
    server, _, _ = srv
    assert request(server, "GET", "/api/state", host=f"192.168.1.50:{server.port}")[0] == 403


# ---- Minor upgraded: Stop must actually stop -------------------------------------------------------------

def test_stop_returns_promptly_even_when_every_command_is_slow(tmp_path):
    class Slow(SimPort):
        def write(self, data):
            time.sleep(0.25)  # 8 PIDs = a 2 s sweep
            super().write(data)

    sim = Slow("rich")
    hub, session, _ = make_hub(tmp_path, port_factory=lambda: sim, sim=sim)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    deadline = time.monotonic() + 5
    while hub.state()["seq"] < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.6)  # now the thread is in the middle of sweep 2 (about 2 s long)
    t0 = time.monotonic()
    hub.stop()
    assert time.monotonic() - t0 < 1.0, "stop() waited for a whole sweep"
    assert hub.state()["status"] == "stopped" and not hub.running


# ---- Minor upgraded: console_data must read the service that is actually open ------------------------------

def test_console_data_reads_the_console_opened_last_not_a_dead_real_one(tmp_path):
    class Dead(ScriptedPort):
        def write(self, data):
            raise RuntimeError("cable unplugged")

    sess = Session(Config(port="x", home=tmp_path, timeout=0.5), port_factory=lambda: Dead({}))
    tl = build_tools(sess)
    try:
        tl["open_console"](demo=False)  # opens fine, then the sampler dies with an error
        end = time.monotonic() + 5
        while time.monotonic() < end and tl["console_data"](10)["status"] != "error":
            time.sleep(0.05)
        assert tl["console_data"](10)["status"] == "error"
        tl["open_console"](demo=True)
        end = time.monotonic() + 5
        while time.monotonic() < end and tl["console_data"](10).get("seq", 0) < 3:
            time.sleep(0.05)
        out = tl["console_data"](10)
        assert out["status"] == "running" and out["channels"]["0C"]["stats"]["n"] >= 3
    finally:
        ConsoleService.shutdown_all()


# ---- test hardening for behavior that was correct but untested -----------------------------------------------

def test_origin_null_is_refused(srv):
    server, hub, _ = srv
    assert request(server, "POST", "/api/start", headers={"Origin": "null"}, body={"pids": DEFAULT_PIDS})[0] == 403
    assert not hub.running


def test_request_lines_carrying_the_token_are_never_logged(srv, capfd):
    server, _, _ = srv
    request(server, "GET", "/api/state")
    request(server, "GET", "/api/state", token="wrongtoken")
    out = capfd.readouterr()
    assert "tok123" not in out.out + out.err and "wrongtoken" not in out.out + out.err
