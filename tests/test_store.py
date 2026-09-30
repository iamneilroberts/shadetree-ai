import json
from datetime import datetime, timezone

import pytest

from obd_reader.snapshot import Dtc, Dtcs, Snapshot, Source
from obd_reader.store import InvalidSnapshotId, SnapshotStore


def snap(sid, day=1, dtcs=()):
    return Snapshot(snapshot_id=sid, captured_at=datetime(2026, 9, day, tzinfo=timezone.utc),
                    source=Source(kind="replay", tool_version="0.1.0"),
                    dtcs=Dtcs(stored=[Dtc(code=c) for c in dtcs]))


def test_save_load_round_trip_and_never_overwrites(tmp_path):
    st = SnapshotStore(tmp_path)
    path = st.save(snap("a-1"))
    assert path == tmp_path.resolve() / "snapshots" / "a-1.json"
    assert st.load("a-1").snapshot_id == "a-1"
    with pytest.raises(FileExistsError):
        st.save(snap("a-1"))


def test_list_is_oldest_first_with_summaries(tmp_path):
    st = SnapshotStore(tmp_path)
    st.save(snap("later", day=5, dtcs=["P0171"]))
    st.save(snap("earlier", day=2))
    rows = st.list()
    assert [r["snapshot_id"] for r in rows] == ["earlier", "later"]
    assert rows[1]["stored_dtcs"] == 1 and "vin" not in rows[1]


def test_missing_snapshot_is_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        SnapshotStore(tmp_path).load("nope")


@pytest.mark.parametrize("sid", ["", "../x", "a/b", "..", ".hidden", "a b", "x" * 100, "a\x00b", "/etc/passwd"])
def test_unsafe_ids_are_rejected(tmp_path, sid):  # Review Focus 2
    with pytest.raises(InvalidSnapshotId):
        SnapshotStore(tmp_path).path(sid)


def test_import_copies_a_valid_snapshot_from_inside_home(tmp_path):
    src = tmp_path / "incoming.json"
    src.write_text(snap("imp-1").model_dump_json())
    st = SnapshotStore(tmp_path)
    assert st.import_file(src).snapshot_id == "imp-1"
    assert st.load("imp-1").snapshot_id == "imp-1"


def test_import_refuses_paths_outside_home_and_wrong_types(tmp_path):  # Review Focus 2
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(snap("x").model_dump_json())
    st = SnapshotStore(home)
    with pytest.raises(ValueError):
        st.import_file(outside)
    (home / "notes.txt").write_text("hi")
    with pytest.raises(ValueError):
        st.import_file(home / "notes.txt")
    with pytest.raises(ValueError):
        st.import_file(home / ".." / "outside.json")


def test_import_errors_do_not_echo_file_contents(tmp_path):  # Review Focus 2
    bad = tmp_path / "secret.json"
    bad.write_text(json.dumps({"password": "hunter2-super-secret"}))
    with pytest.raises(ValueError) as e:
        SnapshotStore(tmp_path).import_file(bad)
    assert "hunter2" not in str(e.value)


def test_import_refuses_to_overwrite(tmp_path):
    st = SnapshotStore(tmp_path)
    st.save(snap("dup"))
    src = tmp_path / "dup-copy.json"
    src.write_text(snap("dup").model_dump_json())
    with pytest.raises(FileExistsError):
        st.import_file(src)
