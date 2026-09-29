import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from obd_reader.capture import capture
from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.snapshot import Snapshot
from obd_reader.transport import Transport

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_sedan.jsonl"
NOW = datetime(2026, 9, 29, 14, 22, 9, tzinfo=timezone.utc)


def fresh_port():
    return ReplayPort(load_transcript(FIXTURE))


def test_capture_writes_snapshot_and_transcript(tmp_path):
    snap, s_path, t_path = capture(fresh_port(), tmp_path, label="ridgeline", protocol="6", now=NOW)
    assert s_path == tmp_path / "snapshots" / "2026-09-29T14-22-09Z-ridgeline.json"
    assert t_path == tmp_path / "transcripts" / "2026-09-29T14-22-09Z-ridgeline.jsonl"
    assert snap.source.kind == "live" and snap.snapshot_id == "2026-09-29T14-22-09Z-ridgeline"
    assert Snapshot.model_validate_json(s_path.read_text()) == snap
    assert json.loads(t_path.read_text().splitlines()[0])["tx"] == "ATZ"


def test_recorded_transcript_replays_to_the_same_snapshot(tmp_path):
    snap, _, t_path = capture(fresh_port(), tmp_path, label="rt", protocol="6", now=NOW)
    again = scan(Transport(ReplayPort.from_file(t_path)), snapshot_id="x", protocol="6")
    for field in ("vehicle", "protocol", "supported_pids", "dtcs", "mil", "warnings"):
        assert getattr(again, field) == getattr(snap, field), field


@pytest.mark.parametrize("label", ["", "../x", "A b", "UPPER", "a/b", "x" * 41])
def test_bad_label_is_rejected_before_touching_the_port(tmp_path, label):
    port = fresh_port()
    with pytest.raises(ValueError):
        capture(port, tmp_path, label=label, now=NOW)
    assert port.written == []


def test_existing_capture_is_never_overwritten_and_port_untouched(tmp_path):
    capture(fresh_port(), tmp_path, label="dup", protocol="6", now=NOW)
    second = fresh_port()
    with pytest.raises(FileExistsError):
        capture(second, tmp_path, label="dup", protocol="6", now=NOW)
    assert second.written == []


def test_cli_scan_end_to_end_on_a_silent_loopback_port(tmp_path):
    # loop:// echoes our own commands back and never answers: no car, no adapter.
    proc = subprocess.run(
        [sys.executable, "-m", "obd_reader", "scan", "--port", "loop://", "--label", "smoke",
         "--timeout", "0.2", "--out-dir", str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    snaps = list((tmp_path / "snapshots").glob("*-smoke.json"))
    assert len(snaps) == 1 and len(list((tmp_path / "transcripts").glob("*-smoke.jsonl"))) == 1
    snap = Snapshot.model_validate_json(snaps[0].read_text())
    assert snap.source.kind == "live"
    assert any("Mode 01" in w for w in snap.warnings)
    assert "snapshot:" in proc.stdout and "transcript:" in proc.stdout
