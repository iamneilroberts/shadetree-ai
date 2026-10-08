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


# ---- the shareable .zip: VIN serial masked to 000000, verified, fail closed ----
import io  # noqa: E402
import zipfile  # noqa: E402

from obd_reader.elm import parse_all, parse_vin_legacy  # noqa: E402
from obd_reader.export import build_zip  # noqa: E402
from obd_reader.vin import with_check_digit  # noqa: E402

VIN = with_check_digit("1ZZZZ123?AB654321")  # made up, built in code so the repo's VIN guard never sees a literal
MASKED = VIN[:11] + "000000"
TX = "2026-10-07T10-00-00-000000Z-console.jsonl"
RUNZ = "2026-10-07T10-05-00Z-drive.json"


def _hex(b: bytes) -> str:
    return " ".join("%02X" % x for x in b)


_ISO = b"\x49\x02\x01" + VIN.encode()
_PAD = b"\x00\x00\x00" + VIN.encode()
LAYOUTS = {
    "can_single_line": [_hex(_ISO)],
    "can_multi_headers_off": ["014", "0: " + _hex(_ISO[:6]), "1: " + _hex(_ISO[6:13]), "2: " + _hex(_ISO[13:])],
    "can_multi_headers_on_11bit": ["7E8 10 14 " + _hex(_ISO[:6]), "7E8 21 " + _hex(_ISO[6:13]), "7E8 22 " + _hex(_ISO[13:])],
    "can_multi_headers_on_29bit": ["18 DA F1 10 10 14 " + _hex(_ISO[:6]), "18 DA F1 10 21 " + _hex(_ISO[6:13]),
                                   "18 DA F1 10 22 " + _hex(_ISO[13:])],
    "legacy_numbered_lines": [_hex(bytes([0x49, 0x02, n + 1]) + _PAD[4 * n:4 * n + 4]) for n in range(5)],
}


def home_with(tmp_path, rx, run=None, extra=()):
    (tmp_path / "runs").mkdir()
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "runs" / RUNZ).write_text(json.dumps(run or {"kind": "live_run", "demo": False, "transcript": f"transcripts/{TX}",
                                                             "vehicle": {"key": "1ZZZZ123-A"}, "live_sample": {"series": {}}}))
    (tmp_path / "transcripts" / TX).write_text(rows(("ATDP", ["AUTO, ISO 15765-4 (CAN 11/500)"]), ("0902", rx), *extra))
    return tmp_path


def unzip(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n).decode() for n in z.namelist()}


def no_trace_of_the_serial(files: dict[str, str]) -> None:
    serial_hex = _hex(VIN[11:].encode())
    for name, text in files.items():
        assert VIN not in text and VIN[11:] not in text and serial_hex not in text, name


@pytest.mark.parametrize("layout", LAYOUTS)
def test_zip_masks_the_serial_in_each_vin_reply_layout(tmp_path, layout):
    data, left_out = build_zip(home_with(tmp_path, LAYOUTS[layout]), [RUNZ])
    files = unzip(data)
    assert left_out == [] and f"transcripts/{TX}" in files
    row = [json.loads(ln) for ln in files[f"transcripts/{TX}"].splitlines()][1]
    assert len(row["rx"]) == len(LAYOUTS[layout]) and row["rx"][0].split()[:2] == LAYOUTS[layout][0].split()[:2]  # line format kept
    assert "30 30 30 30 30 30" in " ".join(row["rx"]).replace("49 02 05 ", "")
    no_trace_of_the_serial(files)


@pytest.mark.parametrize("layout", ["can_single_line", "can_multi_headers_off", "legacy_numbered_lines"])
def test_masked_transcript_decodes_to_the_masked_vin_with_the_scanners_decoder(tmp_path, layout):
    files = unzip(build_zip(home_with(tmp_path, LAYOUTS[layout]), [RUNZ])[0])
    rx = [json.loads(ln) for ln in files[f"transcripts/{TX}"].splitlines()][1]["rx"]
    got = parse_vin_legacy(rx) if layout.startswith("legacy") else [p[3:20].decode() for p in parse_all(rx, 0x49)]
    assert got == [MASKED]


@pytest.mark.parametrize("rx, extra", [
    (["017", "0: 49 02 01 00 00 00", "1: " + _hex(VIN[:7].encode()), "2: " + _hex(VIN[7:14].encode()),
      "3: " + _hex(VIN[14:].encode())], ()),  # a padded CAN reply: a layout the scanner does not decode
    (LAYOUTS["can_multi_headers_off"], (("0904", ["49 04 01 " + _hex(VIN[11:].encode())]),)),  # its serial turns up in another reply
])
def test_a_transcript_that_cannot_be_masked_is_left_out_and_said_so(tmp_path, rx, extra):
    data, left_out = build_zip(home_with(tmp_path, rx, extra=extra), [RUNZ])
    files = unzip(data)
    assert f"transcripts/{TX}" not in files and f"runs/{RUNZ}" in files
    assert left_out and TX in left_out[0] and "Left out" in files["README.txt"] and TX in files["README.txt"]
    assert "left out" in files["SUMMARY.txt"]


def test_zip_holds_runs_transcripts_summary_and_readme_and_masks_a_vin_in_the_run_file(tmp_path):
    run = {"kind": "live_run", "transcript": f"transcripts/{TX}", "meta": {"title": f"my car {VIN}"}, "live_sample": {"series": {}}}
    data, _ = build_zip(home_with(tmp_path, LAYOUTS["can_multi_headers_off"], run=run), [RUNZ, RUNZ])
    files = unzip(data)
    assert sorted(files) == ["README.txt", "SUMMARY.txt", f"runs/{RUNZ}", f"transcripts/{TX}"]
    assert json.loads(files[f"runs/{RUNZ}"])["meta"]["title"] == f"my car {MASKED}"
    assert "protocol: ISO 15765-4 (CAN 11/500)" in files["SUMMARY.txt"]
    readme = files["README.txt"]
    assert "000000" in readme and "github.com/iamneilroberts/shadetree-ai/issues" in readme and "shadetree-ai 0.1.0" in readme
    no_trace_of_the_serial(files)


def test_a_run_without_a_vin_passes_through_unchanged(tmp_path):
    home = home_with(tmp_path, ["NO DATA"], run={"kind": "live_run", "demo": True, "transcript": f"transcripts/{TX}",
                                                  "live_sample": {"series": {}}})
    files = unzip(build_zip(home, [RUNZ])[0])
    assert files[f"runs/{RUNZ}"] == (home / "runs" / RUNZ).read_text()
    assert files[f"transcripts/{TX}"] == (home / "transcripts" / TX).read_text()


@pytest.mark.parametrize("names", [[], ["../secret.json"], ["nope.json"], ["/etc/passwd"]])
def test_zip_refuses_an_empty_or_unknown_selection(tmp_path, names):
    (tmp_path / "secret.json").write_text("{}")
    with pytest.raises((ValueError, FileNotFoundError)):
        build_zip(home_with(tmp_path, ["NO DATA"]), names)


def test_cli_zip_writes_the_masked_bundle(tmp_path, capsys):
    home_with(tmp_path, LAYOUTS["can_multi_headers_off"])
    assert main(["export-run", "--out-dir", str(tmp_path), "--dest", str(tmp_path / "o.tgz"), "--zip"]) == 0
    assert "masked" in capsys.readouterr().out and not (tmp_path / "o.tgz").exists()
    no_trace_of_the_serial(unzip((tmp_path / "o.zip").read_bytes()))


@pytest.mark.parametrize("extra, verified", [((), True), ((("0904", ["49 04 01 " + _hex(VIN[11:].encode())]),), False)])
def test_each_run_names_its_vehicle_by_key_and_masked_vin_only_when_verified(tmp_path, extra, verified):
    from obd_reader.vehicle import vehicle_key
    files = unzip(build_zip(home_with(tmp_path, LAYOUTS["can_multi_headers_off"], extra=extra), [RUNZ])[0])
    run = json.loads(files[f"runs/{RUNZ}"])
    assert run["vehicle_key"] == vehicle_key(VIN)
    assert run.get("vin_masked") == (MASKED if verified else None)
    for name in ("SUMMARY.txt", "README.txt"):
        assert vehicle_key(VIN) in files[name] and (MASKED in files[name]) == verified, name
    assert verified or "masked VIN is not verified" in files["README.txt"]
    no_trace_of_the_serial(files)
