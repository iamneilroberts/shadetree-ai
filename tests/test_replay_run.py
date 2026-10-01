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
