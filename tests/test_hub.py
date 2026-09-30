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
    assert st["status"] == "running" and st["demo"] is True and set(st["channels"]) == set(DEFAULT_PIDS)
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
