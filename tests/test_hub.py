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
