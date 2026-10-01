from obd_reader.hub import DEFAULT_PIDS, EXTRA_PIDS
from obd_reader.pids import PIDS
from obd_reader.stat_help import HELP, MODE06

FIELDS = {"title", "measures", "use", "typical", "status"}
GROUPS = {"o2_sensor", "o2_heater", "catalyst", "egr_vvt", "evap", "misfire", "fuel_system", "other"}


def _complete(key, e):
    assert FIELDS <= set(e), key
    assert isinstance(e["use"], list) and 2 <= len(e["use"]) <= 3, key
    assert all(isinstance(x, str) and x for x in [e["title"], e["measures"], e["typical"], *e["use"]]), key
    assert e["status"] == ["model_drafted", "unreviewed"], key


def test_default_and_leading_extra_pids_have_complete_entries():
    for pid in DEFAULT_PIDS + EXTRA_PIDS[:16]:
        _complete(pid, HELP[pid])


def test_every_catalog_key_is_a_decodable_pid():
    assert set(HELP) <= set(PIDS)


def test_mode06_groups_are_complete():
    assert set(MODE06) == GROUPS
    for g, e in MODE06.items():
        _complete(g, e)


def test_watch_ranges_are_well_formed_and_nested():
    seen = 0
    for pid, e in HELP.items():
        for key in ("watch", "watch_engine_off"):
            w = e.get(key)
            if w is None:
                continue
            seen += 1
            ok, out = w["ok"], w["out"]
            assert len(ok) == len(out) == 2, (pid, key)
            for r in (ok, out):
                assert r[0] is None or r[1] is None or r[0] <= r[1], (pid, key)
            assert out[0] is None or (ok[0] is not None and out[0] <= ok[0]), (pid, key)
            assert out[1] is None or (ok[1] is not None and ok[1] <= out[1]), (pid, key)
    assert seen >= 7  # four trims, coolant, battery (running and engine off)
    assert "watch_engine_off" in HELP["42"] and all("watch" in HELP[p] for p in ("05", "06", "07", "08", "09", "42"))
    assert "watch" not in HELP["04"] and "watch" not in HELP["0B"]


def test_engine_off_battery_band_is_open_above_so_charging_is_never_flagged():
    # hybrids and start-stop pauses read rpm 0 while charging at 14 V; surface charge after shutdown reads 13+ V
    w = HELP["42"]["watch_engine_off"]
    assert w["ok"][1] is None and w["out"][1] is None and w["ok"][0] is not None and w["out"][0] is not None


def test_metric_numbers_in_the_help_text_come_with_us_equivalents():
    import re
    for pid, e in HELP.items():
        text = " ".join([e["measures"], e["typical"], *e["use"]])
        assert not re.search(r"\d C\b", text), f"{pid}: write temperatures as degrees C"
        if "°C" in text:
            assert "°F" in text, pid
        if "kPa" in text:
            assert "inHg" in text, pid
