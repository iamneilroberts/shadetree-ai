import pytest

from obd_reader.pids import decode_pid
from obd_reader.simulator import SCENARIOS, SimPort
from obd_reader.transport import Transport

from conftest import FakeClock

PIDS8 = ["0C", "05", "06", "07", "08", "09", "0B", "42"]


def sweep(sim, t):
    vals = {}
    for pid in PIDS8:
        lines = t.send(f"01{pid}")
        raw = bytes.fromhex(lines[0].replace(" ", ""))
        assert raw[0] == 0x41 and raw[1] == int(pid, 16)
        vals[pid] = decode_pid(pid, raw[2:]).value
    return vals


def run(scenario, seconds=30, rev=False):
    clk = FakeClock()
    sim = SimPort(scenario, clock=clk.now)
    sim.rev = rev
    t = Transport(sim)
    out = []
    for _ in range(int(seconds / 0.4)):
        clk.sleep(0.4)
        out.append(sweep(sim, t))
    return out


def test_every_scenario_stays_in_physical_ranges():
    for sc in SCENARIOS:
        for rev in (False, True):
            for v in run(sc, rev=rev):
                assert 400 <= v["0C"] <= 3200 and 20 <= v["05"] <= 110
                for p in ("06", "07", "08", "09"):
                    assert -30 <= v[p] <= 30
                assert 20 <= v["0B"] <= 110 and 11 <= v["42"] <= 15


def test_rich_scenario_reads_a_cold_coolant_and_negative_trims_at_idle_and_at_2500():
    idle, rev = run("rich")[-10:], run("rich", rev=True)[-10:]
    for rows in (idle, rev):
        assert all(r["05"] < 50 for r in rows)
        assert all(r["07"] < -15 and r["09"] < -15 for r in rows)


def test_lean_scenario_trims_fade_as_load_rises():
    idle, rev = run("lean")[-10:], run("lean", rev=True)[-10:]
    assert all(r["07"] > 10 for r in idle) and all(r["07"] < 8 for r in rev)


def test_healthy_scenario_has_small_trims_and_a_warm_engine():
    rows = run("healthy", seconds=60)[-10:]
    assert all(abs(r["07"]) < 5 and abs(r["09"]) < 5 for r in rows) and all(r["05"] > 80 for r in rows)


def test_rev_moves_engine_speed_to_about_2500():
    assert 2300 < run("healthy", rev=True)[-1]["0C"] < 2700
    assert run("healthy")[-1]["0C"] < 900


def test_non_pid_commands_and_unsupported_pids():
    t = Transport(SimPort())
    assert t.send("ATE0") == ["OK"]
    assert t.send("ATDP") == ["SIMULATED (no car)"]
    assert t.send("STI") == ["?"]
    assert t.send("0110") == ["NO DATA"]


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError):
        SimPort("bogus")
    with pytest.raises(ValueError):
        SimPort().set_scenario("bogus")


def _codes(scenario, cmd):
    t = Transport(SimPort(scenario))
    return t.send(cmd)


def test_rich_car_reports_two_stored_and_one_pending_code_and_the_lamp_is_on():
    assert _codes("rich", "03") == ["43 02 01 17 01 72"]
    assert _codes("rich", "07") == ["47 01 01 75"]
    assert _codes("rich", "0A") == ["4A 00"]
    assert _codes("rich", "0101")[0].startswith("41 01 82")


def test_lean_car_codes_and_healthy_car_has_none():
    assert _codes("lean", "03") == ["43 02 01 71 01 74"]
    assert _codes("lean", "07") == ["47 01 01 01"]
    assert _codes("healthy", "03") == ["43 00"]
    assert _codes("healthy", "0101")[0].startswith("41 01 00")


def test_support_bitmaps_chain_to_the_next_page_and_name_the_extra_readings():
    t = Transport(SimPort())
    first = t.send("0100")[0].split()
    assert first[:2] == ["41", "00"] and int(first[5], 16) & 1  # more pages follow
    page2 = bytes.fromhex("".join(t.send("0120")[0].split()[2:]))
    assert page2[-1] & 1  # PID 40 page is supported too (control module voltage, equivalence ratio)


def test_mode06_answers_two_monitors():
    t = Transport(SimPort())
    assert t.send("0600")[0].startswith("46 00") and t.send("0621")[0].startswith("46 21")


def test_sim_answers_the_vin_request_in_multi_frame_layout_and_it_parses():
    from obd_reader.elm import parse_all
    from obd_reader.simulator import SIM_VIN
    from obd_reader.snapshot import VIN_RE
    lines = Transport(SimPort()).send("0902")
    assert lines[0] == "014" and lines[1].startswith("0: 49 02 01")
    payload = parse_all(lines, 0x49)[0]
    assert payload[3:20].decode("ascii") == SIM_VIN and VIN_RE.fullmatch(SIM_VIN)
