from datetime import datetime, timezone
from pathlib import Path

from obd_reader.pids import PIDS
from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.snapshot import UndecodedPid
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


def _scan_records(records, protocol="6"):
    port = ReplayPort(records)
    return scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol=protocol), port


def test_advertised_pids_without_a_decoder_are_read_once_and_kept_raw():
    snap, port = run(SEDAN)
    assert snap.undecoded == [UndecodedPid(pid="2B", reply="ok", raw=["03"])]
    assert port.written.count("012B") == 1 and port.unmatched == []


def test_ridgeline_bitmap_undecoded_pids_are_requested_and_nothing_else():
    # Synthetic replies layered on the real bitmaps: 6C answers, 9D is refused, 41 answers from both ECUs.
    # 66, 67 and 68 (multi-sensor MAF, coolant, intake air) are decoded now, so they are no longer listed here.
    extra = [{"tx": "016C", "rx": ["41 6C 03 01 F4 01 E0"]}, {"tx": "019D", "rx": ["7F 01 12"]},
             {"tx": "0141", "rx": ["41 41 00 07 E5 00", "41 41 00 04 00 00"]}]
    snap, port = _scan_records(load_transcript(REAL) + extra, protocol="0")
    expected = ["41", "6C", "9D", "9E", "9F", "A3"]
    assert [u.pid for u in snap.undecoded] == expected
    requested = [c for c in port.written if c.startswith("01") and c[2:] in PIDS]
    assert requested == []  # decodable PIDs are not read here; only the undecoded ones are
    assert port.written.count("0101") == 1  # status is read once, by the readiness step
    got = {u.pid: u for u in snap.undecoded}
    assert got["6C"].reply == "ok" and got["6C"].raw == ["0301F401E0"]
    assert got["9D"].reply == "nrc:12" and got["9D"].raw == []
    assert got["41"].raw == ["0007E500", "00040000"]
    assert got["9E"].reply == "adapter_error"  # not in the capture: replay answers "?"


def test_undecoded_reads_are_capped_with_a_warning():
    records = [dict(r, rx=["41 20 80 00 00 01"]) if r["tx"] == "0120" else r for r in load_transcript(SEDAN)]
    records += [{"tx": "0140", "rx": ["41 40 00 00 00 01"]}, {"tx": "0160", "rx": ["41 60 FF FF FF FF"]},
                {"tx": "0180", "rx": ["41 80 FF FF FF FE"]}]
    snap, port = _scan_records(records)
    assert len(snap.undecoded) == 32
    assert sum(1 for c in port.written if c.startswith("01") and c[2:] not in PIDS and c[2:] != "01"
               and int(c[2:], 16) % 0x20) == 32
    assert any("cap 32" in w for w in snap.warnings)
