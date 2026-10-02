import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from obd_reader.__main__ import main
from obd_reader.probe import markdown, report, write_probe
from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.transport import Transport
from obd_reader.vehicle import vehicle_key
from obd_reader.vin import find_vins, with_check_digit

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)
# MIDs 01, 02 and page 20 on the first page; MID 21 on page 20. Synthetic: no fixture has a Mode 06 pass yet.
MODE06 = [{"tx": "0600", "rx": ["46 00 C0 00 00 01"]}, {"tx": "0620", "rx": ["46 20 80 00 00 00"]}]


def probe_scan(records, protocol="6"):
    port = ReplayPort(records)
    return scan(Transport(port), snapshot_id="p", captured_at=NOW, protocol=protocol, mode06=True), port


def text_of(snap):
    rep = report(snap)
    return json.dumps(rep, indent=2) + markdown(rep)


def test_the_mode06_pass_reads_only_the_mid_bitmap_pages():
    snap, port = probe_scan(load_transcript(FIX / "synthetic_sedan.jsonl") + MODE06)
    assert [c for c in port.written if c.startswith("06")] == ["0600", "0620"]
    assert snap.supported_pids["06"] == ["01", "02", "20", "21"]
    assert {r.cmd: r.reply for r in snap.replies}["0620"] == "ok"


@pytest.mark.parametrize("fixture,protocol", [("synthetic_sedan.jsonl", "6"), ("ridgeline_2024_can29.jsonl", "0")])
def test_the_report_carries_no_vin_but_keeps_the_vehicle_key(fixture, protocol):
    snap, _ = probe_scan(load_transcript(FIX / fixture) + MODE06, protocol)
    text = text_of(snap)
    assert snap.vehicle.vin and snap.vehicle.vin not in text and snap.vehicle.vin[11:] not in text
    assert find_vins(text) == []
    assert vehicle_key(snap.vehicle.vin) in text  # the report really was built from a scan that read the VIN
    assert "transcript" not in report(snap) and "fixtures" not in text


def test_a_warning_that_quotes_a_vin_keeps_only_its_lead_in():
    bad = ["014", "0: 49 02 01 4F 48 47", "1: 43 4D 38 32 36 33 33", "2: 41 30 30 34 33 35 32"]  # 'O' -> invalid
    records = [dict(r, rx=bad) if r["tx"] == "0902" else r for r in load_transcript(FIX / "synthetic_sedan.jsonl")]
    snap, _ = probe_scan(records)
    assert any("82633A004352" in w for w in snap.warnings)
    assert "82633A004352" not in text_of(snap)
    assert "Mode 09 returned an invalid VIN" in report(snap)["warnings"]


def test_write_refuses_a_report_with_a_vin_looking_token(tmp_path):
    snap, _ = probe_scan(load_transcript(FIX / "synthetic_sedan.jsonl"))
    snap.mode09.cal_ids = [with_check_digit("5FPYK3F5?RB999999")]
    with pytest.raises(RuntimeError, match="VIN"):
        write_probe(snap, tmp_path)
    assert not (tmp_path / "probes").exists() or list((tmp_path / "probes").iterdir()) == []


def test_cli_probe_on_replay_writes_a_vin_free_json_and_markdown(tmp_path, capsys):
    tr = tmp_path / "t.jsonl"
    tr.write_text("".join(json.dumps(r) + "\n" for r in load_transcript(FIX / "synthetic_sedan.jsonl") + MODE06))
    assert main(["probe", "--replay", str(tr), "--protocol", "6", "--out-dir", str(tmp_path)]) == 0
    (j,), (m,) = (tmp_path / "probes").glob("*-probe.json"), (tmp_path / "probes").glob("*-probe.md")
    rep, md = json.loads(j.read_text()), m.read_text()
    assert rep["supported_pids"]["06"] == ["01", "02", "20", "21"] and rep["vehicle_key"] == "1HGCM826-3"
    assert "- Mode 06 supported: 01, 02, 20, 21" in md and "latency median" in md
    assert find_vins(j.read_text() + md) == []
    assert "safe to share" in capsys.readouterr().out
    assert not (tmp_path / "snapshots").exists()  # a replay probe writes only the report


def test_cli_probe_live_keeps_the_snapshot_and_transcript_local_and_writes_the_report(tmp_path, elm_server):
    url = elm_server(load_transcript(FIX / "synthetic_sedan.jsonl") + MODE06 + [{"tx": "ATSP0", "rx": ["OK"]}])
    assert main(["probe", "--port", url, "--timeout", "2", "--out-dir", str(tmp_path)]) == 0
    (s,), (j,) = (tmp_path / "snapshots").glob("*-probe.json"), (tmp_path / "probes").glob("*-probe.json")
    assert "1HGCM82633A004352" in s.read_text()  # the private snapshot has the VIN
    assert len(list((tmp_path / "transcripts").glob("*-probe.jsonl"))) == 1
    assert json.loads(j.read_text())["supported_pids"]["06"] == ["01", "02", "20", "21"]
    assert find_vins(j.read_text()) == []
