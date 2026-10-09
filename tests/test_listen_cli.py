import subprocess
from pathlib import Path

from obd_reader.__main__ import main
from obd_reader.bus_capture import read_records
from obd_reader.vin import find_vins

ROOT = Path(__file__).resolve().parent.parent


def test_listen_on_the_simulator_writes_a_capture_and_prints_the_summary(tmp_path, capsys):
    assert main(["listen", "--port", "sim", "--seconds", "1", "--label", "t", "--out-dir", str(tmp_path)]) == 0
    (cap,) = (tmp_path / "captures").glob("*-t.jsonl")
    out = capsys.readouterr().out
    assert cap.with_suffix(".md").exists() and "| 0C9 |" in out and str(cap) in out
    assert find_vins(cap.with_suffix(".md").read_text(encoding="utf-8")) == []


def test_summarize_reads_an_existing_capture(tmp_path, capsys):
    main(["listen", "--port", "sim", "--seconds", "1", "--label", "t", "--out-dir", str(tmp_path)])
    (cap,) = (tmp_path / "captures").glob("*-t.jsonl")
    capsys.readouterr()
    assert main(["listen", "--summarize", str(cap)]) == 0
    assert "| 0C9 |" in capsys.readouterr().out


def test_bad_arguments_are_errors_not_tracebacks(tmp_path, capsys):
    assert main(["listen", "--port", "sim", "--seconds", "0", "--out-dir", str(tmp_path)]) == 1
    assert main(["listen", "--port", "sim", "--seconds", "901", "--out-dir", str(tmp_path)]) == 1
    assert main(["listen", "--port", "sim", "--label", "Bad Label", "--out-dir", str(tmp_path)]) == 1
    assert "error:" in capsys.readouterr().err


def test_ctrl_c_reports_the_partial_capture(tmp_path, capsys, monkeypatch):
    import obd_reader.listen as lmod

    real = lmod.run_capture

    def interrupted(events, writer, *a, **k):
        def boom():
            yield next(iter(events))
            raise KeyboardInterrupt
        return real(boom(), writer, *a, **k)

    monkeypatch.setattr(lmod, "run_capture", interrupted)
    assert main(["listen", "--port", "sim", "--seconds", "1", "--label", "t", "--out-dir", str(tmp_path)]) == 130
    (cap,) = (tmp_path / "captures").glob("*-t.jsonl")
    assert "stopped" in capsys.readouterr().out and list(read_records(cap))[-1]["reason"] == "interrupted"


def test_ctrl_c_before_the_capture_does_not_name_an_older_one(tmp_path, capsys, monkeypatch):
    import obd_reader.listen as lmod

    (tmp_path / "captures").mkdir()
    old = tmp_path / "captures" / "20200101T000000Z-t.jsonl"
    old.write_text("{}\n")

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(lmod, "scan", interrupted)
    assert main(["listen", "--port", "sim", "--seconds", "1", "--label", "t", "--out-dir", str(tmp_path)]) == 130
    out = capsys.readouterr().out
    assert "stopped before the capture began" in out and old.name not in out


def test_captures_stay_gitignored():
    assert subprocess.run(["git", "check-ignore", "-q", "captures/x.jsonl"], cwd=ROOT).returncode == 0
