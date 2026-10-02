import json
import tarfile

import pytest

from obd_reader.__main__ import main
from obd_reader.export import ExportError, export_run

RUN = "2026-09-30T17-18-50Z-run.json"
OLD_RUN = "2026-09-30T09-00-00Z-run.json"
TR_NEW = "2026-09-30T17-16-27-667400Z-console.jsonl"
TR_OLD = "2026-09-30T08-58-00-000000Z-console.jsonl"
TR_LATER = "2026-09-30T18-30-00-000000Z-console.jsonl"


def rows(*pairs):
    return "".join(json.dumps({"t": i * 0.1, "tx": tx, "rx": rx}) + "\n" for i, (tx, rx) in enumerate(pairs))


def make(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "transcripts").mkdir()
    for n in (RUN, OLD_RUN):
        (tmp_path / "runs" / n).write_text(json.dumps({"kind": "live_run", "live_sample": {"series": {}}}))
    (tmp_path / "transcripts" / TR_NEW).write_text(rows(
        ("ATDP", ["AUTO, ISO 15765-4 (CAN 29/500)"]),
        ("03", ["43 00"]), ("07", ["47 00"]), ("0A", ["4A 00"]), ("0101", ["41 01 00 07 E5 00"]),
        ("0902", ["49 02 01 11 22 33 44 55 66 77 88 99"]),
        ("0600", ["46 00 CC 00 00 01"]), ("0601", ["46 01 80 14 00 C7 00 00 00 C8 01 87 14 00 9A"]), ("0621", ["46 21 A1 0B 00 00"]),
        ("010C", ["41 0C 0B 54"]), ("0105", ["41 05 7C"]), ("010C", ["41 0C 0C 00"]), ("0105", ["41 05 7C"]),
    ))
    (tmp_path / "transcripts" / TR_OLD).write_text(rows(("010C", ["41 0C 00 00"])))
    (tmp_path / "transcripts" / TR_LATER).write_text(rows(("010C", ["41 0C 00 00"])))


def names(tgz):
    with tarfile.open(tgz) as t:
        return sorted(t.getnames()), {m.name: t.extractfile(m).read().decode() for m in t.getmembers() if m.isfile()}


def test_bundle_holds_the_newest_run_its_own_transcript_and_a_summary(tmp_path):
    make(tmp_path)
    dest = export_run(tmp_path, tmp_path / "out.tgz")
    got, _ = names(dest)
    assert got == sorted(["shadetree-share", "shadetree-share/SUMMARY.txt", "shadetree-share/runs",
                          f"shadetree-share/runs/{RUN}", "shadetree-share/transcripts", f"shadetree-share/transcripts/{TR_NEW}"])


def test_summary_reports_protocol_codes_lamp_mode06_and_channel_stats(tmp_path):
    make(tmp_path)
    _, files = names(export_run(tmp_path, tmp_path / "out.tgz"))
    s = files["shadetree-share/SUMMARY.txt"]
    for want in ("protocol: ISO 15765-4 (CAN 29/500)", "codes: stored none, pending none, permanent none", "MIL: off",
                 "Mode 06: 2 MIDs (01, 21)", "0C engine_rpm", "n=2", "min 725", "mean 746.5", "max 768", "05 coolant_temp"):
        assert want in s, want


def test_summary_never_carries_vin_reply_bytes(tmp_path):
    make(tmp_path)
    _, files = names(export_run(tmp_path, tmp_path / "out.tgz"))
    assert "49 02" not in files["shadetree-share/SUMMARY.txt"] and "0902" not in files["shadetree-share/SUMMARY.txt"]


def test_latest_two_takes_both_runs_with_their_transcripts(tmp_path):
    make(tmp_path)
    got, _ = names(export_run(tmp_path, tmp_path / "out.tgz", latest=2))
    assert f"shadetree-share/runs/{OLD_RUN}" in got and f"shadetree-share/transcripts/{TR_OLD}" in got


def test_no_runs_is_a_clear_error_and_the_cli_returns_1(tmp_path, capsys):
    with pytest.raises(ExportError, match="no run files"):
        export_run(tmp_path, tmp_path / "out.tgz")
    assert main(["export-run", "--out-dir", str(tmp_path), "--dest", str(tmp_path / "o.tgz")]) == 1
    assert "no run files" in capsys.readouterr().err


def test_cli_writes_the_bundle_and_says_it_may_hold_the_vin(tmp_path, capsys):
    make(tmp_path)
    assert main(["export-run", "--out-dir", str(tmp_path), "--dest", str(tmp_path / "o.tgz")]) == 0
    out = capsys.readouterr().out
    assert (tmp_path / "o.tgz").exists() and "never commit" in out.lower()


def test_a_run_that_names_its_transcript_is_paired_with_that_one_not_by_time(tmp_path):
    make(tmp_path)  # by time, RUN would pair with TR_NEW
    (tmp_path / "runs" / RUN).write_text(json.dumps({"kind": "live_run", "transcript": f"transcripts/{TR_OLD}"}))
    got, files = names(export_run(tmp_path, tmp_path / "out.tgz"))
    assert f"shadetree-share/transcripts/{TR_OLD}" in got and f"shadetree-share/transcripts/{TR_NEW}" not in got
    assert f"transcript: {TR_OLD}" in files["shadetree-share/SUMMARY.txt"]


def test_a_named_transcript_outside_the_data_home_is_not_bundled(tmp_path):
    make(tmp_path)
    (tmp_path / "secret.jsonl").write_text("{}\n")
    (tmp_path / "home").mkdir()
    for d in ("runs", "transcripts"):
        (tmp_path / d).rename(tmp_path / "home" / d)
    (tmp_path / "home" / "runs" / RUN).write_text(json.dumps({"transcript": "../secret.jsonl"}))
    got, files = names(export_run(tmp_path / "home", tmp_path / "out.tgz"))
    assert [n for n in got if n.startswith("shadetree-share/transcripts/")] == []
    assert "transcript: none found" in files["shadetree-share/SUMMARY.txt"]
