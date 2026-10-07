"""The Windows installer, launcher and guide: present, ASCII, and only real console flags."""
import re
from pathlib import Path

from obd_reader.__main__ import build_parser

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "install" / "install-windows.ps1"
BAT = ROOT / "install" / "shadetree-start.bat"
GUIDE = ROOT / "docs" / "windows-start-here.md"


def _console_flags() -> set[str]:
    sub = next(a for a in build_parser()._actions if a.dest == "cmd")
    return {s for a in sub.choices["console"]._actions for s in a.option_strings}


def test_files_exist():
    for f in (PS1, BAT, GUIDE):
        assert f.is_file(), f


def test_scripts_are_ascii_and_bat_has_crlf():
    for f in (PS1, BAT):
        f.read_bytes().decode("ascii")
    raw = BAT.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")   # a batch file with bare LF can break goto/labels


def test_launcher_uses_only_real_console_flags():
    flags = _console_flags()
    used = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", BAT.read_text()))
    # the installer runs pip and winget too: check only its lines about the console
    used |= {f for line in PS1.read_text().splitlines() if "console" in line
             for f in re.findall(r"(?<![\w-])--[a-z][a-z-]*", line)}
    assert {"--port", "--protocol", "--demo", "--host", "--allow-lan", "--out-dir"} <= used
    assert used <= flags, used - flags


def test_guide_covers_handheld_and_protocol():
    text = GUIDE.read_text()
    for needle in ("Handheld", "--protocol", "#v5", "read-only", "not been tested on a Windows machine"):
        assert needle in text, needle
