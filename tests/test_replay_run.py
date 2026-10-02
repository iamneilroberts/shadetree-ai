import copy
import json
import os

import pytest

from obd_reader import replay_run as rr


def run_obj():
    return {"kind": "live_run", "demo": False, "adapter": {"protocol": "ISO 15765-4 (CAN 29/500)"},
            "live_sample": {"duration_s": 1.2, "rate_hz": 2.5, "series": {
                "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[0.4, 700], [0.8, 720], [1.2, 710]]},
                "05": {"name": "coolant_temp", "unit": "C", "samples": [[0.4, 80], [0.8, 81], [1.2, 82]]}}}}


def test_a_good_run_loads_and_groups_samples_into_sweeps():
    r = rr.load_run(run_obj())
    assert r.duration == 1.2 and r.rate_hz == 2.5 and r.protocol == "ISO 15765-4 (CAN 29/500)"
    assert r.sweeps[0] == (0.4, {"0C": 700.0, "05": 80.0}) and len(r.sweeps) == 3
    assert r.names["0C"] == ("engine_rpm", "rpm")
    assert r.codes is None and r.mode06 is None and r.vehicle is None


def test_readings_sampled_at_different_times_still_group_by_timestamp():
    o = run_obj()
    o["live_sample"]["series"]["05"]["samples"] = [[0.4, 80], [1.2, 82]]
    r = rr.load_run(o)
    assert r.sweeps[1] == (0.8, {"0C": 720.0}) and r.sweeps[2][1] == {"0C": 710.0, "05": 82.0}


def test_window_and_index_helpers():
    r = rr.load_run(run_obj())
    assert r.index_after(0.0) == 0 and r.index_after(0.8) == 2 and r.index_after(5.0) == 3
    assert r.first_in_window(1.2, 0.5) == 1 and r.first_in_window(1.2, 60) == 0


def _bad(mutate):
    o = run_obj()
    mutate(o)
    return o


BAD = {
    "wrong kind": _bad(lambda o: o.update(kind="snapshot")),
    "not a dict": [],
    "no series": _bad(lambda o: o["live_sample"].update(series={})),
    "bad reading id": _bad(lambda o: o["live_sample"]["series"].update({"zz": {"name": "x", "unit": None, "samples": [[1, 1]]}})),
    "lowercase id": _bad(lambda o: o["live_sample"]["series"].update({"0c": {"name": "x", "unit": None, "samples": [[1, 1]]}})),
    "nan value": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([2.0, float("nan")])),
    "inf time": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([float("inf"), 1])),
    "bool value": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([2.0, True])),
    "negative time": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([-1, 1])),
    "time too large": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([86401, 1])),
    "bad pair": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([1, 2, 3])),
    "long name": _bad(lambda o: o["live_sample"]["series"]["0C"].update(name="x" * 81)),
    "no samples": _bad(lambda o: [s.update(samples=[]) for s in o["live_sample"]["series"].values()]),
    "too many readings": _bad(lambda o: o["live_sample"].update(series={f"{i:02X}": {"name": "x", "unit": None, "samples": [[1, 1]]} for i in range(65)})),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_malformed_runs_are_rejected_with_a_message(name):
    with pytest.raises(ValueError):
        rr.load_run(copy.deepcopy(BAD[name]))


def test_too_many_samples_are_rejected(monkeypatch):
    monkeypatch.setattr(rr, "MAX_SAMPLES", 5)
    with pytest.raises(ValueError, match="too many"):
        rr.load_run(run_obj())


def test_optional_fields_are_whitelisted_and_bad_ones_dropped():
    o = run_obj()
    o["codes"] = {"read": True, "note": None, "mil": True, "extra": "x",
                  "stored": [{"code": "P0117", "desc": "d", "hint": "h", "known": True, "junk": 1}], "pending": [], "permanent": []}
    o["mode06"] = {"read": True, "mids": ["3A"], "results": [{"mid": "3A", "tid": "01", "uasid": "10", "value": 1, "minimum": 0, "maximum": 5, "within_limits": True}]}
    o["vehicle"] = {"key": "9SXSMUL1-T", "vin": "SHOULD-NOT-SURVIVE"}
    r = rr.load_run(o)
    assert r.codes == {"read": True, "note": None, "stored": [{"code": "P0117", "desc": "d", "hint": "h", "known": True}],
                       "pending": [], "permanent": [], "mil": True}
    assert r.mode06["results"][0] == {"mid": "3A", "tid": "01", "uasid": "10", "value": 1, "minimum": 0, "maximum": 5, "within_limits": True}
    assert r.vehicle == {"key": "9SXSMUL1-T", "known": False, "runs": 0, "note": None}
    o["codes"]["stored"][0]["code"] = "not a code"
    o["mode06"]["results"][0]["value"] = "x"
    o["vehicle"]["key"] = "lowercase-key"
    r = rr.load_run(o)
    assert r.codes is None and r.mode06 is None and r.vehicle is None


def _put(d, name, obj, mtime=None):
    p = d / name
    p.write_text(json.dumps(obj))
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def test_read_run_file_accepts_only_plain_names_inside_the_folder(tmp_path):
    _put(tmp_path, "a-run.json", run_obj())
    assert rr.read_run_file(tmp_path, "a-run.json")["kind"] == "live_run"
    for bad in ("../a-run.json", "a/b.json", "", "a-run.txt", "x" * 101 + ".json", None, 5):
        with pytest.raises(ValueError):
            rr.read_run_file(tmp_path, bad)
    with pytest.raises(FileNotFoundError):
        rr.read_run_file(tmp_path, "missing.json")


def test_symlinks_and_oversize_files_are_refused(tmp_path, monkeypatch):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(run_obj()))
    d = tmp_path / "runs"
    d.mkdir()
    (d / "link.json").symlink_to(outside)
    with pytest.raises(FileNotFoundError):
        rr.read_run_file(d, "link.json")
    _put(d, "big.json", run_obj())
    monkeypatch.setattr(rr, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="too large"):
        rr.read_run_file(d, "big.json")


def test_list_runs_is_newest_first_skips_invalid_files_and_caps_at_fifty(tmp_path):
    _put(tmp_path, "old.json", run_obj(), 1000)
    _put(tmp_path, "new.json", run_obj(), 2000)
    _put(tmp_path, "snap.json", {"kind": "snapshot"}, 3000)
    (tmp_path / "broken.json").write_text("{nope")
    (tmp_path / "notes.txt").write_text("x")
    out = rr.list_runs(tmp_path)
    assert [r["name"] for r in out] == ["new.json", "old.json"]
    assert out[0]["duration"] == 1.2 and out[0]["size"] > 0
    for i in range(60):
        _put(tmp_path, f"r{i:02d}.json", run_obj(), 5000 + i)
    assert len(rr.list_runs(tmp_path)) == 50
    assert rr.list_runs(tmp_path / "nope") == []


def test_huge_numbers_are_a_plain_value_error_not_an_overflow():
    o = run_obj()
    o["live_sample"]["series"]["0C"]["samples"].append([2.0, int("9" * 400)])
    with pytest.raises(ValueError):
        rr.load_run(o)
    o = run_obj()
    o["live_sample"]["rate_hz"] = int("9" * 400)
    assert rr.load_run(o).rate_hz == 0.0


def test_a_file_with_a_huge_number_is_skipped_by_the_list_not_fatal(tmp_path):
    (tmp_path / "huge.json").write_text('{"kind": "live_run", "live_sample": {"duration_s": ' + "9" * 400 + "}}")
    _put(tmp_path, "ok.json", run_obj())
    assert [r["name"] for r in rr.list_runs(tmp_path)] == ["ok.json"]


# ---- labels (meta) and run listing for the replay picker ----
from hypothesis import given, strategies as st  # noqa: E402

from obd_reader.vin import with_check_digit  # noqa: E402

META = {"make": "Honda", "model": "Ridgeline", "year": 2024, "title": "Ridgeline 6 min drive"}


def test_a_meta_block_is_ignored_by_load_run_and_old_files_still_load():
    o = run_obj()
    plain = rr.load_run(copy.deepcopy(o))
    o["meta"] = dict(META)
    assert rr.load_run(o) == plain
    o["meta"] = {"make": 5, "year": "x"}
    assert rr.load_run(o) == plain, "a broken meta block never stops a replay"


def test_clean_meta_accepts_a_good_label_and_drops_unknown_keys():
    assert rr.clean_meta({**META, "vin": "x"}) == META


@pytest.mark.parametrize("bad", [
    {**META, "make": ""}, {**META, "make": "x" * 41}, {**META, "model": "x" * 41}, {**META, "title": "x" * 81},
    {**META, "year": "2024"}, {**META, "year": 2024.0}, {**META, "year": True}, {**META, "year": 1995}, {**META, "year": 2101},
    {**META, "title": "line\nbreak"}, {**META, "make": None},
    {k: v for k, v in META.items() if k != "title"}, "not a dict", None,
])
def test_clean_meta_rejects_bad_labels(bad):
    with pytest.raises(ValueError):
        rr.clean_meta(bad)


def test_clean_meta_rejects_a_vin_shaped_string_in_any_label():
    vin = with_check_digit("5FPYK3F5?RB999999")
    for key in ("make", "model", "title"):
        for text in (vin, f"drive {vin}", vin.lower(), "1" * 17):
            with pytest.raises(ValueError, match="VIN"):
                rr.clean_meta({**META, key: text[:40]})


@given(st.text(alphabet="ABCDEFGHJKLMNPRSTUVWXYZ0123456789", min_size=17, max_size=40))
def test_any_run_of_17_vin_characters_is_rejected(s):
    with pytest.raises(ValueError):
        rr.clean_meta({**META, "make": s})


def test_label_run_writes_the_meta_block_and_the_file_still_loads(tmp_path):
    p = _put(tmp_path, "a-run.json", run_obj())
    rr.label_run(p, make=" Honda ", model="Ridgeline", year=2024, title="Ridgeline 6 min drive")
    obj = json.loads(p.read_text())
    assert obj["meta"] == META
    rr.load_run(obj)
    assert sorted(x.name for x in tmp_path.iterdir()) == ["a-run.json"], "no temp file left behind"


def test_label_run_refuses_bad_labels_and_non_runs_and_leaves_the_file_alone(tmp_path):
    p = _put(tmp_path, "a-run.json", run_obj())
    before = p.read_text()
    with pytest.raises(ValueError):
        rr.label_run(p, make="Honda", model="Ridgeline", year=2024, title=with_check_digit("5FPYK3F5?RB999999"))
    assert p.read_text() == before
    snap = _put(tmp_path, "snap.json", {"kind": "snapshot"})
    with pytest.raises(ValueError):
        rr.label_run(snap, **{**META})


def test_list_runs_reports_labels_and_a_timestamp_from_the_name_or_the_file_time(tmp_path):
    labelled = run_obj()
    labelled["meta"] = dict(META)
    _put(tmp_path, "2026-09-30T21-32-56Z-drive.json", labelled, 1000)
    broken = run_obj()
    broken["meta"] = {"make": "x" * 99}
    _put(tmp_path, "plain.json", broken, 1_700_000_000)
    out = {r["name"]: r for r in rr.list_runs(tmp_path)}
    assert out["2026-09-30T21-32-56Z-drive.json"]["meta"] == META
    assert out["2026-09-30T21-32-56Z-drive.json"]["time"] == "2026-09-30T21:32:56Z", "the name wins over the file time"
    assert out["plain.json"]["meta"] is None, "a bad label lists as unlabelled"
    assert out["plain.json"]["time"] == "2023-11-14T22:13:20Z"


def test_list_runs_is_newest_first_by_timestamp(tmp_path):
    _put(tmp_path, "2026-01-01T00-00-00Z-old.json", run_obj(), 3000)
    _put(tmp_path, "2026-06-01T00-00-00Z-new.json", run_obj(), 1000)
    assert [r["name"] for r in rr.list_runs(tmp_path)] == ["2026-06-01T00-00-00Z-new.json", "2026-01-01T00-00-00Z-old.json"]


def test_label_run_cli(tmp_path, capsys):
    from obd_reader.__main__ import main

    p = _put(tmp_path, "a-run.json", run_obj())
    assert main(["label-run", str(p), "--make", "Honda", "--model", "Ridgeline", "--year", "2024",
                 "--title", "Ridgeline 6 min drive"]) == 0
    assert json.loads(p.read_text())["meta"] == META
    assert main(["label-run", str(p), "--make", "Honda", "--model", "Ridgeline", "--year", "1990", "--title", "t"]) == 1
    assert "error" in capsys.readouterr().err


def test_demo_provenance_and_unanswered_codes_survive_loading():
    o = run_obj()
    assert rr.load_run(o).demo is False
    o["demo"] = True
    o["codes"] = {"read": True, "note": None, "mil": None, "unanswered": ["pending", "mil", "bogus"], "stored": [], "pending": [], "permanent": []}
    r = rr.load_run(o)
    assert r.demo is True and r.codes["mil"] is None and r.codes["unanswered"] == ["pending", "mil"]
    o["codes"] = {"read": False, "note": "the car did not answer", "mil": False}
    assert rr.load_run(o).codes == {"read": False, "note": "the car did not answer", "mil": False}


def test_readiness_and_freeze_frame_blocks_are_checked_and_a_bad_one_is_dropped():
    o = run_obj()
    o["readiness"] = {"read": True, "mil": False, "dtc_count": 0, "ignition": "spark",
                      "monitors": {"misfire": {"supported": True, "complete": True}, "egr": {"supported": False, "complete": None}}}
    o["freeze_frame"] = {"read": True, "dtc": "P0171", "pids": {"05": {"name": "coolant_temp", "unit": "C", "value": 90, "label": None}}}
    r = rr.load_run(o)
    assert r.readiness["monitors"]["egr"] == {"supported": False, "complete": None} and r.freeze_frame["pids"]["05"]["value"] == 90.0
    for bad in ({"monitors": {"<b>": {"supported": True}}}, {"ignition": "steam"}, {"dtc_count": True}):
        assert rr.load_run({**o, "readiness": {**o["readiness"], **bad}}).readiness is None
    for bad in ({"dtc": "X1234"}, {"pids": {"5": {}}}, {"pids": {"05": {"name": "x", "unit": None, "value": float("nan")}}}):
        assert rr.load_run({**o, "freeze_frame": {**o["freeze_frame"], **bad}}).freeze_frame is None
    o["freeze_frame"] = {"read": False, "note": "the car did not answer the freeze-frame request"}
    assert rr.load_run(o).freeze_frame == o["freeze_frame"]
