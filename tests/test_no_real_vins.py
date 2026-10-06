"""Guard: no real VIN may ever be committed to this public repo.

Real scans are gitignored (snapshots/, transcripts/, runs/). This test fails the suite if any tracked file
contains a VIN-looking token that is not on the reviewed allowlist of synthetic/public example VINs, and if
the capture directories stop being ignored. Adding a VIN to tests/vin_allowlist.txt is a deliberate, reviewable act.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from obd_reader.vin import find_vins

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "tests" / "vin_allowlist.txt"
pytestmark = pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(),
                                reason="needs a git checkout")


def allowed() -> set[str]:
    out = set()
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def tracked_text_files() -> list[Path]:
    names = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    files = []
    for name in names.split(b"\0"):
        if not name:
            continue
        p = ROOT / name.decode()
        if p.is_file() and p.stat().st_size < 5_000_000:
            files.append(p)
    return files


def scan(files: list[Path], root: Path = ROOT) -> dict[str, list[str]]:
    ok, hits = allowed(), {}
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary file
        bad = [v for v in find_vins(text) if v not in ok]
        if bad:
            hits[str(p.relative_to(root))] = bad
    return hits


def test_no_tracked_file_contains_a_vin_that_is_not_on_the_allowlist():
    hits = scan(tracked_text_files())
    # print only file names and a masked form: this message itself must not leak a VIN into CI logs
    masked = {f: [v[:8] + "*" * 9 for v in vs] for f, vs in hits.items()}
    assert not hits, f"real-looking VIN(s) in tracked files (remove them, or allowlist a synthetic one): {masked}"


def test_the_allowlist_only_contains_vins_and_explains_each_one():
    lines = [ln for ln in ALLOWLIST.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    assert lines, "allowlist should not be empty"
    for ln in lines:
        vin, _, why = ln.partition("#")
        assert len(vin.strip()) == 17 and why.strip(), f"each allowlisted VIN needs a reason: {ln!r}"


def test_capture_directories_are_gitignored():
    for path in ("snapshots/x.json", "transcripts/x.jsonl", "runs/x.json", "probes/x.json", "quirks-local/x.json", ".env"):
        r = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
        assert r.returncode == 0, f"{path} must stay gitignored"


def test_the_scanner_would_catch_a_leak(tmp_path):
    from obd_reader.vin import with_check_digit

    leak, clean = tmp_path / "leak.json", tmp_path / "clean.json"
    vin = with_check_digit("5FPYK3F5?RB999999")
    leak.write_text(f'{{"vin": "{vin}"}}')
    clean.write_text('{"vin": null}')
    assert vin not in allowed()
    assert scan([leak, clean], root=tmp_path) == {"leak.json": [vin]}
