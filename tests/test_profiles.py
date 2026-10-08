import json
import pytest

from obd_reader.profiles import ProfileStore

KEY = "9SXSMUL1-T"
GOOD = {"schema": 1, "key": KEY, "updated": "2026-09-30T18:00:00+00:00", "runs": 2, "protocol": "ISO 15765-4 (CAN 29/500)",
        "supported_pids": ["04", "0C"], "unsupported": ["10"], "extras": ["04"]}


def test_save_then_load_round_trips(tmp_path):
    s = ProfileStore(tmp_path)
    s.save(KEY, GOOD)
    assert s.load(KEY) == GOOD
    assert (tmp_path / "profiles" / f"{KEY}.json").exists()


def test_missing_corrupt_and_wrong_schema_files_load_as_none(tmp_path):
    s = ProfileStore(tmp_path)
    assert s.load(KEY) is None
    (tmp_path / "profiles").mkdir()
    p = tmp_path / "profiles" / f"{KEY}.json"
    p.write_text("{not json")
    assert s.load(KEY) is None
    p.write_text(json.dumps({**GOOD, "schema": 99}))
    assert s.load(KEY) is None
    p.write_text(json.dumps({**GOOD, "unsupported": "10"}))
    assert s.load(KEY) is None


def test_bad_pid_entries_are_dropped_not_trusted(tmp_path):
    s = ProfileStore(tmp_path)
    s.save(KEY, {**GOOD, "unsupported": ["10", "ZZ", "1", 5, "0b"]})
    assert s.load(KEY)["unsupported"] == ["10"]


def test_keys_that_are_not_keys_are_refused_so_no_path_can_escape(tmp_path):
    s = ProfileStore(tmp_path)
    for bad in ("../x", "a/b", "", "9SXSMUL1T", "9sxsmul1-t", "9SXSMUL1-T.json"):
        assert s.load(bad) is None
        try:
            s.save(bad, GOOD)
        except ValueError:
            continue
        raise AssertionError(f"saved {bad!r}")


def test_save_replaces_atomically_and_leaves_no_temp_files(tmp_path):
    s = ProfileStore(tmp_path)
    s.save(KEY, GOOD)
    s.save(KEY, {**GOOD, "runs": 3})
    assert s.load(KEY)["runs"] == 3
    assert [p.name for p in (tmp_path / "profiles").iterdir()] == [f"{KEY}.json"]


def test_set_name_keeps_the_runs_and_a_bad_name_loads_as_no_name(tmp_path):
    s = ProfileStore(tmp_path)
    assert s.set_name(KEY, "Simco", "Bench", 2026) == {"make": "Simco", "model": "Bench", "year": 2026}
    assert s.load(KEY)["runs"] == 0 and s.load(KEY)["model"] == "Bench"   # a new profile with no runs
    s.save(KEY, GOOD)
    s.set_name(KEY, "Simco", "Bench", 2026)
    assert {k: v for k, v in s.load(KEY).items() if k not in ("make", "model", "year", "updated")} == \
        {k: v for k, v in GOOD.items() if k != "updated"}
    s.save(KEY, {**GOOD, "make": "Simco", "model": "x" * 99, "year": 2026})
    assert "make" not in s.load(KEY)
    for bad in (("", "B", 2026), ("S", "B", 1950), ("S", "B", "2026"), ("S", "1HGCM82633A004352", 2026)):
        with pytest.raises(ValueError):
            s.set_name(KEY, *bad)
