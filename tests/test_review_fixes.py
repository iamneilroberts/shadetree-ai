"""Regression tests for the findings of the Phase 3a whole-branch review."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from obd_reader.live import sample
from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.session import Config, Session
from obd_reader.store import SnapshotStore
from obd_reader.tools import TOOL_NAMES, build_tools
from obd_reader.transport import AdapterNotReady, SerialPort, Transport

from conftest import REVIEWED_TOOLS, FakeClock, RampPort, ScriptedPort

SEDAN = Path(__file__).parent / "fixtures" / "synthetic_sedan.jsonl"
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def live_session(tmp_path, factory):
    clk = FakeClock()
    return Session(Config(port="fake", home=tmp_path, timeout=0.2), port_factory=factory,
                   clock=clk.now, sleep=clk.sleep)


# ---- Important 1: never write while the adapter may still be busy -------------------------------

def test_serial_port_refuses_to_write_while_the_previous_command_has_no_prompt():
    # A reply that timed out with no '>' means the ELM may still be busy; writing now
    # would interrupt it and could make it read the rest of our bytes as a new command.
    port = SerialPort("loop://")
    port.recovery_s = 0.2
    assert port.read_until_prompt(0.1) == ""
    with pytest.raises(AdapterNotReady):
        port.write(b"0100\r")
    assert port._ser.in_waiting == 0
    port.close()


def test_serial_port_writes_once_the_late_prompt_arrives():
    port = SerialPort("loop://")
    port.recovery_s = 1.0
    port.read_until_prompt(0.1)
    port._ser.write(b"STOPPED\r>")  # the ELM finally answers
    port.write(b"0100\r")
    assert port._ser.read(64) == b"0100\r"
    port.close()


@pytest.mark.parametrize("bad", ["nan", "inf", "-1", "0", "abc"])
def test_timeout_must_be_a_positive_finite_number(bad):
    with pytest.raises(ValueError):
        Config.from_env({"SHADETREE_TIMEOUT": bad})


# ---- Important 2: bounded time holding the adapter -----------------------------------------------

def test_sampling_stops_early_when_nothing_answers():
    port = ScriptedPort({})
    clk = FakeClock()
    ls = sample(Transport(port), ["0C", "0D"], 60, hz=1, clock=clk.now, sleep=clk.sleep)
    assert len(port.writes) <= 4 and all(s.samples == [] for s in ls.series.values())
    assert clk.t < 5


def test_live_data_says_so_when_nothing_answers(tmp_path):
    out = build_tools(live_session(tmp_path, lambda: ScriptedPort({})))["live_data"](["0C"], seconds=30, hz=1)
    assert "no data" in out["note"].lower() and out["series"]["0C"]["stats"] == {"n": 0}


# ---- Important 3: freeze frame with more than one ECU --------------------------------------------

def test_freeze_frame_uses_the_ecu_that_has_one():
    recs = load_transcript(SEDAN)
    for tx, rx in (("020200", ["42 02 00 00 00", "42 02 00 01 71"]),
                   ("020000", ["42 00 00 18 18 00 00", "42 00 00 18 18 00 00"]),
                   ("020C00", ["42 0C 00 00 00", "42 0C 00 1A F8"]),
                   ("020500", ["42 05 00 28", "42 05 00 7B"])):
        recs = [dict(r, rx=rx) if r["tx"] == tx else r for r in recs]
    snap = scan(Transport(ReplayPort(recs)), snapshot_id="t", captured_at=NOW, protocol="6")
    ff = snap.freeze_frame
    assert ff is not None and ff.dtc == "P0171"
    assert ff.pids["0C"].value == 1726.0 and ff.pids["05"].value == 83  # second ECU's values, not the first's


def test_freeze_frame_skips_a_pid_when_ecu_counts_differ():
    # only one ECU answers 020C00 while two answered the DTC request: attribution is unsafe, so skip it
    recs = load_transcript(SEDAN)
    for tx, rx in (("020200", ["42 02 00 00 00", "42 02 00 01 71"]),
                   ("020C00", ["42 0C 00 1A F8"])):
        recs = [dict(r, rx=rx) if r["tx"] == tx else r for r in recs]
    snap = scan(Transport(ReplayPort(recs)), snapshot_id="t", captured_at=NOW, protocol="6")
    assert snap.freeze_frame.dtc == "P0171" and "0C" not in snap.freeze_frame.pids


# ---- Review Focus 2: symlinks and error text -----------------------------------------------------

def test_symlinked_snapshot_outside_the_data_dir_is_refused(tmp_path):
    home = tmp_path / "home"
    (home / "snapshots").mkdir(parents=True)
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({"password": "hunter2"}))
    (home / "snapshots" / "ln.json").symlink_to(outside)
    st = SnapshotStore(home)
    with pytest.raises((ValueError, FileNotFoundError)) as e:
        st.load("ln")
    assert "hunter2" not in str(e.value)
    assert st.list() == []


def test_malformed_snapshot_errors_do_not_echo_content(tmp_path):
    st = SnapshotStore(tmp_path)
    st.dir.mkdir(parents=True)
    (st.dir / "bad.json").write_text(json.dumps({"snapshot_id": "hunter2-SECRET"}))
    with pytest.raises(ValueError) as e:
        st.load("bad")
    assert "hunter2" not in str(e.value)


# ---- Important 10: no J1939 / user-defined protocols ---------------------------------------------

@pytest.mark.parametrize("proto", ["A", "B", "C", "a"])
def test_scan_refuses_j1939_and_user_defined_protocols(tmp_path, proto):
    ports = []
    s = live_session(tmp_path, lambda: ports.append(ReplayPort([])) or ports[-1])
    with pytest.raises(ValueError):
        build_tools(s)["scan"]("ok", proto)
    assert ports == []


# ---- test hardening ------------------------------------------------------------------------------

def test_live_data_stats_are_exact_not_computed_from_the_downsample(tmp_path):
    port = RampPort()
    out = build_tools(live_session(tmp_path, lambda: port))["live_data"](["0C"], seconds=120, hz=10)
    st = out["series"]["0C"]["stats"]
    assert len(out["series"]["0C"]["samples"]) <= 120
    assert st["n"] == port.n and st["min"] == 10 and st["max"] == port.n * 10
    assert st["mean"] == pytest.approx(10 * (port.n + 1) / 2, abs=0.01)


def test_the_tool_set_is_the_literal_reviewed_list(tmp_path):
    assert set(build_tools(live_session(tmp_path, lambda: ScriptedPort({})))) == set(REVIEWED_TOOLS)
    assert set(TOOL_NAMES) == set(REVIEWED_TOOLS)


def test_registered_mcp_tools_are_the_literal_reviewed_list(tmp_path):
    from obd_reader.mcp_server import build_server

    srv = build_server(live_session(tmp_path, lambda: ScriptedPort({})))
    assert {t.name for t in asyncio.run(srv.list_tools())} == set(REVIEWED_TOOLS)
