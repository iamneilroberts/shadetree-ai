import http.client
import json
import time

import pytest

from obd_reader.console import ConsoleService
from obd_reader.session import AdapterBusy, Config, NoAdapterError, Session
from obd_reader.simulator import SimPort
from obd_reader.tools import build_tools


def demo_session(tmp_path):
    return Session(Config(port=None, home=tmp_path))


def get_state(url):
    host_port = url.split("//")[1].split("/")[0]
    token = url.split("t=")[1]
    c = http.client.HTTPConnection(host_port, timeout=5)
    c.request("GET", f"/api/state?t={token}", headers={"Host": host_port})
    r = c.getresponse()
    data = json.loads(r.read())
    c.close()
    return data


def wait_seq(url, n):
    end = time.monotonic() + 6
    while time.monotonic() < end:
        if get_state(url)["seq"] >= n:
            return True
        time.sleep(0.03)
    return False


def test_open_console_demo_starts_the_server_and_sampling(tmp_path):
    tl = build_tools(demo_session(tmp_path))
    out = tl["open_console"](demo=True)
    try:
        assert out["demo"] is True and out["url"].startswith("http://127.0.0.1:") and "t=" in out["url"]
        assert wait_seq(out["url"], 3)
        assert tl["open_console"](demo=True)["url"] == out["url"]  # same server, not a second one
    finally:
        ConsoleService.shutdown_all()


def test_console_data_matches_what_the_page_sees(tmp_path):  # Review Focus 5
    tl = build_tools(demo_session(tmp_path))
    out = tl["open_console"](demo=True)
    try:
        assert wait_seq(out["url"], 8)
        data = tl["console_data"](seconds=30)
        st = get_state(out["url"])
        assert data["status"] == "running" and data["seq"] <= st["seq"]
        assert data["channels"]["0C"]["name"] == "engine_rpm" and data["channels"]["0C"]["stats"]["n"] >= 8
        assert {"0C", "05", "06", "07", "08", "09", "0B", "42"} <= set(data["channels"]) and len(data["channels"]) <= 16
    finally:
        ConsoleService.shutdown_all()


def test_other_live_tools_are_refused_while_the_console_samples(tmp_path):  # Review Focus 5
    # a real (non-demo) session whose adapter is the console's: read_pid must not interleave bytes
    sim = SimPort("healthy")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    svc = ConsoleService(s)
    try:
        svc.ensure()
        svc.hub.start(["0C"], hz=10, seconds=30)
        end = time.monotonic() + 5
        while svc.hub.state()["seq"] < 2 and time.monotonic() < end:
            time.sleep(0.02)
        with pytest.raises(AdapterBusy) as e:
            build_tools(s)["read_pid"]("0C")
        assert "console_data" in str(e.value)
    finally:
        svc.stop()


def test_open_console_without_an_adapter_or_demo_is_a_clear_error(tmp_path):
    tl = build_tools(demo_session(tmp_path))
    with pytest.raises(NoAdapterError):
        tl["open_console"](demo=False)


def test_console_data_before_opening_says_so(tmp_path):
    tl = build_tools(demo_session(tmp_path))
    out = tl["console_data"](seconds=10)
    assert out["status"] == "idle" and "open_console" in out["message"]


def test_console_data_rejects_silly_windows(tmp_path):
    tl = build_tools(demo_session(tmp_path))
    for bad in (0, -5, 1e9, float("nan")):
        with pytest.raises(ValueError):
            tl["console_data"](seconds=bad)


def test_cli_console_demo_builds_a_working_service(tmp_path):
    from obd_reader.__main__ import build_parser, console_main

    args = build_parser().parse_args(["console", "--demo", "--http-port", "0", "--scenario", "lean",
                                      "--out-dir", str(tmp_path)])
    svc = console_main(args, block=False)
    try:
        assert wait_seq(svc.server.url, 3)
        assert svc.hub.state()["demo"] is True
    finally:
        svc.stop()


def post_json(url, path, body):
    host_port = url.split("//")[1].split("/")[0]
    token = url.split("t=")[1]
    c = http.client.HTTPConnection(host_port, timeout=5)
    c.request("POST", f"{path}?t={token}", body=json.dumps(body), headers={"Host": host_port, "Content-Type": "application/json"})
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


def test_console_data_names_its_source(tmp_path):  # Review Focus 5
    tl = build_tools(demo_session(tmp_path))
    out = tl["open_console"](demo=True)
    try:
        assert wait_seq(out["url"], 3)
        assert tl["console_data"](seconds=30)["source"] == "live"
        assert post_json(out["url"], "/api/stop", {}) == 200
        run = {"kind": "live_run", "live_sample": {"duration_s": 1.2, "rate_hz": 2.5, "series": {
            "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[0.4, 700], [0.8, 710], [1.2, 720]]}}}}
        assert post_json(out["url"], "/api/replay", {"run": run, "name": "drive.json"}) == 200
        assert post_json(out["url"], "/api/replay/control", {"action": "seek", "pos": 1.2}) == 200
        data = tl["console_data"](seconds=30)
        assert data["source"] == "replay" and data["replay"] == "drive.json" and data["channels"]["0C"]["latest"] == 720.0
    finally:
        ConsoleService.shutdown_all()
