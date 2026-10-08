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
                assert 400 <= v["0C"] <= 3200 and (20 <= v["05"] <= 110 or (sc == "rich" and v["05"] == -40))
                for p in ("06", "07", "08", "09"):
                    assert -30 <= v[p] <= 30
                assert 20 <= v["0B"] <= 110 and 11 <= v["42"] <= 15


def test_rich_scenario_is_a_coolant_sensor_reading_cold_on_a_warm_engine_in_open_loop():
    # one story: P0118 (reads cold), open loop "engine cold", no short-term correction, normal learned trims
    idle, rev = run("rich")[-10:], run("rich", rev=True)[-10:]
    for rows in (idle, rev):
        assert all(r["05"] == -40 for r in rows)
        assert all(r["06"] == 0 and r["08"] == 0 and abs(r["07"]) < 5 and abs(r["09"]) < 5 for r in rows)
    t = Transport(SimPort("rich"))
    assert t.send("0103") == ["41 03 01 00"]  # open loop, engine cold
    assert decode_pid("44", bytes.fromhex(t.send("0144")[0].split(" ", 2)[2].replace(" ", ""))).value < 0.9  # enriched


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


def test_rich_car_reports_p0118_stored_and_permanent_and_the_lamp_is_on():
    assert _codes("rich", "03") == ["43 01 01 18"]
    assert _codes("rich", "07") == ["47 00"]
    assert _codes("rich", "0A") == ["4A 01 01 18"]
    assert _codes("rich", "0101")[0].startswith("41 01 81")


def test_lean_car_codes_and_healthy_car_has_none():
    assert _codes("lean", "03") == ["43 02 01 71 01 74"]
    assert _codes("lean", "07") == ["47 00"]
    assert _codes("healthy", "0A") == ["4A 00"]
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


def test_sim_mirrors_the_ridgeline_supported_set_and_answers_each_one():
    from obd_reader.elm import decode_supported, parse_all
    from obd_reader.pids import PIDS
    from obd_reader.simulator import RAW_ONLY
    pcm = ("01 03 04 06 07 08 09 0B 0C 0D 0E 11 13 15 19 1C 1F 21 23 24 28 2C 2D 2E 2F 30 31 33 3C 3D 41 42 43 44 47 49 4A "
           "51 55 56 57 58 62 63 66 67 68 6C 8E 9D 9E 9F A3 A6").split()
    ecu2 = "01 04 05 0C 0D 11 1F 21 30 31 33 41 42 45 47 49 4A".split()
    t = Transport(SimPort())
    per_ecu: list[set] = [set(), set()]
    for base in range(0x00, 0xC1, 0x20):
        for i, p in enumerate(parse_all(t.send(f"01{base:02X}"), 0x41)):
            per_ecu[i] |= {x for x in decode_supported(base, p[2:6]) if int(x, 16) % 0x20}
    assert per_ecu == [set(pcm), set(ecu2)]
    assert not {"14", "3E", "46", "5C"} & per_ecu[0]  # the real car does not report these
    for pid in sorted(set(pcm + ecu2) - {"01"}):
        raw = bytes.fromhex(t.send(f"01{pid}")[0].replace(" ", ""))
        assert raw[:2] == bytes([0x41, int(pid, 16)]), pid
        assert decode_pid(pid, raw[2:]) is not None if pid in PIDS else pid in RAW_ONLY, pid


def test_healthy_warm_idle_matches_the_ridgeline_it_is_modelled_on():
    clk = FakeClock()
    t = Transport(SimPort("healthy", clock=clk.now))
    rows = []
    for _ in range(60):
        clk.sleep(0.4)
        rows.append({p: decode_pid(p, bytes.fromhex(t.send(f"01{p}")[0].replace(" ", ""))[2:]).value
                     for p in ("0C", "04", "05", "0B", "0E", "42", "06", "07", "24", "44", "23", "66", "67", "68")})
    med = lambda p: sorted(r[p] for r in rows[10:])[25]  # noqa: E731
    assert 715 <= med("0C") <= 732 and 23.5 <= med("04") <= 24.7 and med("05") == med("67") == 88 and med("0B") == 32
    assert 4.0 <= med("0E") <= 5.5 and 14.38 <= med("42") <= 14.51 and 3.9 <= med("06") <= 5.5 and med("07") == 3.1
    assert 0.986 <= med("24") <= 1.015 and 0.987 <= med("44") <= 1.008 and 3450 <= med("23") <= 3590
    assert 2 < med("66") < 6 and 20 < med("68") < 40  # no live read of 66 or 68 exists: model numbers


def test_each_fault_freeze_frame_tells_the_same_story_as_its_codes():
    def frame(sc):
        t = Transport(SimPort(sc))
        dtc = t.send("020200")[0].split()[3:]
        vals = {}
        for pid in ("03", "05", "06", "07"):
            raw = bytes.fromhex(t.send(f"02{pid}00")[0].replace(" ", ""))
            vals[pid] = decode_pid(pid, raw[3:]).value
        return "P" + "".join(dtc), vals
    code, ff = frame("rich")  # coolant sensor reads cold: open loop (engine cold), STFT 0, LTFT normal
    assert code == "P0118" and ff["03"] == 1 and ff["05"] == -40 and ff["06"] == 0 and abs(ff["07"]) < 5
    code, ff = frame("lean")  # vacuum leak: closed loop, warm, high positive trims
    assert code == "P0171" and ff["03"] == 2 and ff["05"] > 80 and ff["06"] > 0 and ff["07"] > 10
