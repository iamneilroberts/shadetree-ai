from datetime import datetime, timezone
from pathlib import Path

from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.transport import Transport

SEDAN = Path(__file__).parent / "fixtures" / "synthetic_sedan.jsonl"
REAL = Path(__file__).parent / "fixtures" / "ridgeline_2024_can29.jsonl"
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def run(path, **kw):
    port = ReplayPort(load_transcript(path))
    return scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol=kw.pop("protocol", "6"), **kw), port


def test_freeze_frame_is_read_when_a_dtc_is_stored():
    snap, port = run(SEDAN)
    ff = snap.freeze_frame
    assert ff is not None and ff.dtc == "P0171"
    assert ff.pids["0C"].value == 1726.0 and ff.pids["0C"].name == "engine_rpm"
    assert ff.pids["05"].value == 83 and ff.pids["04"].value == 50.2
    assert port.unmatched == []


def test_no_freeze_frame_requests_when_there_are_no_codes():
    snap, port = run(REAL, protocol="0")
    assert snap.freeze_frame is None
    assert not any(c.startswith("02") for c in port.written)


def test_readiness_comes_from_every_ecu_in_the_real_capture():
    snap, _ = run(REAL, protocol="0")
    assert snap.ignition_type == "spark"
    assert snap.readiness["catalyst"].supported and snap.readiness["catalyst"].complete is True
    assert snap.readiness["heated_catalyst"].supported is False


def test_symptoms_are_kept_in_user_context():
    snap, _ = run(SEDAN, symptoms="rough idle, smells rich")
    assert snap.user_context.symptoms == "rough idle, smells rich"
