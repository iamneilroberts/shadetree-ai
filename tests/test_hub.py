import json
import time

import pytest

from obd_reader.hub import DEFAULT_PIDS, HubBusy, LiveHub
from obd_reader.live import LiveLimitError
from obd_reader.session import AdapterBusy, Config, Session
from obd_reader.simulator import SimPort

from conftest import ScriptedPort


def make(tmp_path, port_factory=None, sim=None):
    sim = sim or SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=port_factory or (lambda: sim))
    return LiveHub(s, sim=sim), s, sim


def wait_for(cond, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_hub_samples_and_reports_increments(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 5)
    st = hub.state(after=0)
    assert st["status"] == "running" and st["demo"] is True and set(DEFAULT_PIDS) <= set(st["channels"]) and set(st["channels"]) == set(DEFAULT_PIDS) | set(st["extras"])
    assert st["channels"]["0C"]["name"] == "engine_rpm" and st["channels"]["0C"]["unit"] == "rpm"
    first = st["seq"]
    assert wait_for(lambda: hub.state()["seq"] > first + 2)
    inc = hub.state(after=first)
    assert all(s[0] > first for s in inc["channels"]["0C"]["samples"]) and inc["channels"]["0C"]["samples"]
    assert st["adapter"]["protocol"] in (None, "SIMULATED (no car)")
    hub.stop()
    assert hub.state()["status"] == "stopped"


def test_two_viewers_with_different_after_values_both_get_correct_increments(tmp_path):  # Review Focus 4
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 6)
    hub.stop()
    full = hub.state(0)["channels"]["0C"]["samples"]
    a, b = hub.state(2)["channels"]["0C"]["samples"], hub.state(4)["channels"]["0C"]["samples"]
    assert [s[0] for s in a] == [s[0] for s in full if s[0] > 2]
    assert [s[0] for s in b] == [s[0] for s in full if s[0] > 4]


def test_a_new_run_resets_seq_and_buffers(tmp_path):  # Review Focus 4
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 4)
    hub.stop()
    old = hub.state()["seq"]
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 1)
    assert hub.state()["seq"] < old + 2 and hub.state(0)["channels"]["0C"]["samples"][0][0] == 1
    hub.stop()


@pytest.mark.parametrize("pids", [[], ["0C\r04"], ["ZZ"], ["FF"], [f"{i:02X}" for i in range(9)]])
def test_bad_pids_are_refused_before_any_traffic(tmp_path, pids):  # Review Focus 2
    opened = []
    hub, _, _ = make(tmp_path, port_factory=lambda: opened.append(1) or ScriptedPort({}))
    with pytest.raises(LiveLimitError):
        hub.start(pids)
    assert opened == [] and hub.state()["status"] == "idle"


@pytest.mark.parametrize("hz,seconds", [(0, 10), (1e-9, 10), (11, 10), (float("nan"), 10), (2, 0), (2, -1),
                                        (2, 1801), (2, float("inf")), (2, float("nan"))])
def test_bad_rate_or_duration_is_refused(tmp_path, hz, seconds):  # Review Focus 2
    hub, _, _ = make(tmp_path)
    with pytest.raises(LiveLimitError):
        hub.start(DEFAULT_PIDS, hz=hz, seconds=seconds)


def test_starting_twice_is_refused(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    with pytest.raises(HubBusy):
        hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    hub.stop()


def test_hub_holds_the_adapter_lock_while_running_and_releases_it(tmp_path):  # Review Focus 3
    hub, session, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 1)
    with pytest.raises(AdapterBusy) as e:
        with session.connection("other"):
            pass
    assert "console_data" in str(e.value)
    hub.stop()
    with session.connection("after"):
        pass


def test_silent_bus_ends_the_run_with_a_message(tmp_path):  # Review Focus 3
    hub, _, _ = make(tmp_path, port_factory=lambda: ScriptedPort({}), sim=SimPort())
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["status"] != "running")
    st = hub.state()
    assert st["status"] == "stopped" and "no data" in st["message"].lower() and st["seq"] == 0


def test_a_failing_adapter_ends_in_error_and_frees_the_lock(tmp_path):  # Review Focus 3
    class Boom(ScriptedPort):
        def write(self, data):
            raise RuntimeError("cable unplugged")

    hub, session, _ = make(tmp_path, port_factory=lambda: Boom({}), sim=SimPort())
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["status"] == "error")
    assert "cable unplugged" in hub.state()["message"]
    # lock released, no zombie: a new connection gets as far as the (still broken) port, not AdapterBusy
    with pytest.raises(RuntimeError, match="cable unplugged"):
        with session.connection("after"):
            pass
    assert not hub.running


def test_run_auto_stops_at_the_deadline(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=0.5)
    assert wait_for(lambda: hub.state()["status"] == "stopped", 4.0)
    assert "auto-stopped" in hub.state()["message"]


def test_recent_reports_exact_stats_over_the_window(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 8)
    hub.stop()
    r = hub.recent(30)
    assert r["0C"]["name"] == "engine_rpm" and r["0C"]["stats"]["n"] >= 8
    assert r["0C"]["latest"] == hub.state(hub.state()["seq"] - 1)["channels"]["0C"]["samples"][-1][2]


def test_save_run_writes_a_json_file_and_never_overwrites(tmp_path):
    hub, _, _ = make(tmp_path)
    with pytest.raises(ValueError):
        hub.save_run("early")  # nothing sampled yet
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 3)
    hub.stop()
    p = hub.save_run("bench-idle")
    data = json.loads(p.read_text())
    assert p.parent == (tmp_path / "runs") and data["live_sample"]["series"]["0C"]["samples"]
    for bad in ("../x", "A b", "", "x" * 41):
        with pytest.raises(ValueError):
            hub.save_run(bad)


def test_run_file_names_the_runs_transcript_relative_to_home(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 3)
    hub.stop()
    data = json.loads(hub.save_run("bench-idle").read_text())
    tr = data["transcript"]
    assert tr.startswith("transcripts/") and tr.endswith("-console.jsonl")  # relative: no home path in a shared run
    lines = (tmp_path / tr).read_text().splitlines()
    assert any(json.loads(ln)["tx"] == "010C" for ln in lines)


def test_set_sim_only_in_demo(tmp_path):
    hub, _, sim = make(tmp_path)
    hub.set_sim(scenario="lean", rev=True)
    assert sim.scenario == "lean" and sim.rev is True
    with pytest.raises(ValueError):
        hub.set_sim(scenario="bogus")
    real = LiveHub(Session(Config(port="x", home=tmp_path), port_factory=lambda: ScriptedPort({})))
    with pytest.raises(ValueError):
        real.set_sim(rev=True)


def _codes_after_start(tmp_path, scenario, sim=None):
    hub, _, _ = make(tmp_path, sim=sim or SimPort(scenario))
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["codes"]["read"])
    st = hub.state()["codes"]
    hub.stop()
    return st


def test_state_carries_the_trouble_codes_with_descriptions(tmp_path):
    c = _codes_after_start(tmp_path, "rich")
    assert [x["code"] for x in c["stored"]] == ["P0117", "P0172"]
    assert [x["code"] for x in c["pending"]] == ["P0175"] and c["permanent"] == []
    assert c["mil"] is True and c["stored"][0]["desc"] and c["stored"][0]["known"] is True


def test_healthy_car_reads_no_codes_and_lamp_off(tmp_path):
    c = _codes_after_start(tmp_path, "healthy")
    assert c["stored"] == c["pending"] == c["permanent"] == [] and c["mil"] is False


def test_codes_are_not_read_before_the_first_sample(tmp_path):
    hub, _, _ = make(tmp_path)
    assert hub.state()["codes"] == {"read": False, "note": None}


def _sim_with(replies: dict[str, str]):
    """A simulated car whose ATDP (and any listed command) answers as given."""
    sim = SimPort("rich")
    sim.sent = []
    orig = sim.write

    def write(data):
        orig(data)
        cmd = data.decode().strip()
        sim.sent.append(cmd)
        if cmd in replies:
            sim._pending = replies[cmd]
    sim.write = write
    return sim


def test_unknown_protocol_skips_code_decoding_and_says_why(tmp_path):
    sim = _sim_with({"ATDP": "AUTO\r"})
    hub, _, _ = make(tmp_path, sim=None, port_factory=lambda: sim)
    hub._sim = None  # behave like a real adapter: only a named protocol enables code decoding
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["codes"]["note"])
    st = hub.state()["codes"]
    hub.stop()
    assert st["read"] is False and "not supported" in st["note"]


def test_legacy_protocol_reads_codes_with_the_legacy_layout(tmp_path):
    sim = _sim_with({"ATDP": "SAE J1850 VPW\r", "03": "43 01 33 00 00 00 00\r", "07": "47 00 00 00 00 00 00\r"})
    hub, _, _ = make(tmp_path, sim=None, port_factory=lambda: sim)
    hub._sim = None
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["codes"]["read"])
    st = hub.state()
    hub.stop()
    codes = st["codes"]
    assert [c["code"] for c in codes["stored"]] == ["P0133"] and codes["pending"] == []
    assert codes["permanent"] == [] and "permanent" in codes["unanswered"]  # Mode 0A is never asked on VPW
    assert "03" in sim.sent and "0A" not in sim.sent


class _NoMapSim(SimPort):
    """A car that does not answer PID 0B (MAP)."""
    def write(self, data: bytes) -> None:
        super().write(data)
        if data.decode("ascii").rstrip("\r") == "010B":
            self._pending = "NO DATA\r"


def test_a_pid_the_car_never_answers_is_dropped_and_reported(tmp_path):
    sim = _NoMapSim("rich")
    hub, _, _ = make(tmp_path, sim=sim)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["unsupported"] == ["0B"])
    assert wait_for(lambda: hub.state()["seq"] >= 8)
    st = hub.state()
    assert st["status"] == "running" and st["channels"]["0B"]["samples"] == []
    assert st["channels"]["0C"]["samples"] and st["channels"]["05"]["samples"]
    hub.stop()


def test_a_supported_pid_is_never_reported_unsupported(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 8)
    assert hub.state()["unsupported"] == []
    hub.stop()


def test_the_run_discovers_extra_readings_up_to_the_pid_cap(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 8)
    st = hub.state()
    assert st["extras"] and len(DEFAULT_PIDS) + len(st["extras"]) <= 16
    assert set(st["extras"]).isdisjoint(DEFAULT_PIDS) and set(st["extras"]) <= set(st["channels"])
    assert all(st["channels"][p]["samples"] for p in st["extras"])  # every extra gets read (they rotate)
    hub.stop()


def test_mode06_results_are_read_once_and_carried_in_state(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["mode06"]["read"])
    m = hub.state()["mode06"]
    assert m["mids"] == ["01", "21"] and len(m["results"]) == 3
    assert {r["mid"] for r in m["results"]} == {"01", "21"}
    hub.stop()


def test_seventeen_pids_are_refused_and_sixteen_are_accepted(tmp_path):
    hub, _, _ = make(tmp_path)
    too_many = ["04", "05", "06", "07", "08", "09", "0B", "0C", "0D", "0E", "11", "42", "43", "44", "0F", "5C", "46"]
    with pytest.raises(LiveLimitError):
        hub.start(too_many, hz=5, seconds=5)
    hub.start(too_many[:16], hz=5, seconds=5)
    hub.stop()


import json as _json

from obd_reader.simulator import SIM_VIN
from obd_reader.vehicle import vehicle_key

CORE = ["0C", "05", "0F"]  # 0F is a PID the simulator does not answer


def _run_once(tmp_path, pids=CORE, hz=10):
    hub, s, sim = make(tmp_path)
    hub.start(pids, hz=hz, seconds=30)
    assert wait_for(lambda: hub.state()["vehicle"] is not None)
    assert wait_for(lambda: hub.state()["seq"] >= 8)
    hub.stop()
    return hub


def test_vehicle_is_identified_by_key_only_and_first_run_is_a_new_car(tmp_path):
    hub = _run_once(tmp_path)
    v = hub.state()["vehicle"]
    assert v == {"key": vehicle_key(SIM_VIN), "known": False, "runs": 0, "note": None}
    assert SIM_VIN not in _json.dumps(hub.state()) and SIM_VIN[-6:] not in _json.dumps(hub.state())


def test_profile_is_saved_with_no_vin_in_it_and_second_run_knows_the_car(tmp_path):
    _run_once(tmp_path)
    f = tmp_path / "profiles" / f"{vehicle_key(SIM_VIN)}.json"
    text = f.read_text()
    assert SIM_VIN not in text and SIM_VIN[-6:] not in text
    saved = _json.loads(text)
    assert saved["runs"] == 1 and "0F" in saved["unsupported"] and "0C" in saved["supported_pids"]
    hub2 = _run_once(tmp_path)
    assert hub2.state()["vehicle"]["known"] is True and hub2.state()["vehicle"]["runs"] == 1
    assert _json.loads(f.read_text())["runs"] == 2


def test_known_unsupported_pid_is_dropped_after_one_miss_and_a_pid_that_answers_is_kept(tmp_path):
    from obd_reader.profiles import ProfileStore
    ProfileStore(tmp_path).save(vehicle_key(SIM_VIN), {"schema": 1, "key": vehicle_key(SIM_VIN), "updated": "", "runs": 4,
                                                        "protocol": None, "supported_pids": [], "unsupported": ["0F", "0C"], "extras": []})
    hub = _run_once(tmp_path)
    st = hub.state()
    assert "0F" in st["unsupported"] and "0C" not in st["unsupported"]  # 0C answers, so the old hint is overruled
    assert _json.loads((tmp_path / "profiles" / f"{vehicle_key(SIM_VIN)}.json").read_text())["unsupported"] == ["0F"]


def test_corrupt_profile_is_ignored_and_overwritten(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    (d / f"{vehicle_key(SIM_VIN)}.json").write_text("{oops")
    hub = _run_once(tmp_path)
    assert hub.state()["vehicle"]["known"] is False
    assert _json.loads((d / f"{vehicle_key(SIM_VIN)}.json").read_text())["runs"] == 1


def test_unwritable_profile_dir_does_not_break_the_run(tmp_path):
    (tmp_path / "profiles").write_text("a file where the folder should be")
    hub = _run_once(tmp_path)
    st = hub.state()
    assert st["seq"] >= 8 and st["status"] == "stopped" and "could not save the car profile" in (st["message"] or "")


def test_run_with_no_value_writes_no_profile(tmp_path):
    hub, _, _ = make(tmp_path, port_factory=lambda: ScriptedPort({}), sim=SimPort())  # silent bus
    hub.start(["0C"], hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["status"] != "running", 5)
    assert hub.state()["vehicle"] is None and not (tmp_path / "profiles").exists()


def test_car_that_reports_no_vin_gets_a_note_and_no_profile(tmp_path):
    hub, _, _ = make(tmp_path, port_factory=lambda: ScriptedPort({"0C": "1AF8"}), sim=SimPort())
    hub.start(["0C"], hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["vehicle"] is not None)
    assert wait_for(lambda: hub.state()["seq"] >= 4)
    hub.stop()
    assert hub.state()["vehicle"] == {"key": None, "known": False, "runs": 0, "note": "the car did not report a VIN"}
    assert not (tmp_path / "profiles").exists()


def test_a_finished_run_is_saved_automatically_and_a_new_start_cannot_lose_it(tmp_path):
    sim = SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(s, sim=sim, autosave=True)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 5)
    hub.stop()
    files = list((tmp_path / "runs").glob("*-auto.json"))
    assert len(files) == 1 and "run saved as" in hub.state()["message"]
    assert json.loads(files[0].read_text())["live_sample"]["series"]["0C"]["samples"]
    assert hub.save_run("drive") == files[0]  # pressing Save run afterwards does not duplicate the file
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)  # the next run clears memory, not the file
    assert wait_for(lambda: hub.state()["seq"] >= 1)
    hub.stop()
    assert len(list((tmp_path / "runs").glob("*-auto.json"))) >= 1 and files[0].exists()


def test_a_demo_run_is_not_saved_automatically(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 3)
    hub.stop()
    assert not (tmp_path / "runs").exists() and "saved" not in (hub.state()["message"] or "")


def test_a_run_that_could_not_be_saved_warns_once_before_a_new_start_clears_it(tmp_path):
    sim = SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(s, sim=sim, autosave=True)
    (tmp_path / "runs").write_text("not a folder")  # makes the save fail
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 3)
    hub.stop()
    assert "could not save the run automatically" in hub.state()["message"]
    with pytest.raises(HubBusy):
        hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)  # second press discards it on purpose
    hub.stop()


def test_a_saved_run_keeps_every_sample_even_when_the_chart_buffer_is_small(tmp_path):
    sim = SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(s, sim=sim, max_buffer=5, autosave=False)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 20)
    hub.stop()
    assert len(hub.state(after=0)["channels"]["0C"]["samples"]) == 5   # what the page sees is bounded
    saved = json.loads(hub.save_run("long-drive").read_text())
    n = saved["live_sample"]["series"]["0C"]["samples"]
    assert len(n) >= 20 and n[0][0] < 2.0                               # the saved run starts at the start


from obd_reader.replay_run import load_run


def _run_obj(n=10, codes=None):
    ts = [round(0.4 * k, 3) for k in range(1, n + 1)]
    o = {"kind": "live_run", "demo": False, "adapter": {"protocol": "ISO 15765-4 (CAN 29/500)"},
         "live_sample": {"duration_s": ts[-1], "rate_hz": 2.5, "series": {
             "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[t, 700 + 10 * i] for i, t in enumerate(ts)]},
             "AB": {"name": "made_up", "unit": None, "samples": [[t, i] for i, t in enumerate(ts)]}}}}
    if codes:
        o["codes"] = codes
    return o


def _replay_hub(tmp_path, playing=False, **kw):
    hub, _, _ = make(tmp_path)
    hub.start_replay(load_run(_run_obj(**kw)), "drive.json", playing=playing)
    return hub


def test_replay_state_and_stepping_publish_sweeps(tmp_path):
    hub = _replay_hub(tmp_path)
    st = hub.state()
    assert st["status"] == "running" and st["demo"] is False and st["seq"] == 0
    assert st["replay"] == {"name": "drive.json", "duration": 4.0, "pos": 0.0, "speed": 1.0, "playing": False, "ended": False, "demo": False}
    assert st["adapter"] == {"chip": None, "ati": "replay", "protocol": "ISO 15765-4 (CAN 29/500)"}
    assert st["codes"] == {"read": False, "note": "not stored in this run"} and st["mode06"]["read"] is False
    hub._replay_advance(1.0)
    st = hub.state()
    assert st["seq"] == 2 and st["now"] == 1.0 and st["replay"]["pos"] == 1.0
    assert [s[2] for s in st["channels"]["0C"]["samples"]] == [700.0, 710.0]
    assert st["channels"]["AB"]["name"] == "made_up" and st["channels"]["0C"]["name"] == "engine_rpm"
    hub.exit_replay()


def test_speed_scales_the_advance_and_bad_values_are_refused(tmp_path):
    hub = _replay_hub(tmp_path)
    hub.replay_control("speed", speed=4)
    hub._replay_advance(0.5)
    assert hub.state()["replay"]["pos"] == 2.0 and hub.state()["replay"]["speed"] == 4.0
    for bad in (3, 0, -1, True, "fast", None):
        with pytest.raises(ValueError):
            hub.replay_control("speed", speed=bad)
    with pytest.raises(ValueError):
        hub.replay_control("explode")
    with pytest.raises(ValueError):
        hub.replay_control("seek", pos=float("nan"))
    hub.exit_replay()


def test_backward_seek_resets_the_page_and_refills_the_last_minute(tmp_path):
    hub = _replay_hub(tmp_path)
    hub._replay_advance(3.0)
    before = hub.state()
    hub.replay_control("seek", pos=1.0)
    st = hub.state()
    assert st["run"] != before["run"], "a new run id makes viewers drop their buffers"
    assert st["seq"] == 2 and st["now"] == 1.0 and [s[2] for s in st["channels"]["0C"]["samples"]] == [700.0, 710.0]
    assert st["replay"]["ended"] is False
    hub.exit_replay()


def test_play_pause_end_and_restart(tmp_path):
    hub = _replay_hub(tmp_path)
    hub.replay_control("play")
    assert hub.state()["replay"]["playing"] is True
    hub.replay_control("pause")
    hub._replay_advance(10.0)  # past the end
    r = hub.state()["replay"]
    assert r["pos"] == 4.0 and r["ended"] is True and r["playing"] is False and hub.state()["seq"] == 10
    hub.replay_control("play")  # from the end: starts over
    r = hub.state()["replay"]
    assert r["pos"] < 0.5 and r["ended"] is False and r["playing"] is True  # the player thread is running now, so not exactly 0
    hub.replay_control("restart")
    assert hub.state()["replay"]["pos"] < 0.5
    hub.exit_replay()


def test_the_player_thread_advances_while_playing_and_holds_when_paused(tmp_path):
    hub = _replay_hub(tmp_path, playing=True)
    hub.replay_control("speed", speed=8)
    assert wait_for(lambda: hub.state()["replay"]["ended"], 5)
    assert hub.state()["seq"] == 10
    hub.replay_control("restart")
    hub.replay_control("pause")
    seq = hub.state()["seq"]
    time.sleep(0.3)
    assert hub.state()["seq"] == seq
    hub.exit_replay()


def test_exit_returns_to_idle_and_stop_means_exit(tmp_path):
    hub = _replay_hub(tmp_path)
    hub._replay_advance(1.0)
    hub.stop()
    st = hub.state()
    assert st["status"] == "idle" and st["replay"] is None and st["seq"] == 0 and st["channels"] == {}
    assert not hub.running


def test_live_sampling_and_replay_exclude_each_other(tmp_path):
    hub = _replay_hub(tmp_path)
    with pytest.raises(HubBusy, match="replay"):
        hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    hub.exit_replay()
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 2)
    with pytest.raises(HubBusy):
        hub.start_replay(load_run(_run_obj()), "x.json")
    assert hub.state()["status"] == "running" and hub.state()["replay"] is None
    hub.stop()


def test_loading_another_run_replaces_the_first(tmp_path):
    hub = _replay_hub(tmp_path)
    hub._replay_advance(1.0)
    hub.start_replay(load_run(_run_obj(n=5)), "second.json", playing=False)
    st = hub.state()
    assert st["replay"]["name"] == "second.json" and st["replay"]["duration"] == 2.0 and st["seq"] == 0
    hub.exit_replay()


def test_a_replay_never_writes_a_file_and_cannot_be_saved(tmp_path):
    sim = SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(s, sim=sim, autosave=True)
    hub.start_replay(load_run(_run_obj()), "drive.json", playing=False)
    hub._replay_advance(10.0)
    with pytest.raises(ValueError, match="replay"):
        hub.save_run("x")
    hub.exit_replay()
    assert not (tmp_path / "runs").exists()


def test_unsaved_live_run_is_not_silently_replaced_by_a_replay(tmp_path):
    hub, _, _ = make(tmp_path)
    hub._unsaved = True
    with pytest.raises(HubBusy, match="could not be saved"):
        hub.start_replay(load_run(_run_obj()), "x.json")
    hub.start_replay(load_run(_run_obj()), "x.json", playing=False)  # asking again discards it
    hub.exit_replay()


def test_codes_and_key_in_the_run_reach_the_state(tmp_path):
    codes = {"read": True, "note": None, "mil": True, "stored": [{"code": "P0117", "desc": "d", "hint": "h", "known": True}], "pending": [], "permanent": []}
    obj = _run_obj(codes=codes)
    obj["vehicle"] = {"key": "9SXSMUL1-T"}
    hub, _, _ = make(tmp_path)
    hub.start_replay(load_run(obj), "x.json", playing=False)
    st = hub.state()
    assert st["codes"]["stored"][0]["code"] == "P0117" and st["codes"]["mil"] is True
    assert st["vehicle"]["key"] == "9SXSMUL1-T"
    hub.exit_replay()


def test_saved_run_carries_codes_mode06_and_the_partial_key_and_replays_them(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["codes"]["read"] and hub.state()["mode06"]["read"] and hub.state()["vehicle"] is not None)
    assert wait_for(lambda: hub.state()["seq"] >= 6)
    hub.stop()
    path = hub.save_run("trip")
    text = path.read_text()
    data = json.loads(text)
    assert data["codes"]["read"] is True and data["mode06"]["read"] is True and data["vehicle"] == {"key": vehicle_key(SIM_VIN)}
    assert SIM_VIN not in text and SIM_VIN[-6:] not in text, "the serial and the VIN never reach the file"
    hub2, _, _ = make(tmp_path)
    hub2.start_replay(load_run(data), path.name, playing=False)
    st = hub2.state()
    assert st["codes"]["stored"] == data["codes"]["stored"] and st["codes"]["mil"] == data["codes"]["mil"]
    assert st["mode06"]["results"] == data["mode06"]["results"] and st["vehicle"]["key"] == vehicle_key(SIM_VIN)
    hub2.exit_replay()


def test_huge_control_numbers_are_a_value_error(tmp_path):
    hub = _replay_hub(tmp_path)
    for kw in ({"pos": int("9" * 400)}, {"speed": int("9" * 400)}):
        with pytest.raises(ValueError):
            hub.replay_control("seek" if "pos" in kw else "speed", **kw)
    hub.exit_replay()


def test_a_seek_in_a_long_run_refills_only_the_last_minute(tmp_path):
    ts = [float(k) for k in range(1, 201)]
    obj = {"kind": "live_run", "live_sample": {"duration_s": 200.0, "rate_hz": 1.0, "series": {
        "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[t, t] for t in ts]}}}}
    hub, _, _ = make(tmp_path)
    hub.start_replay(load_run(obj), "long.json", playing=False)
    hub.replay_control("seek", pos=150.0)
    first = hub.state()["channels"]["0C"]["samples"][0]
    assert first[1] == 90.0, "the window is the 60 s before the seek point"
    assert hub.state()["seq"] == 61
    hub.exit_replay()


def test_live_stats_cover_every_sample_of_the_run_not_just_the_chart_buffer(tmp_path):
    sim = SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(s, sim=sim, max_buffer=5, autosave=False)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 12)
    hub.stop()
    vals = [v for _, _, v in hub._full["0C"]]
    st = hub.state()["stats"]["0C"]
    assert st["n"] == len(vals) > 5 and st["min"] == min(vals) and st["max"] == max(vals)
    assert st["avg"] == pytest.approx(sum(vals) / len(vals), abs=1e-3)


def test_replay_stats_cover_the_whole_run_from_the_start_and_after_a_seek(tmp_path):
    hub = _replay_hub(tmp_path)
    want = {"0C": {"n": 10, "min": 700.0, "max": 790.0, "avg": 745.0}, "AB": {"n": 10, "min": 0.0, "max": 9.0, "avg": 4.5}}
    core = lambda st: {p: {k: v[k] for k in ("n", "min", "max", "avg")} for p, v in st.items()}  # the original fields, unchanged
    assert hub.state()["seq"] == 0 and core(hub.state()["stats"]) == want
    hub._replay_advance(1.0)
    hub.replay_control("seek", pos=0.5)
    assert core(hub.state()["stats"]) == want
    hub.exit_replay()
    assert hub.state()["stats"] == {}


def _stat_obj():
    return {"kind": "live_run", "live_sample": {"duration_s": 5.0, "rate_hz": 1.0, "series": {
        "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[1.0, 10], [2.0, 30], [3.0, 20], [4.0, 30], [5.0, 10]]},
        "05": {"name": "coolant_temp", "unit": "C", "samples": [[2.0, 80], [4.0, 90]]},
        "0B": {"name": "intake_manifold_pressure", "unit": "kPa",
               "samples": [[1.0, 1e9 + 4], [2.0, 1e9 + 7], [3.0, 1e9 + 13], [4.0, 1e9 + 16]]}}}}


def test_stats_carry_std_sample_count_and_the_times_of_min_and_max(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start_replay(load_run(_stat_obj()), "s.json", playing=False)
    st = hub.state()["stats"]
    assert {k: st["0C"][k] for k in ("n", "min", "max", "avg", "std", "min_t", "max_t")} == \
        {"n": 5, "min": 10.0, "max": 30.0, "avg": 20.0, "std": 10.0, "min_t": 1.0, "max_t": 2.0}, "first time each extreme is reached"
    assert st["05"]["n"] == 2 and st["05"]["std"] == pytest.approx(7.0711, abs=1e-4)
    assert st["0B"]["std"] == pytest.approx(30 ** 0.5, abs=1e-4), "Welford: no cancellation on large values"
    hub.exit_replay()


def test_a_single_sample_has_zero_std(tmp_path):
    obj = {"kind": "live_run", "live_sample": {"duration_s": 1.0, "rate_hz": 1.0, "series": {
        "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[1.0, 700]]}}}}
    hub, _, _ = make(tmp_path)
    hub.start_replay(load_run(obj), "one.json", playing=False)
    assert hub.state()["stats"]["0C"]["std"] == 0.0
    hub.exit_replay()


def test_replay_last_seen_age_follows_the_replay_clock_per_channel(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start_replay(load_run(_stat_obj()), "s.json", playing=False)
    assert hub.state()["stats"]["0C"]["age"] is None, "nothing published yet"
    hub.replay_control("seek", pos=3.0)
    st = hub.state()["stats"]
    assert st["0C"]["age"] == 0.0 and st["05"]["age"] == 1.0, "the slow channel was last seen at 2.0 s"
    hub.replay_control("seek", pos=5.0)
    st = hub.state()["stats"]
    assert st["0C"]["age"] == 0.0 and st["05"]["age"] == 1.0 and st["0B"]["age"] == 1.0
    assert st["0C"]["n"] == 5 and st["0C"]["min_t"] == 1.0, "whole-run stats are not moved by a seek"
    hub.exit_replay()


def test_live_stats_age_and_extreme_times_match_the_samples(tmp_path):
    sim = SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(s, sim=sim, max_buffer=5, autosave=False)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 8)
    hub.stop()
    rows = hub._full["0C"]
    st = hub.state()
    s0 = st["stats"]["0C"]
    vals = [v for _, _, v in rows]
    assert s0["min_t"] == next(t for _, t, v in rows if v == min(vals)) and s0["max_t"] == next(t for _, t, v in rows if v == max(vals))
    mean = sum(vals) / len(vals)
    assert s0["std"] == pytest.approx((sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5, abs=1e-3)
    assert s0["age"] == pytest.approx(st["now"] - rows[-1][1], abs=0.1) and s0["age"] >= 0


from obd_reader.hub import EXTRA_PIDS, FAST_PIDS, slow_per_sweep


def test_slow_tier_takes_enough_per_sweep_for_its_target_rate_within_a_cap():
    assert slow_per_sweep(0, 2.5) == 0
    assert slow_per_sweep(26, 2.5) == 3, "26 slow PIDs at 2.5 Hz: 3 a sweep, each about every 3.5 s (0.29 Hz)"
    assert slow_per_sweep(2, 2.5) == 1
    assert slow_per_sweep(200, 2.5) == 4, "capped so the fast tier keeps its cadence"


def _capture_run(tmp_path, seconds=30):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=seconds, capture="all")
    return hub


def test_capture_all_polls_the_fast_tier_every_sweep_and_rotates_every_other_supported_pid(tmp_path):
    hub = _capture_run(tmp_path)
    assert wait_for(lambda: hub.state()["tiers"] is not None)
    tiers = hub.state()["tiers"]
    assert tiers["fast"] == FAST_PIDS == ["0C", "0D", "04", "11"] and tiers["slow_per_sweep"] == 1
    assert 16 <= len(tiers["slow"]) <= 26 and not set(tiers["slow"]) & set(FAST_PIDS)
    assert {"05", "06", "07", "42", "3C", "5C", "46"} <= set(tiers["slow"]), "every supported reading, not just the 8 defaults"
    assert wait_for(lambda: all(hub.state()["stats"].get(p) for p in tiers["slow"]), secs=10), "every slow PID gets read"
    hub.stop()
    st, sweeps = hub.state(), hub.state()["seq"]
    assert set(st["channels"]) == set(tiers["fast"]) | set(tiers["slow"])
    n = {p: st["stats"][p]["n"] for p in st["channels"]}
    assert all(n[p] == sweeps for p in FAST_PIDS), "fast tier: one sample per sweep"
    per_slow = sweeps / len(tiers["slow"])
    assert all(n[p] <= per_slow + 1 for p in tiers["slow"]), n
    assert max(n[p] for p in tiers["slow"]) < min(n[p] for p in FAST_PIDS) / 4


def test_default_start_is_unchanged_and_has_no_tiers(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 3)
    st = hub.state()
    assert st["tiers"] is None and set(DEFAULT_PIDS) <= set(st["channels"]) and len(st["channels"]) <= 16
    hub.stop()


def test_the_state_reports_the_capture_level_and_all_is_max(tmp_path):
    hub, _, _ = make(tmp_path)
    assert hub.state()["capture"] is None, "no run yet"
    for given, level in (("min", "min"), ("std", "std"), ("max", "max"), ("all", "max")):
        hub.start(DEFAULT_PIDS, hz=10, seconds=30, capture=given)
        assert wait_for(lambda: hub.state()["seq"] >= 1)
        assert hub.state()["capture"] == level
        hub.stop()
        assert wait_for(lambda: not hub.running)


def test_capture_min_reads_only_the_core_pids_and_the_supported_focus_pids_every_sweep(tmp_path):
    sim = SimPort("rich")
    sent, orig = [], sim.write
    sim.write = lambda data: (sent.append(data.decode("ascii").rstrip("\r")), orig(data))[1]
    hub, _, _ = make(tmp_path, sim=sim)
    hub.set_focus(["0F", "3E", "5C", "0C"])  # 0F: not in this car's bitmap; 0C: already core
    hub.start(DEFAULT_PIDS, hz=10, seconds=30, capture="min")
    assert wait_for(lambda: hub.state()["seq"] >= 4)
    st = hub.state()
    assert st["extras"] == ["3E", "5C"] and set(st["channels"]) == set(DEFAULT_PIDS) | {"3E", "5C"}
    assert wait_for(lambda: hub.state()["stats"]["5C"]["n"] >= 3), "focus PIDs are read every sweep, not rotated"
    hub.set_focus([])  # the old focus-only PIDs are dropped on the next sweep
    assert wait_for(lambda: hub.state()["extras"] == [])
    hub.stop()
    rotating = {"01" + p for p in EXTRA_PIDS if p not in DEFAULT_PIDS} - {"013E", "015C"}
    assert not rotating & set(sent), "no rotating extras"


def test_std_still_rotates_extras_and_reports_its_level(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30, capture="std")
    assert wait_for(lambda: hub.state()["seq"] >= 3)
    st = hub.state()
    assert st["capture"] == "std" and st["extras"] and st["tiers"] is None
    hub.stop()


def test_a_bad_capture_mode_is_refused_before_any_traffic(tmp_path):
    hub, _, _ = make(tmp_path)
    for bad in ("everything", "default", "ALL", 1, None, ["all"]):
        with pytest.raises(LiveLimitError):
            hub.start(DEFAULT_PIDS, capture=bad)
    assert not hub.running


def test_capture_all_without_a_support_bitmap_falls_back_to_the_given_pids(tmp_path):
    class _NoBitmap(SimPort):
        def write(self, data):
            super().write(data)
            if data.decode().rstrip("\r") in ("0100", "0120", "0140"):
                self._pending = "NO DATA\r"
    hub, _, _ = make(tmp_path, sim=_NoBitmap("rich"))
    hub.start(DEFAULT_PIDS, hz=10, seconds=30, capture="all")
    assert wait_for(lambda: hub.state()["seq"] >= 3)
    st = hub.state()
    assert st["tiers"] is None and set(st["channels"]) == set(DEFAULT_PIDS)
    hub.stop()


def test_a_mixed_rate_capture_saves_and_replays_every_channel_at_its_own_times(tmp_path):
    hub = _capture_run(tmp_path)
    assert wait_for(lambda: hub.state()["seq"] >= 40, secs=10)
    hub.stop()
    full = {p: [(t, v) for _, t, v in rows] for p, rows in hub._full.items() if rows}
    data = json.loads(hub.save_run("mixed").read_text())
    saved = {p: [tuple(x) for x in s["samples"]] for p, s in data["live_sample"]["series"].items() if s["samples"]}
    assert saved == full
    run = load_run(data)
    assert any(len(vals) < len(run.names) for _, vals in run.sweeps), "sparse sweeps: a slow channel is absent from most"
    for p, rows in full.items():
        assert [(t, vals[p]) for t, vals in run.sweeps if p in vals] == rows, p
    hub2, _, _ = make(tmp_path)
    hub2.start_replay(run, "mixed.json", playing=False)
    st = hub2.state()["stats"]
    assert {p: st[p]["n"] for p in full} == {p: len(rows) for p, rows in full.items()}
    hub2.replay_control("seek", pos=run.duration)
    ch = hub2.state()["channels"]
    assert all([s[1:] for s in ch[p]["samples"]] == [list(r) for r in full[p] if r[0] >= run.duration - 60] for p in full)
    hub2.exit_replay()


def test_an_old_rectangular_run_file_still_loads_and_replays_every_sweep(tmp_path):
    obj = _run_obj()  # the pre-capture format: every channel at every sweep time
    run = load_run(obj)
    assert len(run.sweeps) == 10 and all(set(vals) == {"0C", "AB"} for _, vals in run.sweeps)
    hub, _, _ = make(tmp_path)
    hub.start_replay(run, "old.json", playing=False)
    hub.replay_control("seek", pos=run.duration)
    assert hub.state()["seq"] == 10 and hub.state()["stats"]["0C"]["n"] == 10
    hub.exit_replay()


class _HondaSim(SimPort):
    """A car whose VIN has the Ridgeline fixture's WMI (5FP) and that stores P3400."""
    def write(self, data: bytes) -> None:
        super().write(data)
        cmd = data.decode("ascii").rstrip("\r")
        if cmd == "03":
            self._pending = "43 01 34 00\r"
        elif cmd == "0902":
            from obd_reader.vin import with_check_digit
            b = [0x49, 0x02, 0x01] + list(with_check_digit("5FPYK3F5?RB000001").encode("ascii"))
            fr = lambda chunk: " ".join(f"{x:02X}" for x in chunk)
            self._pending = "\r".join(["014", "0: " + fr(b[:6]), "1: " + fr(b[6:13]), "2: " + fr(b[13:20])]) + "\r"


def test_a_honda_car_gets_the_honda_meaning_of_a_make_specific_code(tmp_path):
    c = _codes_after_start(tmp_path, None, sim=_HondaSim("rich"))
    assert c["stored"][0]["code"] == "P3400" and "deactivation" in c["stored"][0]["desc"] and c["stored"][0]["known"]

# ---- trust fixes: an unanswered request is never "no codes", "lamp off" or a passed Mode 06 ---------
class _SilentSim(SimPort):
    """A simulated car that answers NO DATA to the commands in `silent` (everything else as usual)."""
    def __init__(self, scenario, silent):
        super().__init__(scenario)
        self.silent = set(silent)

    def write(self, data: bytes) -> None:
        super().write(data)
        if data.decode("ascii").rstrip("\r") in self.silent:
            self._pending = "NO DATA\r"


def _state_when(tmp_path, sim, cond):
    hub, _, _ = make(tmp_path, sim=sim)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: cond(hub.state()))
    st = hub.state()
    hub.stop()
    return st


def test_no_answer_to_any_code_request_is_not_read_and_the_lamp_is_unknown(tmp_path):
    st = _state_when(tmp_path, _SilentSim("rich", ["03", "07", "0A", "0101"]), lambda s: s["codes"]["note"])
    c = st["codes"]
    assert c["read"] is False and "did not answer" in c["note"] and c["mil"] is None


def test_one_unanswered_list_is_named_and_the_answered_ones_are_kept(tmp_path):
    st = _state_when(tmp_path, _SilentSim("rich", ["07"]), lambda s: s["codes"]["read"])
    c = st["codes"]
    assert c["unanswered"] == ["pending"] and c["pending"] == [] and [x["code"] for x in c["stored"]] == ["P0117", "P0172"]
    assert c["mil"] is True


def test_an_unanswered_lamp_bit_is_null_not_off(tmp_path):
    st = _state_when(tmp_path, _SilentSim("healthy", ["0101"]), lambda s: s["codes"]["read"])
    assert st["codes"]["mil"] is None and st["codes"]["unanswered"] == ["mil"] and st["codes"]["stored"] == []


def test_an_empty_answer_is_an_empty_list_with_nothing_unanswered(tmp_path):
    c = _codes_after_start(tmp_path, "healthy")
    assert c["unanswered"] == [] and c["mil"] is False


def test_mode06_with_no_answer_is_not_read_and_says_so(tmp_path):
    st = _state_when(tmp_path, _SilentSim("rich", ["0600"]), lambda s: s["mode06"]["note"])
    assert st["mode06"]["read"] is False and "did not answer" in st["mode06"]["note"] and st["mode06"]["results"] == []


def test_mode06_monitors_without_results_are_read_with_no_results(tmp_path):
    st = _state_when(tmp_path, _SilentSim("rich", ["0601", "0621"]), lambda s: s["mode06"]["read"])
    assert st["mode06"]["mids"] == ["01", "21"] and st["mode06"]["results"] == []


def test_a_replayed_simulation_says_so(tmp_path):
    obj = _run_obj()
    obj["demo"] = True
    hub, _, _ = make(tmp_path)
    hub.start_replay(load_run(obj), "sim.json", playing=False)
    assert hub.state()["replay"]["demo"] is True and hub.state()["demo"] is False
    hub.exit_replay()


def test_a_scenario_chosen_mid_run_gets_its_supported_pids_read_and_never_one_the_bitmap_lacks(tmp_path):
    sim = SimPort("rich")
    sent, orig = [], sim.write
    sim.write = lambda data: (sent.append(data.decode("ascii").rstrip("\r")), orig(data))[1]
    hub, _, _ = make(tmp_path, sim=sim)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 3)
    assert "3E" not in hub.state()["extras"]  # not one of the default extras on this car
    hub.set_focus(["0F", "3e", "5C", "0C"])  # 0F: not in this car's bitmap; 0C: already a core channel
    assert wait_for(lambda: hub.state()["channels"].get("3E", {}).get("samples"))
    st = hub.state()
    hub.stop()
    assert st["focus"] == ["0F", "3E", "5C", "0C"] and st["extras"][:2] == ["3E", "5C"] and len(DEFAULT_PIDS) + len(st["extras"]) <= 16
    assert "0F" not in st["supported"] and "3E" in st["supported"] and "0F" not in st["channels"]
    assert "010F" not in sent, "a PID the car does not list is never asked for"


@pytest.mark.parametrize("bad", ["0C", ["0C\r04"], ["ATZ"], [5], [f"{i:02X}" for i in range(9)]])
def test_focus_takes_only_a_short_list_of_hex_pids(tmp_path, bad):
    hub, _, _ = make(tmp_path)
    with pytest.raises(LiveLimitError):
        hub.set_focus(bad)


def test_readiness_and_freeze_frame_are_read_once_with_the_codes_and_carried_in_state(tmp_path):
    st = _state_when(tmp_path, SimPort("rich"), lambda s: s["freeze_frame"]["read"])
    r, ff = st["readiness"], st["freeze_frame"]
    assert r["read"] is True and r["mil"] is True and r["dtc_count"] == 2 and r["ignition"] == "spark"
    assert r["monitors"]["evap"] == {"supported": True, "complete": False} and r["monitors"]["catalyst"]["complete"] is True
    assert r["monitors"]["secondary_air"] == {"supported": False, "complete": None}
    assert ff["dtc"] == "P0117" and ff["pids"]["05"]["value"] == 38 and ff["pids"]["05"]["unit"] == "C"
    assert ff["pids"]["03"]["label"] == "Open loop, engine cold"


def test_no_stored_code_means_no_freeze_frame_request_and_it_says_so(tmp_path):
    st = _state_when(tmp_path, SimPort("healthy"), lambda s: s["freeze_frame"]["note"])
    assert st["freeze_frame"] == {"read": False, "note": "not requested: no stored code"} and st["readiness"]["read"] is True


def test_unanswered_readiness_and_freeze_frame_are_not_read_never_empty(tmp_path):
    st = _state_when(tmp_path, _SilentSim("rich", ["0101", "020200"]), lambda s: s["freeze_frame"]["note"])
    assert st["readiness"] == {"read": False, "note": "the car did not answer the readiness request (Mode 01 PID 01)"}
    assert st["freeze_frame"] == {"read": False, "note": "the car did not answer the freeze-frame request"}


def test_saved_run_replays_readiness_and_freeze_frame_and_an_old_file_says_not_in_this_recording(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["freeze_frame"]["read"] and hub.state()["seq"] >= 4)
    hub.stop()
    data = json.loads(hub.save_run("trip").read_text())
    hub2, _, _ = make(tmp_path)
    hub2.start_replay(load_run(data), "a.json", playing=False)
    st = hub2.state()
    assert st["readiness"] == data["readiness"] and st["freeze_frame"] == data["freeze_frame"] and st["freeze_frame"]["dtc"] == "P0117"
    hub2.start_replay(load_run(_run_obj()), "old.json", playing=False)
    st = hub2.state()
    assert st["readiness"] == st["freeze_frame"] == {"read": False, "note": "not in this recording"}
    hub2.exit_replay()


def test_console_falls_back_to_a_pinned_protocol_when_automatic_search_finds_nothing(tmp_path):
    sim = SimPort("rich")
    sim.sent, pinned = [], []
    orig = sim.write

    def write(data):
        orig(data)
        cmd = data.decode().strip()
        sim.sent.append(cmd)
        if cmd.startswith("ATSP"):
            pinned[:] = [cmd[4:]]
        elif cmd == "ATDP":
            sim._pending = "SAE J1850 VPW\r"
        elif cmd.startswith("01") and pinned != ["2"]:
            sim._pending = "SEARCHING...\rUNABLE TO CONNECT\r"
    sim.write = write
    hub, _, _ = make(tmp_path, sim=None, port_factory=lambda: sim)
    hub._sim = None
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 2)
    hub.stop()
    assert [c for c in sim.sent if c.startswith("ATSP")][:6] == ["ATSP0", "ATSP6", "ATSP8", "ATSP7", "ATSP9", "ATSP2"]


def test_legacy_protocol_reads_mode06_with_the_one_limit_layout(tmp_path):
    sim = _sim_with({"ATDP": "SAE J1850 VPW\r", "0600": "46 00 FF 40 00 00 00\r",
                     "0602": "46 02 D0 80 03 80 6E\r46 02 0A 00 10 05 AA\r"})
    hub, _, _ = make(tmp_path, sim=None, port_factory=lambda: sim)
    hub._sim = None
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["mode06"]["read"])
    m = hub.state()["mode06"]
    hub.stop()
    assert m["layout"] == "legacy" and m["mids"] == ["02"]
    assert m["results"] == [{"tid": "02", "component": "50", "value": 0x8003, "limit": 0x806E, "limit_type": "min"},
                            {"tid": "02", "component": "0A", "value": 0x10, "limit": 0x5AA, "limit_type": "max"}]
