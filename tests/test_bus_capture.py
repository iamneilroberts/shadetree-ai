import pytest

from obd_reader.bus_capture import CaptureWriter, id_tokens_for, read_records, split_frame, summarize, summarize_file
from obd_reader.simulator import SIM_VIN
from obd_reader.vin import find_vins


def write(tmp_path, frames, steps=(), gaps=(), end_t=10.0):
    w = CaptureWriter(tmp_path / "captures" / "c.jsonl")
    w.header(protocol="A6", protocol_name="ISO 15765-4 (CAN 11/500)", adapter={"ati": "SIM"}, vehicle_key="1HGCM826-3", monitor_command="ATMA")
    for t, step, phase in steps:
        w.step(t, step, phase)
    for t, raw in frames:
        w.frame(t, raw)
    for t, reason, s in gaps:
        w.gap(t, reason, s)
    w.end(end_t, "finished")
    w.close()
    return w.path


def test_records_round_trip_in_order_with_types(tmp_path):
    p = write(tmp_path, [(0.5, "0C9 01 02")], steps=[(0.0, "brake", "start")], gaps=[(1.0, "BUFFER FULL", 0.2)])
    recs = list(read_records(p))
    assert [r["type"] for r in recs] == ["header", "step", "frame", "gap", "end"]
    assert recs[0]["schema"] == 1 and recs[2] == {"type": "frame", "t": 0.5, "raw": "0C9 01 02"}
    assert recs[-1]["frames"] == 1 and recs[-1]["gaps"] == 1 and recs[-1]["gap_seconds"] == 0.2


def test_the_writer_never_overwrites(tmp_path):
    p = write(tmp_path, [])
    with pytest.raises(FileExistsError):
        CaptureWriter(p)


def test_a_truncated_last_line_is_dropped_and_the_rest_summarizes(tmp_path):
    p = write(tmp_path, [(0.5, "0C9 01 02"), (1.0, "0C9 01 03")])
    p.write_text(p.read_text().rsplit("\n", 2)[0] + '\n{"type":"fra', encoding="utf-8")
    assert [r["type"] for r in read_records(p)][-1] == "frame"
    assert "| 0C9 |" in summarize(p)


@pytest.mark.parametrize("raw,n,want", [
    ("0C9 01 02", 1, ("0C9", ["01", "02"])),
    ("18 DA F1 10 03 41 0D 00", 4, ("18 DA F1 10", ["03", "41", "0D", "00"])),
    ("88 FE 10 0B 01 A2", 3, ("88 FE 10", ["0B", "01", "A2"])),
    ("BUFFER FULL", 1, None), ("0C9", 1, None), ("<RX ERROR", 1, None), ("", 1, None),
])
def test_split_frame(raw, n, want):
    assert split_frame(raw, n) == want


@pytest.mark.parametrize("dpn,n", [("A6", 1), ("6", 1), ("8", 1), ("A7", 4), ("9", 4), ("A2", 3), ("1", 3), ("5", 3), ("", 1)])
def test_id_tokens_for(dpn, n):
    assert id_tokens_for(dpn) == n


def test_the_summary_names_where_each_id_changed_and_rates(tmp_path):
    steps = [(0.0, "baseline", "start"), (2.0, "baseline", "end"), (4.0, "brake", "start"), (6.0, "brake", "end")]
    frames = [(t / 10, f"1F5 00 {int(t) % 16:02X}") for t in range(0, 100)]  # a counter: changes everywhere
    frames += [(t / 10, "3B4 20 00" if not 40 <= t < 60 else "3B4 20 01") for t in range(0, 100, 5)]  # only during brake
    md = summarize(write(tmp_path, sorted(frames), steps=steps))
    row = next(ln for ln in md.splitlines() if ln.startswith("| 3B4 |"))
    assert row.split("|")[2].strip() == "20" and row.split("|")[4].strip() == "2" and "brake" in row and "baseline" not in row
    assert "| 1F5 | 100 | 10.0 | 2 | 1 |" in md


def test_the_summary_holds_no_payload_bytes(tmp_path):
    hexvin = " ".join(f"{b:02X}" for b in SIM_VIN.encode("ascii"))
    p = write(tmp_path, [(0.1, "7E0 " + hexvin[:23]), (0.2, "7E1 " + hexvin[24:]), (0.3, "7E0 " + hexvin[:23])])
    md = summarize(p)
    assert find_vins(md) == [] and SIM_VIN not in md and hexvin[:23] not in md and "| 7E0 |" in md


def test_a_capture_with_no_frames_says_so(tmp_path):
    md = summarize(write(tmp_path, []))
    assert "No frames" in md and "| ID |" not in md


def test_summarize_file_writes_the_md_next_to_the_capture(tmp_path):
    p = write(tmp_path, [(0.5, "0C9 01 02")])
    md_path = summarize_file(p)
    assert md_path == p.with_suffix(".md") and "| 0C9 |" in md_path.read_text(encoding="utf-8")
    assert summarize_file(p) == md_path  # re-running overwrites


def test_a_larger_capture_summarizes_from_running_totals(tmp_path):
    steps = [(0.0, "idle", "start"), (10.0, "idle", "end"), (10.0, "rev", "start"), (20.0, "rev", "end")]
    frames = [(i / 100, f"100 00 {(i // 100) % 2:02X} 11") for i in range(2000)]  # byte 2 flips every second
    frames += [(i / 50, f"200 AA {i % 256:02X}") for i in range(1000)]  # a counter
    frames += [(i / 10, "300 01 02 03") for i in range(200)]  # never changes
    md = summarize(write(tmp_path, sorted(frames), steps=steps, gaps=[(5.0, "BUFFER FULL", 0.5)], end_t=20.0))
    assert "| 100 | 2000 | 100.0 | 3 | 1 | idle, rev |" in md
    assert "| 200 | 1000 | 50.0 | 2 | 1 | idle, rev |" in md
    assert "| 300 | 200 | 10.0 | 3 | 0 | — |" in md
    assert "gaps: 1 (0.5 s)" in md
