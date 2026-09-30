"""Multi-ECU behavior, driven by a real 2024 Ridgeline capture (VIN serial redacted)."""
from datetime import datetime, timezone
from pathlib import Path

from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.transport import Transport

REAL = Path(__file__).parent / "fixtures" / "ridgeline_2024_can29.jsonl"
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
VIN_A = ["014", "0: 49 02 01 31 48 47", "1: 43 4D 38 32 36 33 33", "2: 41 30 30 34 33 35 32"]


def run(records):
    port = ReplayPort(records)
    return scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol="0"), port


def patch(records, tx, rx):
    return [dict(r, rx=rx) if r["tx"] == tx else r for r in records]


def test_real_ridgeline_capture_decodes_as_can29_with_synthetic_vin():
    snap, _ = run(load_transcript(REAL))
    assert snap.protocol.name == "ISO 15765-4 (CAN 29/500)" and snap.protocol.pinned is False
    assert snap.vehicle.vin == "5FPYK3F51RB000001" and snap.vehicle.vin_source == "obd"
    assert snap.dtcs.stored == snap.dtcs.pending == snap.dtcs.permanent == []
    assert snap.mil.on is False and snap.mil.dtc_count == 0


def test_supported_pids_are_the_union_of_every_responding_ecu():
    # PID 03 is supported only by the first ECU, PID 05 (coolant temp) only by the second.
    snap, _ = run(load_transcript(REAL))
    pids = snap.supported_pids["01"]
    assert "03" in pids and "05" in pids
    assert pids == sorted(set(pids))  # no duplicates, stable order
    assert {"20", "40", "60", "80", "A0"} <= set(pids)  # every page was walked
    assert "09" in snap.supported_pids and "02" in snap.supported_pids["09"]


def test_dtcs_are_the_union_across_ecus_without_duplicates():
    records = patch(load_transcript(REAL), "03", ["43 02 01 71 C1 00", "43 02 01 71 03 00"])
    snap, _ = run(records)
    assert [d.code for d in snap.dtcs.stored] == ["P0171", "U0100", "P0300"]


def test_mil_is_on_if_any_ecu_says_so_and_counts_add_up():
    records = patch(load_transcript(REAL), "0101", ["41 01 00 07 E5 00", "41 01 82 04 00 00"])
    snap, _ = run(records)
    assert snap.mil.on is True and snap.mil.dtc_count == 2


def test_disagreeing_vins_warn_and_use_the_first_valid_one():
    records = patch(load_transcript(REAL), "0902", VIN_A + ["014", "0: 49 02 01 35 46 50",
                    "1: 59 4B 33 46 35 31 52", "2: 42 30 30 30 30 30 31"])
    snap, _ = run(records)
    assert snap.vehicle.vin == "1HGCM82633A004352"
    assert any("disagree" in w.lower() for w in snap.warnings)
