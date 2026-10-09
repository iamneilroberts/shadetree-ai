import io
import json

import pytest

from obd_reader.bus_capture import CaptureWriter, read_records
from obd_reader.listen import REST_S, SCRIPT, Keys, Step, listen, run_capture, script_seconds
from obd_reader.session import Config, Session
from obd_reader.simulator import SimPort
from obd_reader.transport import MonitorEvent
from obd_reader.vehicle import vehicle_key
from obd_reader.vin import find_vins

TWO = (Step("a", "Do A", 2.0), Step("b", "Do B", 2.0))  # a: 0-2, rest to 7, b: 7-9, rest to 14


class FakeKeys:
    def __init__(self, at=None):
        self.at, self.t = dict(at or {}), None

    def poll(self):
        return self.at.pop(self.t, None)


def feed(ts, keys=None, extra=()):
    """Idle events at the given times (plus extra events), with keys keyed by event time."""
    closed = []

    def gen():
        try:
            for t in ts:
                if keys is not None:
                    keys.t = t
                yield MonitorEvent("idle", t)
                for e in extra:
                    if e.t == t:
                        yield e
        finally:
            closed.append(True)
    return gen(), closed


def capture(tmp_path, events, script=TWO, keys=None, start=0.0):
    out, w = [], CaptureWriter(tmp_path / "c.jsonl")
    reason = run_capture(events, w, script, keys or FakeKeys(), out.append, start)
    w.close()
    return reason, list(read_records(w.path)), out


def steps(recs):
    return [(r["step"], r["phase"], r["t"]) for r in recs if r["type"] == "step"]


def test_the_script_runs_its_windows_and_rests_on_schedule(tmp_path):
    ev, closed = feed([x / 2 for x in range(0, 40)])
    reason, recs, out = capture(tmp_path, ev)
    assert reason == "finished" and closed == [True]
    assert steps(recs) == [("a", "start", 0.0), ("a", "end", 2.0), ("b", "start", 7.0), ("b", "end", 9.0)]
    assert recs[-1]["type"] == "end" and recs[-1]["reason"] == "finished"
    assert any("[1/2] Do A" in ln for ln in out) and any("[2/2] Do B" in ln for ln in out)


def test_s_skips_the_current_step_and_q_stops_and_keeps_the_file(tmp_path):
    keys = FakeKeys({0.5: "s", 8.0: "q"})
    ev, closed = feed([x / 2 for x in range(0, 40)], keys)
    reason, recs, _ = capture(tmp_path, ev, keys=keys)
    assert steps(recs) == [("a", "start", 0.0), ("a", "skipped", 0.5), ("b", "start", 5.5), ("b", "end", 7.5)]
    assert reason == "quit" and recs[-1]["reason"] == "quit" and closed == [True]


def test_frames_and_gaps_are_written_relative_to_the_start(tmp_path):
    extra = [MonitorEvent("frame", 101.0, "0C9 01"), MonitorEvent("gap", 101.5, "BUFFER FULL", 0.3)]
    ev, _ = feed([100 + x / 2 for x in range(0, 40)], extra=extra)
    _, recs, _ = capture(tmp_path, ev, start=100.0)
    assert {"type": "frame", "t": 1.0, "raw": "0C9 01"} in recs
    assert any(r["type"] == "gap" and r["t"] == 1.5 and r["seconds"] == 0.3 for r in recs)


def test_a_plain_listen_finishes_when_the_monitor_does(tmp_path):
    ev, _ = feed([0.0, 0.5, 1.0])
    reason, recs, _ = capture(tmp_path, ev, script=())
    assert reason == "finished" and steps(recs) == []


def test_a_script_cut_short_by_the_time_limit_says_so(tmp_path):
    ev, _ = feed([0.0, 0.5, 1.0])
    reason, recs, _ = capture(tmp_path, ev)
    assert reason == "time_limit" and steps(recs) == [("a", "start", 0.0), ("a", "end", 1.0)]
    assert recs[-1]["type"] == "end" and recs[-1]["reason"] == "time_limit"


def test_q_inside_a_window_closes_that_step_before_the_end_record(tmp_path):
    keys = FakeKeys({8.0: "q"})
    ev, _ = feed([x / 2 for x in range(0, 40)], keys)
    reason, recs, _ = capture(tmp_path, ev, keys=keys)
    assert reason == "quit" and steps(recs)[-2:] == [("b", "start", 7.0), ("b", "end", 8.0)]
    assert [r["type"] for r in recs[-2:]] == ["step", "end"]


def test_the_end_record_survives_a_close_that_raises(tmp_path):
    def gen():
        try:
            while True:
                yield MonitorEvent("frame", 0.1, "0C9 01")
        finally:
            raise OSError("unplugged while stopping")
    keys = FakeKeys()
    keys.poll = lambda: "q"
    w = CaptureWriter(tmp_path / "c.jsonl")
    with pytest.raises(OSError):
        run_capture(gen(), w, (), keys, lambda s: None, 0.0)
    w.close()
    recs = list(read_records(w.path))
    assert recs[-1]["type"] == "end" and recs[-1]["reason"] == "quit"


@pytest.mark.parametrize("exc,reason", [(OSError("unplugged"), "error"), (KeyboardInterrupt(), "interrupted")])
def test_an_error_or_ctrl_c_still_ends_the_file_and_stops_the_monitor(tmp_path, exc, reason):
    closed = []

    def gen():
        try:
            yield MonitorEvent("frame", 0.1, "0C9 01")
            raise exc
        finally:
            closed.append(True)
    w = CaptureWriter(tmp_path / "c.jsonl")
    with pytest.raises(type(exc)):
        run_capture(gen(), w, TWO, FakeKeys(), lambda s: None, 0.0)
    w.close()
    recs = list(read_records(w.path))
    assert recs[-1]["type"] == "end" and recs[-1]["reason"] == reason and recs[-1]["frames"] == 1 and closed == [True]


def test_keys_on_a_stream_that_is_not_a_terminal_never_fire():
    with Keys(stream=io.StringIO("sq")) as keys:
        assert keys.poll() is None


def test_the_script_is_the_specified_one():
    assert SCRIPT[0] == Step("baseline", SCRIPT[0].prompt, 30.0) and len(SCRIPT) == 14
    assert all(s.window_s == 10.0 for s in SCRIPT[1:]) and REST_S == 5.0
    assert script_seconds(SCRIPT) == 30 + 13 * 10 + 14 * 5


def test_listen_on_the_simulator_scans_sets_up_and_captures(tmp_path):
    session = Session(Config(port="sim", home=tmp_path, timeout=1.0), port_factory=lambda: SimPort("healthy", bus="can"))
    out = []
    path = listen(session, label="t", protocol="0", seconds=1.0, out=out.append, keys=FakeKeys())
    recs = list(read_records(path))
    head, end = recs[0], recs[-1]
    assert path.parent == tmp_path / "captures" and path.suffix == ".jsonl"
    assert head["type"] == "header" and head["monitor_command"] == "ATMA" and head["can"] is True and head["protocol"] == "A6"
    saved = json.loads((tmp_path / "snapshots" / f"{head['snapshot_id']}.json").read_text())
    # None on the simulator: its SIMULATED protocol makes scan() skip the VIN path
    assert head["vehicle_key"] == vehicle_key(saved["vehicle"]["vin"]) and head["script"] == []
    assert [s["tx"] for s in head["setup"]] == ["ATH1", "ATS1", "ATAL"]
    assert (tmp_path / "snapshots" / f"{head['snapshot_id']}.json").exists()
    assert find_vins(json.dumps(head)) == [] and end["reason"] == "finished" and end["frames"] > 20
