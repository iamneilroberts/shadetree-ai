"""GM's J1850 (Class 2) Mode $06 table: names, limit types, scaling and help. Values are the rows a 2003 GMC truck
returned on 2026-10-04 (no VIN in them)."""
import re

from obd_reader import gm_mode06 as gm

TRUCK = [  # (tid, component, value, limit, limit_type) as mode06.parse_legacy gave them
    ("02", "04", 0, 0, "min"), ("02", "66", 32771, 32838, "max"), ("02", "36", 0, 0, "max"),
    ("02", "06", 32768, 32768, "min"), ("02", "50", 32771, 32878, "min"), ("02", "60", 33218, 33218, "max"),
    ("02", "30", 40, 40, "min"), ("02", "40", 0, 0, "min"), ("02", "11", 0, 0, "min"), ("02", "21", 0, 0, "max"),
    ("02", "71", 32768, 32768, "max"), ("05", "0A", 16, 1450, "max"), ("05", "4A", 21, 1450, "max"),
    ("0A", "09", 0, 0, "max"), ("0C", "60", 30239, 32809, "max"), ("0C", "70", 31713, 32809, "max"),
    ("0E", "11", 0, 8, "max"), ("0E", "12", 0, 8, "max"), ("0E", "21", 0, 8, "max"), ("0E", "22", 0, 8, "max"),
]


def row(t):
    return dict(zip(("tid", "component", "value", "limit", "limit_type"), t))


def test_every_row_the_truck_returned_is_in_gms_table_with_the_same_limit_type():
    # The limit type came from bit 7 of the component id; GM's table agrees for every one of these rows.
    for t in TRUCK:
        assert "name" in gm.annotate(row(t)), t


def test_weak_vacuum_row_scales_to_the_failing_reading():
    r = gm.annotate(row(("02", "50", 32771, 32878, "min")))
    assert r["name"] == "Weak vacuum, pass test 1" and r["monitor"] == "EVAP monitor, 0.040 in leak"
    assert (r["value_s"], r["limit_s"], r["unit"]) == (0.3, 11.0, "in H2O")
    assert r["value"] == 32771 and r["help"] == "gm:02:50:min"  # the raw number is kept


def test_scaling_modes():
    assert gm.scale(30239, "s_cat", "o") == -2.529  # offset 32768
    assert gm.scale(0xFFFF, "inh2o", "s") == -0.1  # signed
    assert gm.scale(40, "s10", "u") == 4.0
    assert gm.scale(5, "amps", "u") is None  # GM gives no scaling we can apply


def test_unknown_rows_pass_through_unchanged():
    r = row(("02", "7E", 1, 2, "max"))
    assert gm.annotate(r) == r


def test_bit7_listed_duplicates_collapse_to_one_key():
    assert gm.TESTS[("05", "05", "min")][0] == "Rich-to-lean switch time, B1S1, too fast"  # GM lists it as 05 and 85


def test_help_exists_for_every_test_and_cites_gm():
    assert set(gm.HELP) == {gm.help_key(*k) for k in gm.TESTS}
    for k, h in gm.HELP.items():
        assert h["status"] == ["model_drafted", "unreviewed"] and "Source: GM" in h["use"][-1]
        assert h["typical"] and h["measures"] and h["title"]


def test_is_gm_by_wmi():
    assert gm.is_gm("3GKEC16Z-3") and gm.is_gm("1GCEK19T-5")
    assert not gm.is_gm("5FPYK3F5-R") and not gm.is_gm(None)


def test_no_vin_shaped_text():
    import json
    assert not re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", json.dumps(gm.HELP) + json.dumps(gm.MONITORS))
