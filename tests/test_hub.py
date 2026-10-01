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


def test_set_sim_only_in_demo(tmp_path):
    hub, _, sim = make(tmp_path)
    hub.set_sim(scenario="lean", rev=True)
    assert sim.scenario == "lean" and sim.rev is True
    with pytest.raises(ValueError):
        hub.set_sim(scenario="bogus")
    real = LiveHub(Session(Config(port="x", home=tmp_path), port_factory=lambda: ScriptedPort({})))
    with pytest.raises(ValueError):
        real.set_sim(rev=True)


def _codes_after_start(tmp_path, scenario):
    hub, _, _ = make(tmp_path, sim=SimPort(scenario))
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


def test_non_can_protocol_skips_code_decoding_and_says_why(tmp_path):
    sim = SimPort("rich")
    orig = sim.write

    def write(data):
        orig(data)
        if data.decode().strip() == "ATDP":
            sim._pending = "AUTO, SAE J1850 PWM\r"
    sim.write = write
    hub, _, _ = make(tmp_path, sim=None, port_factory=lambda: sim)
    hub._sim = None  # behave like a real adapter: only a CAN protocol name enables code decoding
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["codes"]["note"])
    st = hub.state()["codes"]
    hub.stop()
    assert st["read"] is False and "not supported" in st["note"]


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
    assert st["replay"] == {"name": "drive.json", "duration": 4.0, "pos": 0.0, "speed": 1.0, "playing": False, "ended": False}
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
