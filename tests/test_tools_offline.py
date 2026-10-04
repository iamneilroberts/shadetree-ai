from datetime import datetime, timezone
from pathlib import Path

import pytest

from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.session import Config, Session
from obd_reader.store import InvalidSnapshotId
from obd_reader.tools import NoSnapshotError, build_tools
from obd_reader.transport import Transport

FIX = Path(__file__).parent / "fixtures"


def snapshot_from(name, sid, protocol):
    port = ReplayPort(load_transcript(FIX / name))
    return scan(Transport(port), snapshot_id=sid, captured_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
                protocol=protocol, symptoms="rough idle")


@pytest.fixture
def session(tmp_path):
    s = Session(Config(port=None, home=tmp_path))
    s.store.save(snapshot_from("synthetic_sedan.jsonl", "sedan-1", "6"))
    s.store.save(snapshot_from("ridgeline_2024_can29.jsonl", "ridge-1", "0"))
    return s


@pytest.fixture
def tools(session):
    return build_tools(session)


def test_list_and_get(tools):
    rows = tools["list_snapshots"]()["snapshots"]
    assert {r["snapshot_id"] for r in rows} == {"sedan-1", "ridge-1"}
    got = tools["get_snapshot"]("sedan-1")
    assert got["vehicle"]["vin"] == "1HGCM82633A004352"


def test_default_is_the_newest_snapshot_and_empty_store_is_a_clear_error(tmp_path):
    empty = build_tools(Session(Config(port=None, home=tmp_path)))
    with pytest.raises(NoSnapshotError):
        empty["read_dtcs"]()


def test_read_dtcs_kinds(tools):
    out = tools["read_dtcs"]("sedan-1", "stored")
    assert [d["code"] for d in out["dtcs"]] == ["P0171"] and out["mil"]["on"] is True
    assert tools["read_dtcs"]("sedan-1", "pending")["dtcs"] == []
    assert [d["code"] for d in tools["read_dtcs"]("sedan-1", "all")["dtcs"]] == ["P0171"]
    with pytest.raises(ValueError):
        tools["read_dtcs"]("sedan-1", "everything")


def test_freeze_frame(tools):
    ff = tools["freeze_frame"]("sedan-1")["freeze_frame"]
    assert ff["dtc"] == "P0171" and ff["pids"]["0C"]["value"] == 1726.0
    assert tools["freeze_frame"]("ridge-1")["freeze_frame"] is None


def test_readiness_summarises_incomplete_and_unsupported(tools):
    r = tools["readiness"]("ridge-1")
    assert r["ignition_type"] == "spark" and r["incomplete"] == []
    assert "heated_catalyst" in r["not_supported"] and "catalyst" in r["monitors"]


def test_vehicle_info(tools):
    v = tools["vehicle_info"]("ridge-1")
    assert v["vin"] == "5FPYK3F51RB000001" and v["protocol"] == "ISO 15765-4 (CAN 29/500)"
    assert v["adapter"]["genuine_stn"] is True and "02" in v["supported_mode09_pids"]


def test_vehicle_info_shows_mode09_identity_and_battery_voltage(tools):
    v = tools["vehicle_info"]("sedan-1")
    assert v["mode09"] == {"cal_ids": ["SYNCAL0001"], "cvns": ["1A2B3C4D"], "ecu_names": ["ECM-EngineControl"]}
    assert v["adapter"]["supply_voltage"] == "12.6V"


def test_vehicle_info_counts_reply_classes_and_undecoded_pids(tools):
    v = tools["vehicle_info"]("sedan-1")
    assert v["reply_counts"] == {"ok": sum(v["reply_counts"].values())} and v["reply_counts"]["ok"] > 0
    assert v["undecoded_count"] == 1  # 012B in the synthetic sedan


def test_read_dtcs_names_kinds_the_car_did_not_answer(session):
    snap = snapshot_from("synthetic_sedan.jsonl", "sedan-2", "6")
    session.store.save(snap.model_copy(update={"dtcs": snap.dtcs.model_copy(update={"unanswered": ["pending"]})}))
    t = build_tools(session)
    assert t["read_dtcs"]("sedan-2", "all")["unanswered"] == ["pending"]
    assert t["read_dtcs"]("sedan-2", "stored")["unanswered"] == []


def test_list_supported_pids_names_decodable_pids(tools):
    out = tools["list_supported_pids"]("ridge-1")["mode01"]
    by = {p["pid"]: p for p in out}
    assert by["05"]["name"] == "coolant_temp" and by["0C"]["decodable"] is True
    assert by["01"]["decodable"] is False and by["01"]["name"] == "unknown"


def test_compare_snapshots_reports_differences(tools):
    d = tools["compare_snapshots"]("sedan-1", "ridge-1")
    assert d["dtcs"]["only_in_a"] == ["P0171"] and d["dtcs"]["only_in_b"] == []
    assert d["mil"] == {"a": True, "b": False}
    assert d["protocol"]["a"] != d["protocol"]["b"]
    assert "08" in d["supported_pids"]["only_in_b"]  # supported by the Ridgeline's ECU 1, not by the sedan


def test_unsafe_ids_are_refused(tools):  # Review Focus 2
    for bad in ("../x", "a/b", "/etc/passwd"):
        with pytest.raises(InvalidSnapshotId):
            tools["get_snapshot"](bad)


def test_import_snapshot_inside_home_only(tools, session, tmp_path):  # Review Focus 2
    src = tmp_path / "copy.json"
    snap = session.store.load("sedan-1").model_copy(update={"snapshot_id": "sedan-copy"})
    src.write_text(snap.model_dump_json())
    assert tools["import_snapshot"](str(src))["snapshot_id"] == "sedan-copy"
    with pytest.raises(ValueError):
        tools["import_snapshot"]("/etc/hostname")
