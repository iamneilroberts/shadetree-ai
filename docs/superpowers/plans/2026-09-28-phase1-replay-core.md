# Phase 1 — Replay Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A car-free core: a read-only command allowlist gate, a recording transport, a transcript-driven fake adapter, a snapshot schema, and a minimal scanner that turns a recorded transcript into a snapshot.

**Architecture:** `allowlist.py` is pure and is the single source of truth for what may be sent. `transport.py` is the only module that may import `serial`; every write passes through `check_command` first and is recorded to a transcript. `replay.py` implements the same `Port` interface from a transcript, so the scanner runs identically live and offline. `scanner.py` builds a pydantic `Snapshot` (VIN, protocol, supported PIDs, DTCs, MIL).

**Tech Stack:** Python 3.12 (floor 3.11), pydantic v2, pyserial, pytest, hypothesis, setuptools (src layout).

**Spec:** `docs/design.md` (§4 architecture, §5 allowlist, §6 snapshot schema, §10 Phase 1). Research: `docs/research/data-sources.md` (not needed in this phase).

## Global Constraints

- Python `>=3.11`; src layout `src/obd_reader/`; tests in `tests/`.
- Allowed OBD modes, verbatim from the spec: **01, 02, 03, 07, 09, 0A** (Mode 06 and UDS 0x19 are NOT enabled in Phase 1).
- Only `src/obd_reader/transport.py` may import `serial` (or use `__import__` / `importlib.import_module`).
- No API in this phase accepts a raw command string from a tool/CLI user; the only command-string entry point is `Transport.send`, which gates it.
- Snapshot `schema_version` is `"0.1"`; unknown fields are rejected (`extra="forbid"`).
- Transcript lines are JSONL `{"t": float, "tx": str, "rx": [str]}`; `tx` is the canonical (uppercase, spaceless) command.
- Real transcripts/snapshots are gitignored; only `tests/fixtures/**` is committed.
- **Repo rule (CLAUDE.md): stage files by name; do not commit until Neil says so.** Every "Commit" step below is: stage the named files, then commit only if Neil has approved per-task commits for this branch; otherwise leave staged and continue.
- Run all work in a worktree (`EnterWorktree` name `phase1-replay-core`), not the main clone.
- No hardware and no network access in this phase.

## Review Focus

Failure modes the spec implies but a happy-path test would miss (each has a test in the owning task):

1. Command with embedded/trailing CR/LF (`"0100\r04"`, `"0100\n"`) must be rejected, never split into two writes. → Task 1.
2. Non-ASCII look-alikes / Unicode case folding (`"ATı"` upper-cases to `"ATI"`; full-width `"ＡＴＺ"`) must be rejected, and the gate returns the canonical string that is actually written. → Task 1.
3. Adapter answers `NO DATA` / `?` / a negative response for Mode 09 → VIN is `None` with a warning and the scan does not crash or request `0902`. → Task 6.
4. Truncated or garbage multi-frame response (declared length larger than data, non-hex lines) → parser returns `None`, never raises. → Task 4.
5. Malformed VIN from the adapter (contains `I/O/Q`, wrong length) → snapshot VIN is `None` with a warning; the schema itself also rejects a bad VIN. → Tasks 3 and 6.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package + dev deps + pytest config |
| `src/obd_reader/__init__.py` | `__version__` |
| `src/obd_reader/allowlist.py` | `ALLOWED_MODES`, `ForbiddenCommand`, `check_command()` |
| `src/obd_reader/transport.py` | `Port` protocol, `TranscriptRecorder`, `Transport` (gate + record), `SerialPort` (only `serial` importer) |
| `src/obd_reader/snapshot.py` | Pydantic snapshot models, `VIN_RE` |
| `src/obd_reader/elm.py` | Response parsing (`parse_response`), DTC and supported-PID decoding |
| `src/obd_reader/replay.py` | `load_transcript`, `ReplayPort` |
| `src/obd_reader/scanner.py` | `scan()` → `Snapshot` |
| `src/obd_reader/__main__.py` | `python -m obd_reader replay <transcript>` |
| `tests/conftest.py` | `SpyPort` |
| `tests/test_allowlist.py`, `test_transport.py`, `test_import_boundary.py`, `test_snapshot.py`, `test_elm.py`, `test_replay.py`, `test_scanner.py` | Tests |
| `tests/fixtures/synthetic_sedan.jsonl` | Hand-written CAN 11/500 transcript (P0171 stored, MIL on) |

---

### Task 1: Scaffold + allowlist gate

**Files:**
- Create: `pyproject.toml`, `src/obd_reader/__init__.py`, `src/obd_reader/allowlist.py`
- Test: `tests/test_allowlist.py`

**Interfaces:**
- Produces: `obd_reader.allowlist.ALLOWED_MODES: frozenset[int]`, `ForbiddenCommand(ValueError)`, `check_command(cmd: str) -> str` (returns the canonical command; raises `ForbiddenCommand` otherwise).

- [ ] **Step 1: Scaffold the package and venv**

```bash
cd /home/neil/dev/obd-reader
mkdir -p src/obd_reader tests/fixtures
```

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "obd-reader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.6", "pyserial>=3.5"]

[project.optional-dependencies]
dev = ["pytest>=8", "hypothesis>=6.100"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create `src/obd_reader/__init__.py`:

```python
__version__ = "0.1.0"
```

```bash
python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
```

Expected: installs without error (pip in a venv; no system packages).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_allowlist.py`:

```python
import pytest
from hypothesis import given, strategies as st

from obd_reader.allowlist import ALLOWED_MODES, ForbiddenCommand, check_command

# mode -> number of argument bytes the request takes
ARG_BYTES = {0x01: 1, 0x02: 2, 0x03: 0, 0x07: 0, 0x09: 1, 0x0A: 0}

ALLOWED = [
    "0100", "01 0C", "020C00", "03", "07", "0900", "0902", "0A",
    "ATZ", "ATD", "ATWS", "ATE0", "ATL0", "ATS0", "ATH1", "ATSP6", "ATSPA6",
    "ATTP6", "ATDP", "ATDPN", "ATRV", "ATI", "AT@1", "ATCAF1", "ATST64",
    "ATAT1", "ATSH7DF", "ATSH7E0", "ATCRA7E8", "ATCRA", "STI", "STDI",
    "  at i ",
]

FORBIDDEN = [
    # services outside the allowlist
    "04", "0400", "05", "0500", "06", "0600", "08", "0800", "0B", "0C", "0E",
    "10", "1901", "22F190", "2F", "3101",
    # ELM/STN commands that write, persist, or flood
    "ATPP", "ATPP0CSV01", "ATPPS", "ATMA", "ATCF", "ATCM", "STPX", "STPXH7DF", "STSAVE",
    # wrong argument length
    "010", "01000", "0200", "020C", "0300", "0A00",
    # injection / framing tricks (Review Focus 1)
    "0100\r04", "0100\n", "0100\r", "ATZ\rATPP0CSV01",
    # unicode look-alikes (Review Focus 2)
    "ATı", "ＡＴＺ", "０１００",
    "", " ",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed_commands_pass_and_are_canonical(cmd):
    canon = check_command(cmd)
    assert canon == cmd.replace(" ", "").upper()
    assert canon.isascii()


@pytest.mark.parametrize("cmd", FORBIDDEN)
def test_forbidden_commands_raise(cmd):
    with pytest.raises(ForbiddenCommand):
        check_command(cmd)


@pytest.mark.parametrize("cmd", [None, b"0100", 100, ["0100"]])
def test_non_string_input_raises(cmd):
    with pytest.raises(ForbiddenCommand):
        check_command(cmd)


def assert_modes_rejected(check):
    """Exhaustive: every hex frame is accepted iff mode+arg length is on the list."""
    for mode in range(256):
        for n_args in range(4):
            cmd = f"{mode:02X}" + "00" * n_args
            expected = ARG_BYTES.get(mode) == n_args
            try:
                check(cmd)
                accepted = True
            except ForbiddenCommand:
                accepted = False
            assert accepted == expected, cmd


def test_every_hex_frame_is_classified_correctly():
    assert_modes_rejected(check_command)
    assert ALLOWED_MODES == frozenset(ARG_BYTES)


def test_mutation_check_a_gate_that_allows_mode_04_is_caught():
    def mutant(cmd):
        if cmd.replace(" ", "").upper() == "04":
            return "04"
        return check_command(cmd)

    with pytest.raises(AssertionError):
        assert_modes_rejected(mutant)


_ALPHABET = "0123456789ABCDEFabcdef ATSPHCRDLEIZWMXQ@\r\n\t"


@given(st.text(alphabet=_ALPHABET, max_size=14))
def test_fuzz_near_miss_strings(s):
    try:
        canon = check_command(s)
    except ForbiddenCommand:
        return
    assert canon.isascii() and "\r" not in canon and "\n" not in canon
    if canon[:2] in ("AT", "ST"):
        assert not canon.startswith(("ATPP", "ATMA", "STPX"))
    else:
        assert int(canon[:2], 16) in ALLOWED_MODES


@given(st.text(max_size=20))
def test_fuzz_arbitrary_unicode_never_yields_non_ascii(s):
    try:
        canon = check_command(s)
    except ForbiddenCommand:
        return
    assert canon.isascii()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_allowlist.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'obd_reader.allowlist'`.

- [ ] **Step 4: Write the implementation**

Create `src/obd_reader/allowlist.py`:

```python
"""Read-only command allowlist: the single source of truth for what may be sent.

`check_command` returns the canonical (uppercase, spaceless, ASCII) command that
the transport writes. Anything else raises ForbiddenCommand.

Not enabled yet (see docs/design.md §13): Mode 06, UDS 0x19, STIX-style STN
commands (unverified on hardware), ATPPS.
"""
import re

ALLOWED_MODES = frozenset({0x01, 0x02, 0x03, 0x07, 0x09, 0x0A})


class ForbiddenCommand(ValueError):
    """Raised for any command that is not on the read-only allowlist."""


_H = "[0-9A-F]"
_PATTERNS = tuple(
    re.compile(p)
    for p in (
        # OBD services: hex, spaces removed, exact argument lengths
        rf"01{_H}{{2}}",      # Mode 01 PID
        rf"02{_H}{{4}}",      # Mode 02 PID + frame number
        r"03",                # stored DTCs
        r"07",                # pending DTCs
        rf"09{_H}{{2}}",      # Mode 09 PID
        r"0A",                # permanent DTCs
        # ELM327 AT commands (explicit list)
        r"ATZ", r"ATD", r"ATWS",
        r"ATE[01]", r"ATL[01]", r"ATS[01]", r"ATH[01]",
        r"ATDPN?", r"ATRV", r"ATI", r"AT@1",
        r"ATCAF[01]", r"ATAT[012]",
        r"ATSPA?[0-9A-C]", r"ATTPA?[0-9A-C]",
        rf"ATST{_H}{{2}}",
        rf"ATSH(?:{_H}{{3}}|{_H}{{6}}|{_H}{{8}})",
        rf"ATCRA(?:{_H}{{3}}|{_H}{{8}})?",
        # STN identify (read-only)
        r"STI", r"STDI",
    )
)


def check_command(cmd: str) -> str:
    if not isinstance(cmd, str) or not cmd.isascii():
        raise ForbiddenCommand(f"not an ASCII string: {cmd!r}")
    canon = cmd.replace(" ", "").upper()
    if any(p.fullmatch(canon) for p in _PATTERNS):
        return canon
    raise ForbiddenCommand(f"not on the read-only allowlist: {cmd!r}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_allowlist.py -q`
Expected: all pass (the hypothesis tests run ~100 examples each).

- [ ] **Step 6: Stage (commit only if Neil approved per-task commits)**

```bash
git add pyproject.toml src/obd_reader/__init__.py src/obd_reader/allowlist.py tests/test_allowlist.py
git commit -m "feat: read-only command allowlist with exhaustive and fuzz tests"
```

---

### Task 2: Transport (gate, recorder, serial port) + import boundary

**Files:**
- Create: `src/obd_reader/transport.py`, `tests/conftest.py`
- Test: `tests/test_transport.py`, `tests/test_import_boundary.py`

**Interfaces:**
- Consumes: `check_command`, `ForbiddenCommand` from Task 1.
- Produces:
  - `Port` (Protocol): `write(data: bytes) -> None`, `read_until_prompt(timeout: float) -> str` (text before the `>` prompt), `close() -> None`.
  - `TranscriptRecorder(path: Path)`: `record(t: float, tx: str, rx: list[str])`, `close()`.
  - `Transport(port: Port, recorder: TranscriptRecorder | None = None, clock=time.monotonic)`: `send(cmd: str, timeout: float = 5.0) -> list[str]` (non-empty stripped lines), `close()`.
  - `SerialPort(url: str, baudrate: int = 115200)`: a `Port` backed by pyserial (`serial_for_url`).

- [ ] **Step 1: Write the failing tests**

Create `tests/conftest.py`:

```python
import pytest


class SpyPort:
    """Records every byte string written; replies with a canned response."""

    def __init__(self, reply: str = "OK\r"):
        self.writes: list[bytes] = []
        self.reply = reply

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def read_until_prompt(self, timeout: float) -> str:
        return self.reply

    def close(self) -> None:
        pass


@pytest.fixture
def spy():
    return SpyPort()
```

Create `tests/test_transport.py`:

```python
import json

import pytest
from hypothesis import given, strategies as st

from obd_reader.allowlist import ForbiddenCommand, check_command
from obd_reader.transport import SerialPort, Transport, TranscriptRecorder

from conftest import SpyPort


def test_send_writes_canonical_command_with_cr_and_returns_lines():
    port = SpyPort(reply="\r41 00 BE 3F A8 13\r\r")
    t = Transport(port)
    assert t.send("01 00") == ["41 00 BE 3F A8 13"]
    assert port.writes == [b"0100\r"]


def test_forbidden_command_never_reaches_the_port(spy):
    t = Transport(spy)
    with pytest.raises(ForbiddenCommand):
        t.send("04")
    assert spy.writes == []


@given(st.text(max_size=20))
def test_fuzz_only_allowlisted_bytes_reach_the_port(s):
    port = SpyPort()
    t = Transport(port)
    try:
        t.send(s)
    except ForbiddenCommand:
        assert port.writes == []
        return
    assert len(port.writes) == 1
    written = port.writes[0]
    assert written.endswith(b"\r") and written.count(b"\r") == 1
    assert check_command(written[:-1].decode("ascii")) == written[:-1].decode("ascii")


def test_recorder_writes_jsonl(tmp_path):
    path = tmp_path / "t.jsonl"
    ticks = iter([10.0, 10.5])
    rec = TranscriptRecorder(path)
    t = Transport(SpyPort(reply="OK\r"), recorder=rec, clock=lambda: next(ticks))
    t.send("ATE0")
    rec.close()
    line = json.loads(path.read_text().splitlines()[0])
    assert line == {"t": 0.5, "tx": "ATE0", "rx": ["OK"]}


def test_forbidden_command_is_not_recorded(tmp_path):
    path = tmp_path / "t.jsonl"
    rec = TranscriptRecorder(path)
    t = Transport(SpyPort(), recorder=rec)
    with pytest.raises(ForbiddenCommand):
        t.send("04")
    rec.close()
    assert path.read_text() == ""


def test_serial_port_reads_up_to_prompt_using_loopback():
    port = SerialPort("loop://")
    port._ser.write(b"NO DATA\r\r>")
    assert port.read_until_prompt(1.0) == "NO DATA\r\r"
    port.close()
```

Create `tests/test_import_boundary.py`:

```python
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "obd_reader"


def serial_touchers(root: Path) -> set[str]:
    """File names under root that import serial or use dynamic import tricks."""
    found = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(n == "serial" or n.startswith("serial.") for n in names):
                found.add(path.name)
            if isinstance(node, ast.Name) and node.id == "__import__":
                found.add(path.name)
            if isinstance(node, ast.Attribute) and node.attr == "import_module":
                found.add(path.name)
    return found


def test_only_transport_touches_serial():
    assert serial_touchers(SRC) == {"transport.py"}


def test_detector_flags_a_violation(tmp_path):
    (tmp_path / "ok.py").write_text("import json\n")
    (tmp_path / "bad1.py").write_text("import serial\n")
    (tmp_path / "bad2.py").write_text("from serial.tools import list_ports\n")
    (tmp_path / "bad3.py").write_text("m = __import__('serial')\n")
    (tmp_path / "bad4.py").write_text("import importlib\nimportlib.import_module('serial')\n")
    assert serial_touchers(tmp_path) == {"bad1.py", "bad2.py", "bad3.py", "bad4.py"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_transport.py tests/test_import_boundary.py -q`
Expected: `ModuleNotFoundError: No module named 'obd_reader.transport'` for `test_transport.py`; in `test_import_boundary.py`, `test_only_transport_touches_serial` fails with `set() != {'transport.py'}` and the detector test passes.

- [ ] **Step 3: Write the implementation**

Create `src/obd_reader/transport.py`:

```python
"""The only module allowed to import `serial`. Every write goes through the gate."""
import json
import time
from pathlib import Path
from typing import Callable, Protocol

from obd_reader.allowlist import check_command


class Port(Protocol):
    def write(self, data: bytes) -> None: ...
    def read_until_prompt(self, timeout: float) -> str: ...
    def close(self) -> None: ...


class TranscriptRecorder:
    def __init__(self, path: Path):
        self._fh = open(path, "w", encoding="utf-8")

    def record(self, t: float, tx: str, rx: list[str]) -> None:
        self._fh.write(json.dumps({"t": round(t, 3), "tx": tx, "rx": rx}) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class Transport:
    def __init__(
        self,
        port: Port,
        recorder: TranscriptRecorder | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._port = port
        self._recorder = recorder
        self._clock = clock
        self._t0 = clock()

    def send(self, cmd: str, timeout: float = 5.0) -> list[str]:
        canon = check_command(cmd)  # raises before anything touches the port
        self._port.write(canon.encode("ascii") + b"\r")
        raw = self._port.read_until_prompt(timeout)
        lines = [ln.strip() for ln in raw.replace("\r", "\n").split("\n") if ln.strip()]
        if self._recorder is not None:
            self._recorder.record(self._clock() - self._t0, canon, lines)
        return lines

    def close(self) -> None:
        self._port.close()
        if self._recorder is not None:
            self._recorder.close()


class SerialPort:
    """pyserial-backed Port (USB serial, rfcomm, socket://, loop:// for tests)."""

    def __init__(self, url: str, baudrate: int = 115200):
        import serial

        self._ser = serial.serial_for_url(url, baudrate=baudrate, timeout=0.1)

    def write(self, data: bytes) -> None:
        self._ser.write(data)

    def read_until_prompt(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._ser.read(64)
            if chunk:
                buf += chunk
                if b">" in buf:
                    break
        return buf.decode("ascii", errors="replace").split(">", 1)[0]

    def close(self) -> None:
        self._ser.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_transport.py tests/test_import_boundary.py -q`
Expected: all pass.

- [ ] **Step 5: Stage (commit only if Neil approved per-task commits)**

```bash
git add src/obd_reader/transport.py tests/conftest.py tests/test_transport.py tests/test_import_boundary.py
git commit -m "feat: gated recording transport and serial-import boundary test"
```

---

### Task 3: Snapshot schema

**Files:**
- Create: `src/obd_reader/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Produces (`obd_reader.snapshot`): `VIN_RE` (compiled regex), models `Adapter`, `Source`, `Decoded`, `Vehicle`, `Protocol`, `Ecu`, `Dtc`, `Dtcs`, `Mil`, `Snapshot`. Field names and shapes follow `docs/design.md` §6. `Snapshot` has `snapshot_id: str`, `captured_at: datetime`, `source: Source`, `vehicle: Vehicle`, `protocol: Protocol`, `supported_pids: dict[str, list[str]]`, `dtcs: Dtcs`, `mil: Mil`, `warnings: list[str]`. (Freeze frame, readiness, live sample, user_context arrive in later phases.)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_snapshot.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from obd_reader.snapshot import Dtc, Dtcs, Snapshot, Source, Vehicle


def make(**over):
    base = dict(
        snapshot_id="x",
        captured_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        source=Source(kind="replay", tool_version="0.1.0"),
    )
    base.update(over)
    return Snapshot(**base)


def test_defaults_are_sensible():
    s = make()
    assert s.schema_version == "0.1"
    assert s.vehicle.vin is None and s.vehicle.vin_source == "none"
    assert s.dtcs.stored == [] and s.warnings == []


def test_json_round_trip():
    s = make(
        vehicle=Vehicle(vin="1HGCM82633A004352", vin_source="obd"),
        dtcs=Dtcs(stored=[Dtc(code="P0171")]),
        supported_pids={"01": ["0C", "0D"]},
    )
    assert Snapshot.model_validate_json(s.model_dump_json()) == s


@pytest.mark.parametrize("vin", ["1HGCM82633A00435", "1HGCM82633A0043521", "1HGCM82633AO04352", "1hgcm82633a004352", ""])
def test_bad_vin_is_rejected(vin):
    with pytest.raises(ValidationError):
        Vehicle(vin=vin, vin_source="manual")


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        make(surprise=1)


def test_wrong_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        make(schema_version="0.2")


def test_json_schema_is_exportable():
    schema = Snapshot.model_json_schema()
    assert "schema_version" in schema["properties"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_snapshot.py -q`
Expected: `ModuleNotFoundError: No module named 'obd_reader.snapshot'`.

- [ ] **Step 3: Write the implementation**

Create `src/obd_reader/snapshot.py`:

```python
"""Snapshot schema v0.1 (docs/design.md §6). Later phases add freeze frame,
readiness monitors, live samples, and user context."""
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VIN_RE = re.compile(r"[A-HJ-NPR-Z0-9]{17}")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Adapter(_Model):
    ati: str | None = None
    sti: str | None = None
    chip: str | None = None
    genuine_stn: bool | None = None


class Source(_Model):
    kind: Literal["live", "replay", "import"]
    adapter: Adapter = Field(default_factory=Adapter)
    tool_version: str
    transcript: str | None = None


class Decoded(_Model):
    make: str | None = None
    model: str | None = None
    year: int | None = None
    engine: str | None = None
    source: str | None = None
    error_code: str | None = None


class Vehicle(_Model):
    vin: str | None = None
    vin_source: Literal["obd", "manual", "photo", "none"] = "none"
    decoded: Decoded | None = None

    @field_validator("vin")
    @classmethod
    def _check_vin(cls, v: str | None) -> str | None:
        if v is not None and not VIN_RE.fullmatch(v):
            raise ValueError("invalid VIN")
        return v


class Protocol(_Model):
    name: str | None = None
    atsp: str | None = None
    pinned: bool = False


class Ecu(_Model):
    header: str
    role: str | None = None
    modes_seen: list[str] = Field(default_factory=list)


class Dtc(_Model):
    code: str
    ecu: str | None = None
    ref: str | None = None


class Dtcs(_Model):
    stored: list[Dtc] = Field(default_factory=list)
    pending: list[Dtc] = Field(default_factory=list)
    permanent: list[Dtc] = Field(default_factory=list)


class Mil(_Model):
    on: bool | None = None
    dtc_count: int | None = None


class Snapshot(_Model):
    schema_version: Literal["0.1"] = "0.1"
    snapshot_id: str
    captured_at: datetime
    source: Source
    vehicle: Vehicle = Field(default_factory=Vehicle)
    protocol: Protocol = Field(default_factory=Protocol)
    ecus: list[Ecu] = Field(default_factory=list)
    supported_pids: dict[str, list[str]] = Field(default_factory=dict)
    dtcs: Dtcs = Field(default_factory=Dtcs)
    mil: Mil = Field(default_factory=Mil)
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_snapshot.py -q`
Expected: all pass.

- [ ] **Step 5: Stage (commit only if Neil approved per-task commits)**

```bash
git add src/obd_reader/snapshot.py tests/test_snapshot.py
git commit -m "feat: snapshot schema v0.1"
```

---

### Task 4: ELM response parsing and decoders

**Files:**
- Create: `src/obd_reader/elm.py`
- Test: `tests/test_elm.py`

**Interfaces:**
- Produces (`obd_reader.elm`):
  - `parse_response(lines: list[str], sid: int) -> bytes | None` — payload starting at the response SID (e.g. `0x41`), or `None` for `NO DATA`/`?`/errors/negative responses/garbled or truncated data. Never raises.
  - `decode_dtc(b1: int, b2: int) -> str`
  - `decode_dtc_list(payload: bytes) -> list[str]` — CAN format `SID, count, pairs…`; zero pairs skipped. (Non-CAN Mode 03 has no count byte — Phase 4.)
  - `decode_supported(base_pid: int, data: bytes) -> list[str]` — two-hex-digit PID strings from a 4-byte bitmap.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_elm.py`:

```python
import pytest

from obd_reader.elm import decode_dtc, decode_dtc_list, decode_supported, parse_response


def test_single_frame():
    assert parse_response(["41 00 BE 3F A8 13"], 0x41) == bytes.fromhex("4100BE3FA813")


def test_searching_line_is_ignored():
    assert parse_response(["SEARCHING...", "41 0C 1A F8"], 0x41) == bytes.fromhex("410C1AF8")


def test_multi_frame_vin():
    lines = ["014", "0: 49 02 01 31 48 47", "1: 43 4D 38 32 36 33 33", "2: 41 30 30 34 33 35 32"]
    payload = parse_response(lines, 0x49)
    assert payload[:3] == bytes([0x49, 0x02, 0x01])
    assert payload[3:].decode("ascii") == "1HGCM82633A004352"


@pytest.mark.parametrize(
    "lines",
    [
        ["NO DATA"],
        ["?"],
        ["UNABLE TO CONNECT"],
        ["CAN ERROR"],
        ["7F 09 12"],                       # negative response
        [],                                 # empty reply
        ["41 0C 1A F8"],                    # wrong SID for the request below
    ],
)
def test_unsupported_or_wrong_sid_returns_none(lines):
    assert parse_response(lines, 0x49) is None


def test_truncated_multi_frame_returns_none():  # Review Focus 4
    lines = ["014", "0: 49 02 01 31 48 47", "1: 43 4D 38 32 36 33 33"]
    assert parse_response(lines, 0x49) is None


@pytest.mark.parametrize(
    "lines",
    [["014", "garbage"], ["ZZ ZZ"], ["41 0"], ["0FF"], ["000", "0: 49"]],
)
def test_garbage_returns_none_and_never_raises(lines):  # Review Focus 4
    assert parse_response(lines, 0x49) is None


@pytest.mark.parametrize(
    "b1,b2,code",
    [(0x01, 0x71, "P0171"), (0x43, 0x00, "C0300"), (0x80, 0x00, "B0000"), (0xC1, 0x00, "U0100"), (0x21, 0x04, "P2104")],
)
def test_decode_dtc(b1, b2, code):
    assert decode_dtc(b1, b2) == code


def test_decode_dtc_list_skips_padding_and_honours_count():
    assert decode_dtc_list(bytes.fromhex("4302 0171 C100 0000")) == ["P0171", "U0100"]
    assert decode_dtc_list(bytes.fromhex("43 00 00 00 00 00 00")) == []
    assert decode_dtc_list(b"\x43") == []


def test_decode_dtc_list_tolerates_truncation():
    assert decode_dtc_list(bytes.fromhex("43 02 01 71 C1")) == ["P0171"]


def test_decode_supported():
    pids = decode_supported(0x00, bytes.fromhex("BE3FA813"))
    for expected in ["01", "03", "04", "05", "06", "07", "0B", "0C", "0D", "0E", "0F", "10", "11", "13", "15", "1C", "1F", "20"]:
        assert expected in pids
    for absent in ["02", "08", "09", "0A", "12", "14"]:
        assert absent not in pids
    assert decode_supported(0x20, bytes.fromhex("80000000")) == ["21"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_elm.py -q`
Expected: `ModuleNotFoundError: No module named 'obd_reader.elm'`.

- [ ] **Step 3: Write the implementation**

Create `src/obd_reader/elm.py`:

```python
"""ELM/STN response parsing for headers-off (ATH0) output, spaces on (ATS1 default)."""
import re

ERROR_MARKERS = (
    "NO DATA", "UNABLE TO CONNECT", "BUS INIT", "CAN ERROR", "BUS BUSY",
    "BUFFER FULL", "STOPPED", "ERROR", "?",
)
_HEX_LINE = re.compile(r"(?:[0-9A-F]{2} ?)+")
_LEN_LINE = re.compile(r"[0-9A-F]{3}")
_FRAME_LINE = re.compile(r"[0-9A-F]+: ((?:[0-9A-F]{2} ?)+)")


def parse_response(lines: list[str], sid: int) -> bytes | None:
    """Payload starting at the response SID, or None if unsupported/garbled."""
    lines = [ln.strip().upper() for ln in lines if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith("SEARCHING")]
    if not lines or any(m in ln for ln in lines for m in ERROR_MARKERS):
        return None

    if _LEN_LINE.fullmatch(lines[0]) and len(lines) > 1:  # ISO-TP multi-frame
        total = int(lines[0], 16)
        data = b""
        for ln in lines[1:]:
            m = _FRAME_LINE.fullmatch(ln)
            if not m:
                return None
            data += bytes.fromhex(m.group(1))
        if len(data) < total:
            return None
        payload = data[:total]
    else:  # single frame; take the first line that carries the expected SID
        payload = None
        for ln in lines:
            if _HEX_LINE.fullmatch(ln):
                candidate = bytes.fromhex(ln)
                if candidate[:1] == bytes([sid]):
                    payload = candidate
                    break
        if payload is None:
            return None

    return payload if payload[:1] == bytes([sid]) else None


def decode_dtc(b1: int, b2: int) -> str:
    letter = "PCBU"[b1 >> 6]
    return f"{letter}{(b1 >> 4) & 0x3}{b1 & 0xF:X}{b2:02X}"


def decode_dtc_list(payload: bytes) -> list[str]:
    """CAN layout: SID, count, then 2-byte DTCs (zero pairs are padding)."""
    if len(payload) < 2:
        return []
    pairs = payload[2 : 2 + 2 * payload[1]]
    out = []
    for i in range(0, len(pairs) - 1, 2):
        if pairs[i] == 0 and pairs[i + 1] == 0:
            continue
        out.append(decode_dtc(pairs[i], pairs[i + 1]))
    return out


def decode_supported(base_pid: int, data: bytes) -> list[str]:
    mask = int.from_bytes(data[:4].ljust(4, b"\x00"), "big")
    return [f"{base_pid + i + 1:02X}" for i in range(32) if mask & (0x80000000 >> i)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_elm.py -q`
Expected: all pass. If `test_garbage_returns_none_and_never_raises` fails on `["0FF"]` or `["000", "0: 49"]`, that is a parser bug: fix `parse_response` (do not loosen the test).

- [ ] **Step 5: Stage (commit only if Neil approved per-task commits)**

```bash
git add src/obd_reader/elm.py tests/test_elm.py
git commit -m "feat: ELM response parser and DTC/PID decoders"
```

---

### Task 5: Replay port + synthetic fixture

**Files:**
- Create: `src/obd_reader/replay.py`, `tests/fixtures/synthetic_sedan.jsonl`
- Test: `tests/test_replay.py`

**Interfaces:**
- Consumes: `Port` shape from Task 2.
- Produces (`obd_reader.replay`): `load_transcript(path: Path) -> list[dict]`; `ReplayPort(records: list[dict])` with `.written: list[str]` (canonical commands received), `.unmatched: list[str]` (commands with no recorded reply; they get `?`), classmethod `ReplayPort.from_file(path)`. Replies are matched per command in FIFO order.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/synthetic_sedan.jsonl` (hand-written, not from a real car; CAN 11/500, VIN `1HGCM82633A004352`, P0171 stored, MIL on):

```
{"t":0.0,"tx":"ATZ","rx":["ELM327 v1.5"]}
{"t":1.1,"tx":"ATE0","rx":["OK"]}
{"t":1.2,"tx":"ATL0","rx":["OK"]}
{"t":1.3,"tx":"ATH0","rx":["OK"]}
{"t":1.4,"tx":"ATSP6","rx":["OK"]}
{"t":1.5,"tx":"ATI","rx":["ELM327 v1.5"]}
{"t":1.6,"tx":"STI","rx":["?"]}
{"t":1.7,"tx":"ATDP","rx":["ISO 15765-4 (CAN 11/500)"]}
{"t":1.9,"tx":"0100","rx":["41 00 BE 3F A8 13"]}
{"t":2.0,"tx":"0120","rx":["41 20 80 00 00 00"]}
{"t":2.1,"tx":"0900","rx":["49 00 40 00 00 00"]}
{"t":2.3,"tx":"0902","rx":["014","0: 49 02 01 31 48 47","1: 43 4D 38 32 36 33 33","2: 41 30 30 34 33 35 32"]}
{"t":2.5,"tx":"03","rx":["43 01 01 71 00 00 00"]}
{"t":2.6,"tx":"07","rx":["47 00 00 00 00 00 00"]}
{"t":2.7,"tx":"0A","rx":["4A 00 00 00 00 00 00"]}
{"t":2.8,"tx":"0101","rx":["41 01 81 07 65 04"]}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_replay.py`:

```python
from pathlib import Path

from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.transport import Transport

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_sedan.jsonl"


def test_load_transcript_reads_jsonl():
    records = load_transcript(FIXTURE)
    assert records[0] == {"t": 0.0, "tx": "ATZ", "rx": ["ELM327 v1.5"]}
    assert len(records) == 16


def test_replies_come_from_the_transcript_through_the_transport():
    port = ReplayPort.from_file(FIXTURE)
    t = Transport(port)
    assert t.send("0100") == ["41 00 BE 3F A8 13"]
    assert port.written == ["0100"]
    assert port.unmatched == []


def test_unknown_command_gets_question_mark_and_is_reported():
    port = ReplayPort([])
    t = Transport(port)
    assert t.send("0100") == ["?"]
    assert port.unmatched == ["0100"]


def test_repeated_commands_are_served_in_fifo_order_then_run_out():
    port = ReplayPort([{"tx": "0105", "rx": ["41 05 5A"]}, {"tx": "0105", "rx": ["41 05 5B"]}])
    t = Transport(port)
    assert t.send("0105") == ["41 05 5A"]
    assert t.send("0105") == ["41 05 5B"]
    assert t.send("0105") == ["?"]
    assert port.unmatched == ["0105"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_replay.py -q`
Expected: `ModuleNotFoundError: No module named 'obd_reader.replay'`.

- [ ] **Step 4: Write the implementation**

Create `src/obd_reader/replay.py`:

```python
"""A Port that answers from a recorded transcript: no adapter, no car."""
import json
from collections import defaultdict, deque
from pathlib import Path


def load_transcript(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


class ReplayPort:
    def __init__(self, records: list[dict]):
        self._queues: dict[str, deque] = defaultdict(deque)
        for r in records:
            self._queues[r["tx"]].append(r["rx"])
        self.written: list[str] = []
        self.unmatched: list[str] = []
        self._pending = ""

    @classmethod
    def from_file(cls, path: Path) -> "ReplayPort":
        return cls(load_transcript(path))

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        self.written.append(cmd)
        queue = self._queues.get(cmd)
        if queue:
            rx = queue.popleft()
        else:
            self.unmatched.append(cmd)
            rx = ["?"]  # what a real ELM answers to an unknown command
        self._pending = "\r".join(rx) + "\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def close(self) -> None:
        pass
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_replay.py -q`
Expected: all pass.

- [ ] **Step 6: Stage (commit only if Neil approved per-task commits)**

```bash
git add src/obd_reader/replay.py tests/fixtures/synthetic_sedan.jsonl tests/test_replay.py
git commit -m "feat: transcript-driven replay port and synthetic fixture"
```

---

### Task 6: Scanner + CLI demo

**Files:**
- Create: `src/obd_reader/scanner.py`, `src/obd_reader/__main__.py`
- Test: `tests/test_scanner.py`

**Interfaces:**
- Consumes: `Transport` (Task 2), `parse_response`/`decode_*` (Task 4), `Snapshot` and friends + `VIN_RE` (Task 3), `ReplayPort`/`load_transcript` (Task 5).
- Produces: `scan(transport: Transport, *, snapshot_id: str, captured_at: datetime | None = None, kind: str = "replay", protocol: str | None = None, transcript: str | None = None) -> Snapshot`; `python -m obd_reader replay <transcript.jsonl> [--protocol 6]` prints the snapshot JSON.

Scan order (all commands are allowlisted): `ATZ, ATE0, ATL0, ATH0`, optional `ATSP<protocol>`, `ATI`, `STI`, `ATDP`, `0100` (+ `0120`… while the last-PID bit says another page exists), `0900`, `0902` (only if `0900` reports PID 02), `03`, `07`, `0A`, `0101`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scanner.py`:

```python
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from obd_reader.allowlist import check_command
from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.snapshot import Snapshot
from obd_reader.transport import Transport

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_sedan.jsonl"
NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def run_scan(records, protocol="6"):
    port = ReplayPort(records)
    snap = scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol=protocol)
    return snap, port


def test_scan_synthetic_sedan():
    snap, port = run_scan(load_transcript(FIXTURE))
    assert snap.vehicle.vin == "1HGCM82633A004352" and snap.vehicle.vin_source == "obd"
    assert snap.protocol.name == "ISO 15765-4 (CAN 11/500)" and snap.protocol.pinned
    assert [d.code for d in snap.dtcs.stored] == ["P0171"]
    assert snap.dtcs.pending == [] and snap.dtcs.permanent == []
    assert snap.mil.on is True and snap.mil.dtc_count == 1
    assert {"0C", "20", "21"} <= set(snap.supported_pids["01"])
    assert "02" in snap.supported_pids["09"]
    assert snap.source.adapter.ati == "ELM327 v1.5"
    assert snap.source.adapter.genuine_stn is False
    assert snap.warnings == []


def test_every_byte_written_is_allowlisted_and_nothing_was_unmatched():
    _, port = run_scan(load_transcript(FIXTURE))
    assert port.unmatched == []
    assert port.written, "scan wrote nothing"
    for cmd in port.written:
        assert check_command(cmd) == cmd
    assert "0140" not in port.written  # page 0x20 did not advertise 0x40


def test_snapshot_round_trips_through_json():
    snap, _ = run_scan(load_transcript(FIXTURE))
    assert Snapshot.model_validate_json(snap.model_dump_json()) == snap


def _patch(records, tx, rx):
    return [dict(r, rx=rx) if r["tx"] == tx else r for r in records]


def test_mode_09_no_data_gives_no_vin_and_skips_0902():  # Review Focus 3
    records = _patch(load_transcript(FIXTURE), "0900", ["NO DATA"])
    snap, port = run_scan(records)
    assert snap.vehicle.vin is None and snap.vehicle.vin_source == "none"
    assert any("VIN unsupported" in w for w in snap.warnings)
    assert "0902" not in port.written


def test_mode_09_negative_response_is_handled():  # Review Focus 3
    records = _patch(load_transcript(FIXTURE), "0900", ["7F 09 12"])
    snap, _ = run_scan(records)
    assert snap.vehicle.vin is None
    assert any("VIN unsupported" in w for w in snap.warnings)


def test_invalid_vin_from_adapter_is_dropped_with_warning():  # Review Focus 5
    bad = ["014", "0: 49 02 01 4F 48 47", "1: 43 4D 38 32 36 33 33", "2: 41 30 30 34 33 35 32"]  # 'O'
    snap, _ = run_scan(_patch(load_transcript(FIXTURE), "0902", bad))
    assert snap.vehicle.vin is None
    assert any("invalid VIN" in w for w in snap.warnings)


def test_no_dtc_data_replies_mean_empty_lists_not_a_crash():
    records = _patch(_patch(load_transcript(FIXTURE), "03", ["NO DATA"]), "0A", ["NO DATA"])
    snap, _ = run_scan(records)
    assert snap.dtcs.stored == [] and snap.dtcs.permanent == []


def test_cli_replay_prints_a_valid_snapshot():
    out = subprocess.run(
        [sys.executable, "-m", "obd_reader", "replay", str(FIXTURE), "--protocol", "6"],
        capture_output=True, text=True, check=True,
    ).stdout
    snap = Snapshot.model_validate(json.loads(out))
    assert snap.vehicle.vin == "1HGCM82633A004352"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scanner.py -q`
Expected: `ModuleNotFoundError: No module named 'obd_reader.scanner'`.

- [ ] **Step 3: Write the scanner**

Create `src/obd_reader/scanner.py`:

```python
"""Minimal read-only scan: VIN, protocol, supported PIDs, DTCs, MIL."""
from datetime import datetime, timezone

from obd_reader import __version__
from obd_reader.elm import decode_dtc_list, decode_supported, parse_response
from obd_reader.snapshot import (
    VIN_RE, Adapter, Dtc, Dtcs, Mil, Protocol, Snapshot, Source, Vehicle,
)
from obd_reader.transport import Transport

INIT = ("ATZ", "ATE0", "ATL0", "ATH0")


def _first(lines: list[str]) -> str | None:
    return lines[0] if lines else None


def _dtcs(transport: Transport, cmd: str, sid: int) -> list[Dtc]:
    payload = parse_response(transport.send(cmd), sid)
    return [Dtc(code=c) for c in decode_dtc_list(payload)] if payload else []


def scan(
    transport: Transport,
    *,
    snapshot_id: str,
    captured_at: datetime | None = None,
    kind: str = "replay",
    protocol: str | None = None,
    transcript: str | None = None,
) -> Snapshot:
    warnings: list[str] = []
    for cmd in INIT:
        transport.send(cmd)
    if protocol is not None:
        transport.send(f"ATSP{protocol}")
    ati = _first(transport.send("ATI"))
    sti = _first(transport.send("STI"))
    genuine_stn = bool(sti and sti.upper().startswith("STN"))
    adapter = Adapter(
        ati=ati,
        sti=sti if genuine_stn else None,
        chip=sti.split()[0] if genuine_stn else None,
        genuine_stn=genuine_stn,
    )
    dp = _first(transport.send("ATDP"))
    proto = Protocol(
        name=dp.removeprefix("AUTO, ") if dp else None,
        atsp=protocol,
        pinned=protocol is not None,
    )

    supported: dict[str, list[str]] = {}
    pids01: list[str] = []
    base = 0x00
    while base <= 0xE0:
        p = parse_response(transport.send(f"01{base:02X}"), 0x41)
        if p is None or len(p) < 6 or p[1] != base:
            break
        pids = decode_supported(base, p[2:6])
        pids01 += pids
        if f"{base + 0x20:02X}" not in pids:
            break
        base += 0x20
    if pids01:
        supported["01"] = pids01

    vin, vin_source = None, "none"
    p9 = parse_response(transport.send("0900"), 0x49)
    if p9 is not None and len(p9) >= 6:
        pids09 = decode_supported(0x00, p9[2:6])
        supported["09"] = pids09
    else:
        pids09 = []
    if "02" in pids09:
        pv = parse_response(transport.send("0902"), 0x49)
        candidate = pv[3:20].decode("ascii", errors="replace") if pv else ""
        if VIN_RE.fullmatch(candidate):
            vin, vin_source = candidate, "obd"
        else:
            warnings.append(f"Mode 09 returned an invalid VIN: {candidate!r}")
    else:
        warnings.append("VIN unsupported via Mode 09")

    dtcs = Dtcs(
        stored=_dtcs(transport, "03", 0x43),
        pending=_dtcs(transport, "07", 0x47),
        permanent=_dtcs(transport, "0A", 0x4A),
    )

    mil = Mil()
    p1 = parse_response(transport.send("0101"), 0x41)
    if p1 is not None and len(p1) >= 3 and p1[1] == 0x01:
        mil = Mil(on=bool(p1[2] & 0x80), dtc_count=p1[2] & 0x7F)

    return Snapshot(
        snapshot_id=snapshot_id,
        captured_at=captured_at or datetime.now(timezone.utc),
        source=Source(kind=kind, adapter=adapter, tool_version=__version__, transcript=transcript),
        vehicle=Vehicle(vin=vin, vin_source=vin_source),
        protocol=proto,
        supported_pids=supported,
        dtcs=dtcs,
        mil=mil,
        warnings=warnings,
    )
```

`kind` is passed to `Source(kind=...)`, whose type is `Literal["live","replay","import"]`; pydantic validates it at runtime.

- [ ] **Step 4: Write the CLI**

Create `src/obd_reader/__main__.py`:

```python
import argparse
import sys
from pathlib import Path

from obd_reader.replay import ReplayPort
from obd_reader.scanner import scan
from obd_reader.transport import Transport


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="obd-reader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay", help="build a snapshot from a recorded transcript (no adapter)")
    rp.add_argument("transcript", type=Path)
    rp.add_argument("--protocol", default=None, help="ATSP value to pin, e.g. 6")
    args = ap.parse_args(argv)

    port = ReplayPort.from_file(args.transcript)
    snap = scan(
        Transport(port),
        snapshot_id=args.transcript.stem,
        protocol=args.protocol,
        transcript=str(args.transcript),
    )
    print(snap.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: every test in every file passes. If a scanner test fails, fix `scanner.py` (do not edit the fixture to fit).

- [ ] **Step 6: Run the demo**

Run: `.venv/bin/python -m obd_reader replay tests/fixtures/synthetic_sedan.jsonl --protocol 6`
Expected: JSON snapshot with `"vin": "1HGCM82633A004352"`, `"stored": [{"code": "P0171", ...}]`, `"mil": {"on": true, "dtc_count": 1}`.

- [ ] **Step 7: Stage (commit only if Neil approved per-task commits)**

```bash
git add src/obd_reader/scanner.py src/obd_reader/__main__.py tests/test_scanner.py
git commit -m "feat: minimal scanner and replay CLI demo"
```

---

## Phase 1 exit check (demo)

- [ ] `.venv/bin/pytest -q` is green (allowlist exhaustive + fuzz, spy-port fuzz, import boundary, parser, replay, scanner).
- [ ] `.venv/bin/python -m obd_reader replay tests/fixtures/synthetic_sedan.jsonl --protocol 6` prints the snapshot.
- [ ] Manually confirm the demo of "forbidden bytes rejected": `.venv/bin/python -c "from obd_reader.allowlist import check_command; check_command('04')"` raises `ForbiddenCommand`.

## Self-Review (done)

- **Spec coverage:** §5.3 gate (Task 1–2), typed-request idea deferred (no tool layer until Phase 3; noted), import-boundary test (Task 2), fuzz + spy port + mutation check (Tasks 1–2), §6 snapshot subset (Task 3), §10 Phase 1 demo (Task 6). Not covered by design: tool-name-set test and rate caps (need the tool layer, Phase 3).
- **Placeholders:** none.
- **Type consistency:** `check_command`, `Transport.send`, `parse_response`, `decode_supported`, `decode_dtc_list`, `ReplayPort`, `scan`, `VIN_RE` are named identically everywhere.
- **Known limits carried to later phases:** Mode 03 non-CAN layout (no count byte), multi-ECU responses, ELM echo when `ATE0` fails, read timeouts are indistinguishable from empty replies, `ATSH`/`ATCRA` range limits (design §13 item 3).
