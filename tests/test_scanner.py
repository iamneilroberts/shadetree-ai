import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from obd_reader.allowlist import check_command
from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.snapshot import Snapshot
from obd_reader.transport import Transport

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_sedan.jsonl"
NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def run_scan(records, protocol="6"):
    port = ReplayPort(records)
    snap = scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol=protocol)
    return snap, port


def test_scan_synthetic_sedan():
    snap, port = run_scan(load_transcript(FIXTURE))
    assert snap.vehicle.vin == "1HGCM82633A004352" and snap.vehicle.vin_source == "obd"
    assert snap.protocol.name == "ISO 15765-4 (CAN 11/500)" and snap.protocol.pinned
    assert [d.code for d in snap.dtcs.stored] == ["P0171"]
    assert snap.dtcs.pending == [] and snap.dtcs.permanent == []
    assert snap.mil.on is True and snap.mil.dtc_count == 1
    assert {"0C", "20", "21"} <= set(snap.supported_pids["01"])
    assert "02" in snap.supported_pids["09"]
    assert snap.source.adapter.ati == "ELM327 v1.5"
    assert snap.source.adapter.genuine_stn is False
    assert snap.warnings == []


def test_every_byte_written_is_allowlisted_and_nothing_was_unmatched():
    _, port = run_scan(load_transcript(FIXTURE))
    assert port.unmatched == []
    assert port.written, "scan wrote nothing"
    for cmd in port.written:
        assert check_command(cmd) == cmd
    assert "0140" not in port.written  # page 0x20 did not advertise 0x40


def test_snapshot_round_trips_through_json():
    snap, _ = run_scan(load_transcript(FIXTURE))
    assert Snapshot.model_validate_json(snap.model_dump_json()) == snap


def _patch(records, tx, rx):
    return [dict(r, rx=rx) if r["tx"] == tx else r for r in records]


def test_mode_09_no_data_gives_no_vin_and_skips_0902():  # Review Focus 3
    records = _patch(load_transcript(FIXTURE), "0900", ["NO DATA"])
    snap, port = run_scan(records)
    assert snap.vehicle.vin is None and snap.vehicle.vin_source == "none"
    assert any("VIN unsupported" in w for w in snap.warnings)
    assert "0902" not in port.written


def test_mode_09_negative_response_is_handled():  # Review Focus 3
    records = _patch(load_transcript(FIXTURE), "0900", ["7F 09 12"])
    snap, _ = run_scan(records)
    assert snap.vehicle.vin is None
    assert any("VIN unsupported" in w for w in snap.warnings)


def test_invalid_vin_from_adapter_is_dropped_with_warning():  # Review Focus 5
    bad = ["014", "0: 49 02 01 4F 48 47", "1: 43 4D 38 32 36 33 33", "2: 41 30 30 34 33 35 32"]  # 'O'
    snap, _ = run_scan(_patch(load_transcript(FIXTURE), "0902", bad))
    assert snap.vehicle.vin is None
    assert any("invalid VIN" in w for w in snap.warnings)


def test_no_dtc_data_replies_mean_empty_lists_not_a_crash():
    records = _patch(_patch(load_transcript(FIXTURE), "03", ["NO DATA"]), "0A", ["NO DATA"])
    snap, _ = run_scan(records)
    assert snap.dtcs.stored == [] and snap.dtcs.permanent == []


def test_non_can_protocol_skips_dtc_and_vin_decoding_with_a_warning():
    # Non-CAN Mode 03 has no count byte and the VIN reply is 5 lines; decoding
    # them with the CAN layout would yield wrong codes (P0133 -> P3300).
    records = _patch(load_transcript(FIXTURE), "ATDP", ["SAE J1850 PWM"])
    records = _patch(records, "03", ["43 01 33 00 00 00 00"])
    snap, port = run_scan(records)
    assert snap.dtcs.stored == [] and snap.vehicle.vin is None
    assert any("non-CAN" in w for w in snap.warnings)
    assert not {"03", "07", "0A", "0902"} & set(port.written)


def test_unknown_protocol_is_treated_as_non_can():
    records = [r for r in load_transcript(FIXTURE) if r["tx"] != "ATDP"]
    snap, port = run_scan(records)
    assert snap.dtcs.stored == []
    assert any("non-CAN" in w for w in snap.warnings)


def test_auto_protocol_is_not_reported_as_pinned():
    snap, _ = run_scan(load_transcript(FIXTURE) + [{"tx": "ATSP0", "rx": ["OK"]}], protocol="0")
    assert snap.protocol.atsp == "0" and snap.protocol.pinned is False


def test_no_mode_01_bitmap_gives_a_warning_not_silence():
    records = _patch(load_transcript(FIXTURE), "0100", ["UNABLE TO CONNECT"])
    snap, _ = run_scan(records)
    assert snap.supported_pids.get("01") is None
    assert any("Mode 01" in w and "no response" in w.lower() for w in snap.warnings)


def test_cli_replay_prints_a_valid_snapshot():
    out = subprocess.run(
        [sys.executable, "-m", "obd_reader", "replay", str(FIXTURE), "--protocol", "6"],
        capture_output=True, text=True, check=True,
    ).stdout
    snap = Snapshot.model_validate(json.loads(out))
    assert snap.vehicle.vin == "1HGCM82633A004352"
