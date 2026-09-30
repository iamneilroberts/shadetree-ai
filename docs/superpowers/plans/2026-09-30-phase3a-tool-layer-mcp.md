# Phase 3a — Read-only Tool Layer + MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the vehicle-side read-only tools (offline snapshot tools plus live tools) behind an MCP server for Claude Code / Claude Desktop, after widening the allowlist to Modes 05 and 06.

**Architecture:** Snapshot-first. Offline tools read saved snapshots (no adapter needed); only live tools (`adapter_info`, `scan`, `read_pid`, `live_data`, `trim_summary`, `mode06_tests`) open the serial port, each through a `Session` that holds a lock, records a transcript, and goes through the gated `Transport`. A tool registry is built once and registered on an `MCPServer` with `read_only_hint=True`. The reference store, NHTSA lookups and `check_citations` are Phase 3b (separate plan).

**Tech Stack:** Python 3.11+, pydantic v2, pyserial, `mcp>=2.2,<3` (`from mcp.server.mcpserver import MCPServer`), pytest, hypothesis.

**Spec:** `docs/design.md` (§5 allowlist, §6 snapshot, §7 tools). Approved by Neil 2026-09-30: widen the allowlist for Modes 05 and 06 now; UDS `0x19` later (own plan); UDS `0x22` not before OBDb work.

## Global Constraints

- Allowed OBD modes after Task 1, verbatim: **01, 02, 03, 05, 06, 07, 09, 0A**. Mode 04, 08, 0B+, UDS (`0x10`, `0x11`, `0x14`, `0x19`, `0x22`, `0x27`, `0x28`, `0x2E`, `0x2F`, `0x31`, `0x3E`, `0x85`) and every AT/ST write command stay refused.
- Only `src/obd_reader/transport.py` may import `serial` or use `__import__` / `importlib.import_module`.
- No tool parameter accepts a command string. Tools take validated PIDs (2 hex digits present in the PID table), MIDs (2 hex digits), snapshot ids, and numbers. A test asserts the tool-name set and that no parameter is named `cmd`, `command`, `raw`, `hex`, `at`, `payload` or `data`.
- Every registered MCP tool carries `ToolAnnotations(read_only_hint=True, destructive_hint=False)`.
- MCP SDK names, verified against `mcp` 2.2.0: `MCPServer(name, instructions=...)`, `@server.tool(annotations=ToolAnnotations(read_only_hint=True))`, `await server.list_tools()`, `await server.call_tool(name, args)` → `.content[0].text`, `.is_error`; `server.run()` defaults to stdio.
- Snapshot `schema_version` stays `"0.1"`; new fields are optional (`freeze_frame`, `readiness`, `ignition_type`, `live_sample`, `user_context`). Unknown fields stay forbidden.
- Live-data limits: ≤8 PIDs, ≤120 s, ≤10 Hz, ≤120 points per series in a tool response.
- Real snapshots and transcripts (they contain VINs) are gitignored and never committed; only synthetic or VIN-redacted fixtures go in `tests/fixtures/`.
- Env config: `SHADETREE_PORT` (required for live tools), `SHADETREE_BAUD` (default 115200), `SHADETREE_TIMEOUT` (default 10), `SHADETREE_HOME` (default `.`; holds `snapshots/` and `transcripts/`).
- **Repo rule:** work in a worktree; commit per task on the branch (Neil approved commit-as-you-go); merge to `main` only when the whole suite is green; do NOT push without Neil asking.
- Never touch attached hardware without asking Neil first (Task 11 is the only hardware step).

## Review Focus

Failure modes the spec implies but happy-path tests would miss; each has a test in the owning task:

1. A PID or MID argument carrying a smuggled command (`"0C\r04"`, `"04"`, `"ZZ"`, lowercase, 3 digits) must be rejected before anything is sent. → Task 5 (sampler) and Task 9 (tools).
2. `import_snapshot` and `get_snapshot` given a path/id that escapes the data directory (`../../etc/passwd`, absolute paths, symlink-like ids) must be refused, and error messages must not echo file contents. → Task 6 and Task 8.
3. Two live tool calls at once must not interleave bytes on the port: the second must fail fast with a clear "adapter busy" error. → Task 6.
4. Adapter attached but car off (silent or `UNABLE TO CONNECT`): live tools return a structured result or clear error within the configured timeout, never a stack trace or a hang. → Task 9.
5. Response size: a 120 s × 10 Hz × 8 PID sample must be downsampled to ≤120 points per series in the tool response while keeping exact min/max/mean. → Task 5 and Task 9.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/obd_reader/allowlist.py` (modify) | Add Modes 05 and 06 |
| `src/obd_reader/pids.py` (new) | Own Mode 01 PID table + `decode_pid` |
| `src/obd_reader/readiness.py` (new) | Parse Mode 01 PID 01 monitor status |
| `src/obd_reader/snapshot.py` (modify) | Optional freeze-frame / readiness / live-sample / user-context models |
| `src/obd_reader/adapter.py` (new) | `init_adapter`, `identify` (shared by scanner and live tools) |
| `src/obd_reader/scanner.py` (modify) | `_walk_pages`, readiness, freeze frame, `symptoms` |
| `src/obd_reader/capture.py` (modify) | Pass `symptoms` through |
| `src/obd_reader/live.py` (new) | Sampler, limits, stats, downsampling |
| `src/obd_reader/store.py` (new) | Path-safe snapshot store |
| `src/obd_reader/session.py` (new) | Config, lock, transcript-recording connection |
| `src/obd_reader/mode06.py` (new) | Mode 06 MID bitmap and result-group parsing |
| `src/obd_reader/tools.py` (new) | Tool functions + `TOOL_NAMES` |
| `src/obd_reader/mcp_server.py` (new) | `build_server`, `main` |
| `tests/test_*.py` (new/modify) | One test file per module above |

---

### Task 1: Widen the allowlist to Modes 05 and 06

**Files:**
- Modify: `src/obd_reader/allowlist.py`, `tests/test_allowlist.py`, `docs/design.md`, `README.md`, `CLAUDE.md`

**Interfaces:**
- Produces: `ALLOWED_MODES` includes `0x05`, `0x06`; `check_command` accepts `05` + 2 hex bytes (TID, O2 sensor) and `06` + 1 hex byte (MID).

- [ ] **Step 1: Update the tests first**

In `tests/test_allowlist.py`:
1. Replace `ARG_BYTES` with `{0x01: 1, 0x02: 2, 0x03: 0, 0x05: 2, 0x06: 1, 0x07: 0, 0x09: 1, 0x0A: 0}`.
2. In `ALLOWED` add `"0600"`, `"0601"`, `"06 20"`, `"050101"`, `"05 02 01"`.
3. In `FORBIDDEN` remove `"05"`, `"0500"`, `"06"`, `"0600"` from the "services outside the allowlist" group and add, in the "wrong argument length" group: `"05"`, `"0500"`, `"05000000"`, `"06"`, `"060000"`.
4. Keep `"04"`, `"0400"`, `"08"`, `"0800"`, `"0B"`, `"0C"`, `"0E"`, `"10"`, `"1901"`, `"22F190"`, `"2F"`, `"3101"` forbidden.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_allowlist.py -q --tb=line 2>&1 | grep -E "DID NOT RAISE|^E |passed|failed" | head`
Expected: failures for `0600`, `0601`, `050101` etc. (currently forbidden) and `test_every_hex_frame_is_classified_correctly`.

- [ ] **Step 3: Implement**

In `src/obd_reader/allowlist.py` change `ALLOWED_MODES` to `frozenset({0x01, 0x02, 0x03, 0x05, 0x06, 0x07, 0x09, 0x0A})` and add these two patterns to `_PATTERNS` next to the other OBD service patterns:

```python
        rf"05{_H}{{4}}",      # Mode 05 O2 sensor test results: TID + sensor (non-CAN)
        rf"06{_H}{{2}}",      # Mode 06 on-board test results: monitor id (MID)
```

Update the module docstring's "Not enabled yet" line to: `Not enabled yet (see docs/design.md §13): UDS 0x19 / 0x22, STIX-style STN commands (unverified on hardware), ATPPS, ATCAF0.`

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -3`
Expected: whole suite passes (the mutation-check test still proves a gate that admits Mode 04 is caught).

- [ ] **Step 5: Update the docs**

- `docs/design.md` §5.1: allowed services become `01, 02, 03, 05, 06, 07, 09, 0A` (Mode 06 `06 MID`, Mode 05 `05 TID SENSOR`); §5.2: remove 05/06 from the refused list and the "05/06 are read-only" footnote; §13 item 1 (Mode 06): "Decided 2026-09-30: enabled." Add under §5.2: "UDS 0x19 is planned in its own phase, after a real-car test; UDS 0x22 waits for the OBDb work."
- `README.md` and `CLAUDE.md`: change "Modes 01, 02, 03, 07, 09, 0A" to "Modes 01, 02, 03, 05, 06, 07, 09, 0A" wherever it appears; add the decision date to `CLAUDE.md`.

- [ ] **Step 6: Commit**

```bash
git add src/obd_reader/allowlist.py tests/test_allowlist.py docs/design.md README.md CLAUDE.md
git commit -m "feat: allow read-only Modes 05 and 06 (approved 2026-09-30)"
```

---

### Task 2: PID table and decoder

**Files:**
- Create: `src/obd_reader/pids.py`
- Modify: `src/obd_reader/snapshot.py` (add `PidValue`)
- Test: `tests/test_pids.py`

**Interfaces:**
- Produces: `snapshot.PidValue(name: str, value: float | int | str, unit: str | None, raw: str)`; `pids.PIDS: dict[str, PidDef]`; `pids.decode_pid(pid: str, data: bytes) -> PidValue | None` (None for unknown PID or too little data); `pids.pid_name(pid: str) -> str` (`"unknown"` if absent). Table provenance: own hand-written table from public facts (Wikipedia "OBD-II PIDs", formulas are functional facts), confidence `curated` pending review against SAE J1979.

- [ ] **Step 1: Add the model**

Append to `src/obd_reader/snapshot.py` (before `Snapshot`):

```python
class PidValue(_Model):
    name: str
    value: float | int | str
    unit: str | None = None
    raw: str
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_pids.py`:

```python
import pytest

from obd_reader.pids import PIDS, decode_pid, pid_name


@pytest.mark.parametrize(
    "pid,data,value,unit",
    [
        ("05", "7B", 83, "C"),
        ("05", "00", -40, "C"),
        ("06", "80", 0.0, "%"),
        ("06", "00", -100.0, "%"),
        ("07", "FF", 99.2, "%"),
        ("08", "8C", 9.4, "%"),
        ("09", "74", -9.4, "%"),
        ("04", "80", 50.2, "%"),
        ("0A", "64", 300, "kPa"),
        ("0B", "63", 99, "kPa"),
        ("0C", "1AF8", 1726.0, "rpm"),
        ("0D", "3C", 60, "km/h"),
        ("0E", "80", 0.0, "deg"),
        ("0F", "3C", 20, "C"),
        ("10", "0393", 9.15, "g/s"),
        ("11", "FF", 100.0, "%"),
        ("14", "5AFF", 0.45, "V"),
        ("1F", "0064", 100, "s"),
        ("42", "3630", 13.872, "V"),
        ("43", "00FF", 100.0, "%"),
        ("44", "8000", 1.0, "ratio"),
        ("46", "28", 0, "C"),
        ("5C", "5A", 50, "C"),
        ("5E", "0064", 5.0, "L/h"),
    ],
)
def test_decode(pid, data, value, unit):
    v = decode_pid(pid, bytes.fromhex(data))
    assert v is not None and v.unit == unit and v.raw == data
    assert v.value == pytest.approx(value, abs=0.01)


def test_unknown_pid_and_short_data_return_none():
    assert decode_pid("FF", b"\x00") is None
    assert decode_pid("0C", b"\x1a") is None  # RPM needs 2 bytes


def test_names_are_unique_and_lowercase_snake():
    names = [d.name for d in PIDS.values()]
    assert len(names) == len(set(names))
    assert all(n == n.lower() and " " not in n for n in names)
    assert pid_name("0C") == "engine_rpm" and pid_name("EE") == "unknown"


def test_every_pid_key_is_two_upper_hex_digits_and_matches_its_def():
    for key, d in PIDS.items():
        assert len(key) == 2 and key == key.upper() and d.pid == key
        int(key, 16)
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_pids.py -q --tb=line 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.pids'`.

- [ ] **Step 4: Implement**

Create `src/obd_reader/pids.py`:

```python
"""Mode 01 PID table: hand-written from public formulas (Wikipedia "OBD-II PIDs"),
confidence `curated`, to be checked against SAE J1979 before being called
authoritative. Only the common, well-documented PIDs are listed."""
from dataclasses import dataclass
from typing import Callable

from obd_reader.snapshot import PidValue


@dataclass(frozen=True)
class PidDef:
    pid: str
    name: str
    unit: str | None
    nbytes: int
    decode: Callable[[bytes], float | int]


def _u16(d: bytes) -> int:
    return d[0] * 256 + d[1]


def _pct255(d: bytes) -> float:
    return round(d[0] * 100 / 255, 1)


def _trim(d: bytes) -> float:
    return round((d[0] - 128) * 100 / 128, 1)


def _temp(d: bytes) -> int:
    return d[0] - 40


_DEFS = [
    PidDef("04", "calculated_engine_load", "%", 1, _pct255),
    PidDef("05", "coolant_temp", "C", 1, _temp),
    PidDef("06", "stft_b1", "%", 1, _trim),
    PidDef("07", "ltft_b1", "%", 1, _trim),
    PidDef("08", "stft_b2", "%", 1, _trim),
    PidDef("09", "ltft_b2", "%", 1, _trim),
    PidDef("0A", "fuel_pressure", "kPa", 1, lambda d: d[0] * 3),
    PidDef("0B", "intake_manifold_pressure", "kPa", 1, lambda d: d[0]),
    PidDef("0C", "engine_rpm", "rpm", 2, lambda d: _u16(d) / 4),
    PidDef("0D", "vehicle_speed", "km/h", 1, lambda d: d[0]),
    PidDef("0E", "timing_advance", "deg", 1, lambda d: d[0] / 2 - 64),
    PidDef("0F", "intake_air_temp", "C", 1, _temp),
    PidDef("10", "maf", "g/s", 2, lambda d: _u16(d) / 100),
    PidDef("11", "throttle_position", "%", 1, _pct255),
    *[
        PidDef(f"{0x14 + i:02X}", f"o2_b{i // 4 + 1}s{i % 4 + 1}_voltage", "V", 2, lambda d: d[0] / 200)
        for i in range(8)
    ],
    PidDef("1F", "run_time", "s", 2, _u16),
    PidDef("21", "distance_with_mil", "km", 2, _u16),
    PidDef("2C", "commanded_egr", "%", 1, _pct255),
    PidDef("2E", "commanded_evap_purge", "%", 1, _pct255),
    PidDef("2F", "fuel_level", "%", 1, _pct255),
    PidDef("30", "warmups_since_clear", "count", 1, lambda d: d[0]),
    PidDef("31", "distance_since_clear", "km", 2, _u16),
    PidDef("33", "barometric_pressure", "kPa", 1, lambda d: d[0]),
    PidDef("42", "control_module_voltage", "V", 2, lambda d: _u16(d) / 1000),
    PidDef("43", "absolute_load", "%", 2, lambda d: round(_u16(d) * 100 / 255, 1)),
    PidDef("44", "commanded_equivalence_ratio", "ratio", 2, lambda d: round(_u16(d) * 2 / 65536, 3)),
    PidDef("45", "relative_throttle", "%", 1, _pct255),
    PidDef("46", "ambient_air_temp", "C", 1, _temp),
    PidDef("5C", "oil_temp", "C", 1, _temp),
    PidDef("5E", "fuel_rate", "L/h", 2, lambda d: _u16(d) / 20),
]

PIDS: dict[str, PidDef] = {d.pid: d for d in _DEFS}


def decode_pid(pid: str, data: bytes) -> PidValue | None:
    d = PIDS.get(pid)
    if d is None or len(data) < d.nbytes:
        return None
    raw = data[: d.nbytes]
    return PidValue(name=d.name, value=d.decode(raw), unit=d.unit, raw=raw.hex().upper())


def pid_name(pid: str) -> str:
    d = PIDS.get(pid)
    return d.name if d else "unknown"
```

O2 sensor PIDs `14`–`1B` are named `o2_b1s1_voltage`..`o2_b2s4_voltage` (bank = `i // 4 + 1`, sensor = `i % 4 + 1`).

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -3`
Expected: all pass. If a `test_decode` row fails, recompute the expected value from the formula in the spec's source (Wikipedia OBD-II PIDs) before changing anything; do not loosen tolerance.

- [ ] **Step 6: Commit**

```bash
git add src/obd_reader/pids.py src/obd_reader/snapshot.py tests/test_pids.py
git commit -m "feat: Mode 01 PID table with decoders"
```

---

### Task 3: Readiness monitor parser

**Files:**
- Create: `src/obd_reader/readiness.py`
- Modify: `src/obd_reader/snapshot.py` (add `Monitor`)
- Test: `tests/test_readiness.py`

**Interfaces:**
- Consumes: payloads from `elm.parse_all(lines, 0x41)` for request `0101` (`41 01 A B C D`).
- Produces: `snapshot.Monitor(supported: bool, complete: bool | None)`; `readiness.parse_readiness(payloads: list[bytes]) -> tuple[str | None, dict[str, Monitor]]` returning `(ignition_type, monitors)` where ignition_type is `"spark"` or `"compression"` (None if no valid payload) and every monitor name is present (unsupported ones have `supported=False, complete=None`).

- [ ] **Step 1: Add the model**

Append to `src/obd_reader/snapshot.py` before `Snapshot`:

```python
class Monitor(_Model):
    supported: bool
    complete: bool | None = None
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_readiness.py`:

```python
from obd_reader.readiness import parse_readiness

REAL_ECU1 = bytes.fromhex("410100 07E500".replace(" ", ""))   # real Ridgeline: B=07 C=E5 D=00
REAL_ECU2 = bytes.fromhex("410100 040000".replace(" ", ""))   # real Ridgeline: B=04 C=00 D=00


def test_real_ridgeline_two_ecu_status_is_all_complete():
    ignition, m = parse_readiness([REAL_ECU1, REAL_ECU2])
    assert ignition == "spark"
    for name in ("misfire", "fuel_system", "components", "catalyst", "evap", "o2_sensor", "o2_sensor_heater", "egr"):
        assert m[name].supported is True and m[name].complete is True, name
    for name in ("heated_catalyst", "secondary_air", "ac_refrigerant"):
        assert m[name].supported is False and m[name].complete is None, name


def test_incomplete_flags_are_reported():
    # B=0x37: misfire+fuel_system incomplete (bits 4,5), components complete
    # D=0x25: catalyst(bit0), evap(bit2), o2_sensor(bit5) incomplete
    ignition, m = parse_readiness([bytes.fromhex("410100 37E525".replace(" ", ""))])
    assert m["misfire"].complete is False and m["fuel_system"].complete is False
    assert m["components"].complete is True
    assert m["catalyst"].complete is False and m["evap"].complete is False and m["o2_sensor"].complete is False
    assert m["o2_sensor_heater"].complete is True and m["egr"].complete is True


def test_a_monitor_is_complete_only_if_every_supporting_ecu_says_so():
    a = bytes.fromhex("410100 070100".replace(" ", ""))   # catalyst supported, complete
    b = bytes.fromhex("410100 070101".replace(" ", ""))   # catalyst supported, incomplete
    _, m = parse_readiness([a, b])
    assert m["catalyst"].complete is False


def test_compression_ignition_is_detected():
    ignition, m = parse_readiness([bytes.fromhex("410100 0F0000".replace(" ", ""))])
    assert ignition == "compression"
    assert m["misfire"].supported and "catalyst" not in m


def test_garbage_and_short_payloads_yield_nothing():
    assert parse_readiness([]) == (None, {})
    assert parse_readiness([b"\x41\x01\x00"]) == (None, {})
    assert parse_readiness([bytes.fromhex("410200000000")]) == (None, {})
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_readiness.py -q --tb=line 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.readiness'`.

- [ ] **Step 4: Implement**

Create `src/obd_reader/readiness.py`:

```python
"""Mode 01 PID 01 (monitor status since DTCs cleared): 41 01 A B C D.

B bits 0-2 = misfire / fuel system / components supported, bits 4-6 = the same
three not complete, bit 3 = ignition type (0 spark, 1 compression).
C = which of 8 further monitors are supported, D = which of them are NOT complete
(same bit order). Bit names below are for spark ignition; compression engines use
a different list, reported here by bit number until verified.
"""
from obd_reader.snapshot import Monitor

SPARK = ["catalyst", "heated_catalyst", "evap", "secondary_air", "ac_refrigerant",
         "o2_sensor", "o2_sensor_heater", "egr"]
COMPRESSION = [f"compression_monitor_bit{i}" for i in range(8)]


def parse_readiness(payloads: list[bytes]) -> tuple[str | None, dict[str, Monitor]]:
    valid = [p for p in payloads if len(p) >= 6 and p[1] == 0x01]
    if not valid:
        return None, {}
    compression = bool(valid[0][3] & 0x08)
    names = COMPRESSION if compression else SPARK
    all_names = ["misfire", "fuel_system", "components", *names]
    monitors = {n: Monitor(supported=False) for n in all_names}
    for p in valid:
        b, c, d = p[3], p[4], p[5]
        entries = [("misfire", b & 0x01, b & 0x10), ("fuel_system", b & 0x02, b & 0x20),
                   ("components", b & 0x04, b & 0x40)]
        entries += [(names[i], (c >> i) & 1, (d >> i) & 1) for i in range(8)]
        for name, supported, incomplete in entries:
            if not supported:
                continue
            prev = monitors[name]
            complete = not incomplete
            monitors[name] = Monitor(
                supported=True,
                complete=complete if prev.complete is None else (prev.complete and complete),
            )
    return ("compression" if compression else "spark"), monitors
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/obd_reader/readiness.py src/obd_reader/snapshot.py tests/test_readiness.py
git commit -m "feat: readiness monitor parser (verified against real Ridgeline bytes)"
```

---

### Task 4: Snapshot additions, shared adapter helpers, richer scanner

**Files:**
- Modify: `src/obd_reader/snapshot.py`, `src/obd_reader/scanner.py`, `src/obd_reader/capture.py`, `tests/fixtures/synthetic_sedan.jsonl`, `tests/test_replay.py`, `tests/test_scanner.py`
- Create: `src/obd_reader/adapter.py`
- Test: `tests/test_adapter.py`, `tests/test_scanner_extras.py`

**Interfaces:**
- Consumes: `parse_all`, `decode_supported`, `decode_dtc` (elm), `decode_pid`, `PIDS` (pids), `parse_readiness` (readiness).
- Produces:
  - `snapshot.FreezeFrame(dtc: str | None, pids: dict[str, PidValue])`, `snapshot.Series(name: str, unit: str | None, samples: list[tuple[float, float]])`, `snapshot.LiveSample(conditions: dict[str, str], duration_s: float, rate_hz: float, series: dict[str, Series])`, `snapshot.UserContext(symptoms: str, recent_work: str)`; `Snapshot` gains optional `freeze_frame`, `readiness: dict[str, Monitor]`, `ignition_type: Literal["spark","compression"] | None`, `live_sample`, `user_context`.
  - `adapter.INIT = ("ATZ","ATE0","ATL0","ATH0")`, `adapter.init_adapter(transport, protocol: str | None) -> None`, `adapter.identify(transport) -> Adapter`.
  - `scanner.scan(..., symptoms: str = "")`; `capture(..., symptoms: str = "")`.

- [ ] **Step 1: Failing test for the adapter helpers**

Create `tests/test_adapter.py`:

```python
from obd_reader.adapter import INIT, identify, init_adapter
from obd_reader.replay import ReplayPort
from obd_reader.transport import Transport


def records(pairs):
    return [{"tx": tx, "rx": rx} for tx, rx in pairs]


def test_init_sends_reset_echo_linefeed_headers_and_the_protocol():
    port = ReplayPort(records([("ATZ", ["ELM327 v1.4b"]), ("ATE0", ["OK"]), ("ATL0", ["OK"]),
                               ("ATH0", ["OK"]), ("ATSP0", ["OK"])]))
    init_adapter(Transport(port), "0")
    assert port.written == [*INIT, "ATSP0"]
    assert port.unmatched == []


def test_init_without_protocol_does_not_send_atsp():
    port = ReplayPort(records([(c, ["OK"]) for c in INIT]))
    init_adapter(Transport(port), None)
    assert port.written == list(INIT)


def test_identify_reports_genuine_stn():
    port = ReplayPort(records([("ATI", ["ELM327 v1.4b"]), ("STI", ["STN2232 v5.12.4"])]))
    a = identify(Transport(port))
    assert (a.ati, a.sti, a.chip, a.genuine_stn) == ("ELM327 v1.4b", "STN2232 v5.12.4", "STN2232", True)


def test_identify_reports_a_plain_elm_when_sti_is_unknown():
    port = ReplayPort(records([("ATI", ["ELM327 v1.5"]), ("STI", ["?"])]))
    a = identify(Transport(port))
    assert a.genuine_stn is False and a.chip is None and a.sti is None
```

- [ ] **Step 2: Failing tests for the richer scan**

Create `tests/test_scanner_extras.py` (uses the synthetic sedan fixture that Step 5 extends):

```python
from datetime import datetime, timezone
from pathlib import Path

from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
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
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_adapter.py tests/test_scanner_extras.py -q --tb=line 2>&1 | grep -E "ModuleNotFound|Error|passed|failed" | head -4`
Expected: `ModuleNotFoundError: No module named 'obd_reader.adapter'` and unexpected-keyword `symptoms`.

- [ ] **Step 4: Implement the snapshot models**

Append to `src/obd_reader/snapshot.py` before `Snapshot` (after `Monitor`):

```python
class FreezeFrame(_Model):
    dtc: str | None = None
    pids: dict[str, PidValue] = Field(default_factory=dict)


class Series(_Model):
    name: str
    unit: str | None = None
    samples: list[tuple[float, float]] = Field(default_factory=list)


class LiveSample(_Model):
    conditions: dict[str, str] = Field(default_factory=dict)
    duration_s: float
    rate_hz: float
    series: dict[str, Series] = Field(default_factory=dict)


class UserContext(_Model):
    symptoms: str = ""
    recent_work: str = ""
```

Add these fields to `Snapshot` (after `mil`, before `warnings`):

```python
    freeze_frame: FreezeFrame | None = None
    readiness: dict[str, Monitor] = Field(default_factory=dict)
    ignition_type: Literal["spark", "compression"] | None = None
    live_sample: LiveSample | None = None
    user_context: UserContext = Field(default_factory=UserContext)
```

- [ ] **Step 5: Implement the adapter module and extend the scanner**

Create `src/obd_reader/adapter.py`:

```python
"""Adapter bring-up and identification, shared by the scanner and the live tools."""
from obd_reader.snapshot import Adapter
from obd_reader.transport import Transport

INIT = ("ATZ", "ATE0", "ATL0", "ATH0")


def init_adapter(transport: Transport, protocol: str | None) -> None:
    for cmd in INIT:
        transport.send(cmd)
    if protocol is not None:
        transport.send(f"ATSP{protocol}")


def identify(transport: Transport) -> Adapter:
    ati = (transport.send("ATI") or [None])[0]
    sti = (transport.send("STI") or [None])[0]
    genuine = bool(sti and sti.upper().startswith("STN"))
    return Adapter(
        ati=ati,
        sti=sti if genuine else None,
        chip=sti.split()[0] if genuine else None,
        genuine_stn=genuine,
    )
```

In `src/obd_reader/scanner.py`:
1. Replace the local `INIT` tuple, the init loop and the ATI/STI block by `init_adapter(transport, protocol)` and `adapter = identify(transport)` (import from `obd_reader.adapter`); delete `_first` only if it becomes unused (it is still used for `ATDP`).
2. Replace the Mode 01 page loop with this helper and call `pids01 = _walk_pages(transport, 0x01)` (keep `supported["01"] = sorted(pids01)` and the "no response" warning when empty):

```python
def _walk_pages(transport: Transport, mode: int) -> set[str]:
    """Supported-PID bitmaps for Mode 01 (`01xx`) or Mode 02 (`02xx00`), page by page."""
    sid, off = 0x40 + mode, (2 if mode == 0x01 else 3)
    found: set[str] = set()
    base = 0x00
    while base <= 0xE0:
        cmd = f"{mode:02X}{base:02X}" + ("00" if mode == 0x02 else "")
        pids: set[str] = set()
        for p in parse_all(transport.send(cmd), sid):
            if len(p) >= off + 4 and p[1] == base:
                pids.update(decode_supported(base, p[off : off + 4]))
        if not pids:
            break
        found |= pids
        if f"{base + 0x20:02X}" not in pids:
            break
        base += 0x20
    return found
```

3. Add the freeze-frame helper and use it right after the DTCs are read (only when `dtcs.stored` is non-empty):

```python
def _freeze_frame(transport: Transport) -> FreezeFrame | None:
    """Mode 02 frame 0: the DTC that triggered it, then every decodable supported PID."""
    dtc_payloads = [p for p in parse_all(transport.send("020200"), 0x42) if len(p) >= 5]
    if not dtc_payloads:
        return None
    hi, lo = dtc_payloads[0][3], dtc_payloads[0][4]
    if hi == 0 and lo == 0:
        return None
    values: dict[str, PidValue] = {}
    for pid in sorted(_walk_pages(transport, 0x02)):
        if pid not in PIDS:
            continue
        for p in parse_all(transport.send(f"02{pid}00"), 0x42):
            if len(p) >= 3 + PIDS[pid].nbytes and p[1] == int(pid, 16):
                v = decode_pid(pid, p[3:])
                if v is not None:
                    values[pid] = v
                break
    return FreezeFrame(dtc=decode_dtc(hi, lo), pids=values)
```

4. Add `symptoms: str = ""` to `scan(...)`, set `user_context=UserContext(symptoms=symptoms)`, compute readiness from the `0101` payloads already read (`ignition, monitors = parse_readiness(all_status_payloads)` where `all_status_payloads = parse_all(transport.send("0101"), 0x41)`; keep the existing MIL logic on the filtered list), and pass `freeze_frame=..., readiness=monitors, ignition_type=ignition` to `Snapshot(...)`.
5. Update imports: `decode_dtc`, `decode_pid`, `PIDS`, `parse_readiness`, `FreezeFrame`, `PidValue`, `UserContext`, `init_adapter`, `identify`.

In `src/obd_reader/capture.py` add `symptoms: str = ""` to `capture(...)` and pass it to `scan(...)`.

Append these lines to `tests/fixtures/synthetic_sedan.jsonl` (synthetic freeze frame for the P0171 sedan):

```
{"t":3.2,"tx":"020200","rx":["42 02 00 01 71"]}
{"t":3.3,"tx":"020000","rx":["42 00 00 18 18 00 00"]}
{"t":3.4,"tx":"020400","rx":["42 04 00 80"]}
{"t":3.5,"tx":"020500","rx":["42 05 00 7B"]}
{"t":3.6,"tx":"020C00","rx":["42 0C 00 1A F8"]}
{"t":3.7,"tx":"020D00","rx":["42 0D 00 00"]}
```

Update `tests/test_replay.py`: `len(records) == 25`.

- [ ] **Step 6: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -4`
Expected: everything passes, including the previous scanner tests (the refactor to `_walk_pages`/`init_adapter` is covered by them).

- [ ] **Step 7: Commit**

```bash
git add src/obd_reader/adapter.py src/obd_reader/snapshot.py src/obd_reader/scanner.py src/obd_reader/capture.py tests/fixtures/synthetic_sedan.jsonl tests/test_replay.py tests/test_adapter.py tests/test_scanner_extras.py
git commit -m "feat: freeze frame, readiness and symptoms in the scan; shared adapter helpers"
```

---

### Task 5: Live sampler

**Files:**
- Create: `src/obd_reader/live.py`
- Test: `tests/test_live.py`, extend `tests/conftest.py`

**Interfaces:**
- Consumes: `Transport.send`, `parse_all`, `PIDS`, `snapshot.LiveSample/Series`.
- Produces: `live.LiveLimitError(ValueError)`; constants `MAX_PIDS = 8`, `MAX_SECONDS = 120.0`, `MAX_HZ = 10.0`, `MAX_POINTS = 120`; `live.validate_pids(pids: list[str]) -> list[str]` (returns upper-case, raises on bad/duplicate/unknown/too many); `live.sample(transport, pids, seconds, *, hz=2.0, clock=time.monotonic, sleep=time.sleep) -> LiveSample`; `live.summarize(series: Series) -> dict` (`n, min, max, mean, first, last, delta`); `live.downsample(samples, max_points=MAX_POINTS)`.

- [ ] **Step 1: Extend conftest with a scripted ECU**

Append to `tests/conftest.py`:

```python
class ScriptedPort:
    """Answers `01PP` from a table of raw data hex; anything else gets OK, unknown PIDs NO DATA."""

    def __init__(self, pid_data: dict[str, str]):
        self.pid_data = pid_data
        self.writes: list[str] = []
        self._pending = ""

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        self.writes.append(cmd)
        if cmd.startswith("01") and len(cmd) == 4:
            pid = cmd[2:]
            self._pending = (f"41 {pid} {self.pid_data[pid]}\r" if pid in self.pid_data else "NO DATA\r")
        else:
            self._pending = "OK\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def close(self) -> None:
        pass


class FakeClock:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self):
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_live.py`:

```python
import pytest

from obd_reader.live import (
    MAX_POINTS, LiveLimitError, downsample, sample, summarize, validate_pids,
)
from obd_reader.snapshot import Series
from obd_reader.transport import Transport

from conftest import FakeClock, ScriptedPort


def run(pids, seconds, hz=2.0, data=None):
    port = ScriptedPort(data or {"0C": "1AF8", "05": "7B", "06": "80"})
    clk = FakeClock()
    ls = sample(Transport(port), pids, seconds, hz=hz, clock=clk.now, sleep=clk.sleep)
    return ls, port


def test_sample_polls_each_pid_every_tick_and_decodes():
    ls, port = run(["0C", "05"], seconds=2, hz=2)
    assert [t for t, _ in ls.series["0C"].samples] == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert {v for _, v in ls.series["0C"].samples} == {1726.0}
    assert {v for _, v in ls.series["05"].samples} == {83}
    assert ls.series["0C"].name == "engine_rpm" and ls.series["0C"].unit == "rpm"
    assert ls.duration_s == 2 and ls.rate_hz == 2
    assert port.writes and all(c.startswith("01") and len(c) == 4 for c in port.writes)


def test_pid_without_data_yields_an_empty_series_not_an_error():
    ls, _ = run(["0C", "0D"], seconds=1, hz=1, data={"0C": "1AF8"})
    assert ls.series["0D"].samples == [] and len(ls.series["0C"].samples) == 2


@pytest.mark.parametrize(
    "pids",
    [[], ["0C"] * 2, ["0C\r04"], ["ZZ"], ["0c\n"], ["0C0"], ["FF"], [f"{i:02X}" for i in range(9)], [""], [None]],
)
def test_bad_pid_lists_are_refused_before_any_traffic(pids):
    port = ScriptedPort({})
    with pytest.raises(LiveLimitError):
        sample(Transport(port), pids, 1)
    assert port.writes == []


@pytest.mark.parametrize("seconds,hz", [(0, 2), (-1, 2), (121, 2), (10, 0), (10, 11), (10, -1)])
def test_bad_duration_or_rate_is_refused_before_any_traffic(seconds, hz):
    port = ScriptedPort({"0C": "1AF8"})
    with pytest.raises(LiveLimitError):
        sample(Transport(port), ["0C"], seconds, hz=hz)
    assert port.writes == []


def test_validate_pids_normalises_case():
    assert validate_pids(["0c", "5c"]) == ["0C", "5C"]


def test_summarize_is_exact():
    s = Series(name="x", unit="%", samples=[(0.0, 1.0), (1.0, 3.0), (2.0, 2.0)])
    assert summarize(s) == {"n": 3, "min": 1.0, "max": 3.0, "mean": 2.0, "first": 1.0, "last": 2.0, "delta": 1.0}
    assert summarize(Series(name="x", samples=[])) == {"n": 0}


def test_downsample_keeps_endpoints_and_caps_points():  # Review Focus 5
    pts = [(float(i), float(i)) for i in range(1000)]
    out = downsample(pts)
    assert len(out) <= MAX_POINTS and out[0] == pts[0] and out[-1] == pts[-1]
    assert downsample(pts[:10]) == pts[:10]
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_live.py -q --tb=line 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.live'`.

- [ ] **Step 4: Implement**

Create `src/obd_reader/live.py`:

```python
"""Bounded live-data sampling over the gated transport (Mode 01 only)."""
import re
import time
from typing import Callable

from obd_reader.elm import parse_all
from obd_reader.pids import PIDS
from obd_reader.snapshot import LiveSample, Series
from obd_reader.transport import Transport

MAX_PIDS = 8
MAX_SECONDS = 120.0
MAX_HZ = 10.0
MAX_POINTS = 120
_PID_RE = re.compile(r"[0-9A-Fa-f]{2}")


class LiveLimitError(ValueError):
    """A live-data request outside the safety limits or with a bad PID."""


def validate_pids(pids: list[str]) -> list[str]:
    if not pids or len(pids) > MAX_PIDS:
        raise LiveLimitError(f"give between 1 and {MAX_PIDS} PIDs")
    out: list[str] = []
    for p in pids:
        if not isinstance(p, str) or not _PID_RE.fullmatch(p):
            raise LiveLimitError(f"not a 2-digit hex PID: {p!r}")
        p = p.upper()
        if p not in PIDS:
            raise LiveLimitError(f"PID {p} is not in the decoder table")
        if p in out:
            raise LiveLimitError(f"duplicate PID {p}")
        out.append(p)
    return out


def sample(
    transport: Transport,
    pids: list[str],
    seconds: float,
    *,
    hz: float = 2.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> LiveSample:
    pids = validate_pids(pids)
    if not 0 < seconds <= MAX_SECONDS:
        raise LiveLimitError(f"seconds must be in (0, {MAX_SECONDS:g}]")
    if not 0 < hz <= MAX_HZ:
        raise LiveLimitError(f"hz must be in (0, {MAX_HZ:g}]")
    series = {p: Series(name=PIDS[p].name, unit=PIDS[p].unit) for p in pids}
    period, t0 = 1.0 / hz, clock()
    while True:
        t = clock() - t0
        if t > seconds:
            break
        for p in pids:
            d = PIDS[p]
            for payload in parse_all(transport.send(f"01{p}"), 0x41):
                if len(payload) >= 2 + d.nbytes and payload[1] == int(p, 16):
                    series[p].samples.append((round(t, 3), d.decode(payload[2 : 2 + d.nbytes])))
                    break
        sleep(max(0.0, period - (clock() - t0 - t)))
    return LiveSample(duration_s=seconds, rate_hz=hz, series=series)


def summarize(series: Series) -> dict:
    vals = [v for _, v in series.samples]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "min": min(vals), "max": max(vals), "mean": round(sum(vals) / len(vals), 3),
            "first": vals[0], "last": vals[-1], "delta": round(vals[-1] - vals[0], 3)}


def downsample(samples: list[tuple[float, float]], max_points: int = MAX_POINTS) -> list[tuple[float, float]]:
    if len(samples) <= max_points:
        return list(samples)
    step = (len(samples) - 1) / (max_points - 1)
    picked = [samples[round(i * step)] for i in range(max_points)]
    picked[-1] = samples[-1]
    return picked
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -3`
Expected: all pass. (`test_sample_polls_...` last assertion is a loose sanity check that only `01xx` commands were sent.)

- [ ] **Step 6: Commit**

```bash
git add src/obd_reader/live.py tests/conftest.py tests/test_live.py
git commit -m "feat: bounded live-data sampler with limits, stats and downsampling"
```

---

### Task 6: Snapshot store and session

**Files:**
- Create: `src/obd_reader/store.py`, `src/obd_reader/session.py`
- Test: `tests/test_store.py`, `tests/test_session.py`

**Interfaces:**
- Produces:
  - `store.InvalidSnapshotId(ValueError)`; `store.SnapshotStore(root: Path)` with `.dir`, `.path(snapshot_id) -> Path`, `.save(snap) -> Path`, `.load(snapshot_id) -> Snapshot` (FileNotFoundError if absent), `.list() -> list[dict]` (oldest→newest by `captured_at`; keys `snapshot_id`, `captured_at`, `protocol`, `stored_dtcs`), `.import_file(path: Path) -> Snapshot` (path must be a `.json` file inside `root`; refuses to overwrite; never echoes file content in errors).
  - `session.Config(port, baud=115200, timeout=10.0, home=Path("."))` with `Config.from_env(env=None)`; `session.NoAdapterError`, `session.AdapterBusy` (both `RuntimeError`); `session.Session(config, port_factory=None, clock=time.monotonic, sleep=time.sleep)` with `.config`, `.store`, `.clock`, `.sleep`, and `.connection(label: str)` — a context manager yielding an initialised `Transport` that records `transcripts/<utc-time>-<label>.jsonl` and holds a non-blocking lock.

- [ ] **Step 1: Failing store tests**

Create `tests/test_store.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from obd_reader.snapshot import Dtc, Dtcs, Source, Snapshot
from obd_reader.store import InvalidSnapshotId, SnapshotStore


def snap(sid, day=1, dtcs=()):
    return Snapshot(snapshot_id=sid, captured_at=datetime(2026, 9, day, tzinfo=timezone.utc),
                    source=Source(kind="replay", tool_version="0.1.0"),
                    dtcs=Dtcs(stored=[Dtc(code=c) for c in dtcs]))


def test_save_load_round_trip_and_never_overwrites(tmp_path):
    st = SnapshotStore(tmp_path)
    path = st.save(snap("a-1"))
    assert path == tmp_path / "snapshots" / "a-1.json"
    assert st.load("a-1").snapshot_id == "a-1"
    with pytest.raises(FileExistsError):
        st.save(snap("a-1"))


def test_list_is_oldest_first_with_summaries(tmp_path):
    st = SnapshotStore(tmp_path)
    st.save(snap("later", day=5, dtcs=["P0171"]))
    st.save(snap("earlier", day=2))
    rows = st.list()
    assert [r["snapshot_id"] for r in rows] == ["earlier", "later"]
    assert rows[1]["stored_dtcs"] == 1 and "vin" not in rows[1]


def test_missing_snapshot_is_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        SnapshotStore(tmp_path).load("nope")


@pytest.mark.parametrize("sid", ["", "../x", "a/b", "..", ".hidden", "a b", "x" * 100, "a\x00b", "/etc/passwd"])
def test_unsafe_ids_are_rejected(tmp_path, sid):  # Review Focus 2
    with pytest.raises(InvalidSnapshotId):
        SnapshotStore(tmp_path).path(sid)


def test_import_copies_a_valid_snapshot_from_inside_home(tmp_path):
    src = tmp_path / "incoming.json"
    src.write_text(snap("imp-1").model_dump_json())
    st = SnapshotStore(tmp_path)
    assert st.import_file(src).snapshot_id == "imp-1"
    assert st.load("imp-1").snapshot_id == "imp-1"


def test_import_refuses_paths_outside_home_and_wrong_types(tmp_path):  # Review Focus 2
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(snap("x").model_dump_json())
    st = SnapshotStore(home)
    with pytest.raises(ValueError):
        st.import_file(outside)
    (home / "notes.txt").write_text("hi")
    with pytest.raises(ValueError):
        st.import_file(home / "notes.txt")
    with pytest.raises(ValueError):
        st.import_file(home / ".." / "outside.json")


def test_import_errors_do_not_echo_file_contents(tmp_path):  # Review Focus 2
    bad = tmp_path / "secret.json"
    bad.write_text(json.dumps({"password": "hunter2-super-secret"}))
    with pytest.raises(ValueError) as e:
        SnapshotStore(tmp_path).import_file(bad)
    assert "hunter2" not in str(e.value)


def test_import_refuses_to_overwrite(tmp_path):
    st = SnapshotStore(tmp_path)
    st.save(snap("dup"))
    src = tmp_path / "dup-copy.json"
    src.write_text(snap("dup").model_dump_json())
    with pytest.raises(FileExistsError):
        st.import_file(src)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_store.py -q --tb=line 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.store'`.

- [ ] **Step 3: Implement the store**

Create `src/obd_reader/store.py`:

```python
"""Path-safe snapshot storage under <home>/snapshots/."""
import json
import re
from pathlib import Path

from pydantic import ValidationError

from obd_reader.snapshot import Snapshot

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")


class InvalidSnapshotId(ValueError):
    pass


class SnapshotStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.dir = self.root / "snapshots"

    def path(self, snapshot_id: str) -> Path:
        if not isinstance(snapshot_id, str) or not _ID_RE.fullmatch(snapshot_id) or ".." in snapshot_id:
            raise InvalidSnapshotId("snapshot ids are 1-80 chars of letters, digits, '.', '_' and '-'")
        return self.dir / f"{snapshot_id}.json"

    def save(self, snap: Snapshot) -> Path:
        path = self.path(snap.snapshot_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8") as fh:
            fh.write(snap.model_dump_json(indent=2) + "\n")
        return path

    def load(self, snapshot_id: str) -> Snapshot:
        path = self.path(snapshot_id)
        if not path.is_file():
            raise FileNotFoundError(f"no snapshot named {snapshot_id!r}")
        return Snapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        rows = []
        for path in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            try:
                s = Snapshot.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValidationError, ValueError):
                continue
            rows.append({"snapshot_id": s.snapshot_id, "captured_at": s.captured_at.isoformat(),
                         "protocol": s.protocol.name, "stored_dtcs": len(s.dtcs.stored)})
        return sorted(rows, key=lambda r: r["captured_at"])

    def import_file(self, path: Path) -> Snapshot:
        src = Path(path).resolve()
        if src.suffix != ".json" or not src.is_file() or not src.is_relative_to(self.root):
            raise ValueError("import only reads .json files inside the data directory")
        try:
            snap = Snapshot.model_validate(json.loads(src.read_text(encoding="utf-8")))
        except (ValidationError, ValueError):
            raise ValueError("file is not a valid snapshot") from None  # never echo the content
        self.save(snap)
        return snap
```

- [ ] **Step 4: Run to verify the store passes**

Run: `.venv/bin/python -m pytest tests/test_store.py -q --tb=short 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 5: Failing session tests**

Create `tests/test_session.py`:

```python
import json
import threading
from pathlib import Path

import pytest

from obd_reader.session import AdapterBusy, Config, NoAdapterError, Session

from conftest import ScriptedPort


def make(tmp_path, port=None, **cfg):
    return Session(Config(port=port if port is not None else "fake", home=tmp_path, **cfg),
                   port_factory=lambda: ScriptedPort({"0C": "1AF8"}))


def test_config_from_env():
    c = Config.from_env({"SHADETREE_PORT": "/dev/ttyUSB9", "SHADETREE_BAUD": "38400",
                         "SHADETREE_TIMEOUT": "3", "SHADETREE_HOME": "/tmp/x"})
    assert (c.port, c.baud, c.timeout, c.home) == ("/dev/ttyUSB9", 38400, 3.0, Path("/tmp/x"))
    d = Config.from_env({})
    assert d.port is None and d.baud == 115200 and d.timeout == 10.0 and d.home == Path(".")


def test_connection_initialises_the_adapter_and_records_a_transcript(tmp_path):
    s = make(tmp_path)
    with s.connection("unit") as t:
        t.send("010C")
    files = list((tmp_path / "transcripts").glob("*-unit.jsonl"))
    assert len(files) == 1
    lines = [json.loads(l) for l in files[0].read_text().splitlines()]
    assert [l["tx"] for l in lines][:5] == ["ATZ", "ATE0", "ATL0", "ATH0", "ATSP0"]
    assert lines[-1]["tx"] == "010C"


def test_no_port_configured_means_no_adapter_error_and_no_port_opened(tmp_path):
    opened = []
    s = Session(Config(port=None, home=tmp_path), port_factory=lambda: opened.append(1))
    with pytest.raises(NoAdapterError):
        with s.connection("x"):
            pass
    assert opened == []


def test_a_second_connection_while_one_is_open_fails_fast(tmp_path):  # Review Focus 3
    s = make(tmp_path)
    with s.connection("first"):
        with pytest.raises(AdapterBusy):
            with s.connection("second"):
                pass
    with s.connection("third"):  # released afterwards
        pass


def test_lock_is_released_when_the_body_raises(tmp_path):
    s = make(tmp_path)
    with pytest.raises(RuntimeError):
        with s.connection("boom"):
            raise RuntimeError("x")
    with s.connection("after"):
        pass


def test_raw_port_shares_the_lock_and_the_no_adapter_rule(tmp_path):
    s = make(tmp_path)
    with s.raw_port() as port:
        assert port is not None
        with pytest.raises(AdapterBusy):
            with s.connection("x"):
                pass
    with s.connection("y"):  # released
        pass
    with pytest.raises(NoAdapterError):
        with Session(Config(port=None, home=tmp_path), port_factory=lambda: ScriptedPort({})).raw_port():
            pass


def test_port_is_closed_after_use(tmp_path):
    closed = []

    class P(ScriptedPort):
        def close(self):
            closed.append(True)

    s = Session(Config(port="fake", home=tmp_path), port_factory=lambda: P({}))
    with s.connection("c"):
        pass
    assert closed == [True]
```

- [ ] **Step 6: Run to verify failure, then implement**

Run: `.venv/bin/python -m pytest tests/test_session.py -q --tb=line 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.session'`.

Create `src/obd_reader/session.py`:

```python
"""Live-adapter session: config from the environment, one connection at a time,
every command recorded to a transcript."""
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping

from obd_reader.adapter import init_adapter
from obd_reader.store import SnapshotStore
from obd_reader.transport import Port, SerialPort, TranscriptRecorder, Transport


class NoAdapterError(RuntimeError):
    """SHADETREE_PORT is not set, so live tools cannot reach an adapter."""


class AdapterBusy(RuntimeError):
    """Another tool call is using the adapter."""


@dataclass
class Config:
    port: str | None
    baud: int = 115200
    timeout: float = 10.0
    home: Path = field(default_factory=lambda: Path("."))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        return cls(
            port=env.get("SHADETREE_PORT") or None,
            baud=int(env.get("SHADETREE_BAUD", 115200)),
            timeout=float(env.get("SHADETREE_TIMEOUT", 10)),
            home=Path(env.get("SHADETREE_HOME", ".")),
        )


class Session:
    def __init__(
        self,
        config: Config,
        port_factory: Callable[[], Port] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.store = SnapshotStore(config.home)
        self.clock, self.sleep = clock, sleep
        self._lock = threading.Lock()
        self._factory = port_factory or (lambda: SerialPort(config.port, baudrate=config.baud))

    def _acquire(self) -> None:
        if not self.config.port:
            raise NoAdapterError("SHADETREE_PORT is not set; live tools need the adapter's serial port")
        if not self._lock.acquire(blocking=False):
            raise AdapterBusy("the adapter is busy with another tool call; try again in a moment")

    @contextmanager
    def raw_port(self) -> Iterator[Port]:
        """A fresh port under the same lock, for callers (scan) that build their own Transport."""
        self._acquire()
        port = None
        try:
            port = self._factory()
            yield port
        finally:
            if port is not None:
                port.close()
            self._lock.release()

    @contextmanager
    def connection(self, label: str, protocol: str | None = "0") -> Iterator[Transport]:
        self._acquire()
        transport = None
        try:
            tdir = Path(self.config.home) / "transcripts"
            tdir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
            recorder = TranscriptRecorder(tdir / f"{stamp}-{label}.jsonl")
            transport = Transport(self._factory(), recorder=recorder, default_timeout=self.config.timeout)
            init_adapter(transport, protocol)
            yield transport
        finally:
            if transport is not None:
                transport.close()
            self._lock.release()
```

`connection` opens the transcript recorder before the port; if the factory raises, the lock is still released by the `finally`.

- [ ] **Step 7: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/obd_reader/store.py src/obd_reader/session.py tests/test_store.py tests/test_session.py
git commit -m "feat: path-safe snapshot store and single-owner recording session"
```

---

### Task 7: Mode 06 parser

**Files:**
- Create: `src/obd_reader/mode06.py`
- Test: `tests/test_mode06.py`

**Interfaces:**
- Consumes: payloads from `elm.parse_all(lines, 0x46)`; `elm.decode_supported`.
- Produces: `mode06.Mode06Result` (pydantic: `mid: str, tid: str, uasid: str, value: int, minimum: int, maximum: int, within_limits: bool | None`); `mode06.supported_mids(payloads: list[bytes], base: int) -> set[str]`; `mode06.parse_results(payload: bytes) -> list[Mode06Result]`. **Layout is from the J1979 description and is NOT yet verified on a real car** (`46 MID` then repeated 8-byte groups `TID UASID VAL(2) MIN(2) MAX(2)`); raw integers only, no unit scaling. Task 11 validates it on hardware.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mode06.py`:

```python
from obd_reader.mode06 import Mode06Result, parse_results, supported_mids


def test_supported_mids_bitmap():
    assert supported_mids([bytes.fromhex("460080000001")], 0x00) == {"01", "20"}
    assert supported_mids([bytes.fromhex("462000000001")], 0x00) == set()  # wrong page for this base


def test_parse_two_result_groups():
    payload = bytes.fromhex("46 01 8B 0A 12 34 00 00 FF FF  8C 0A 00 05 00 00 00 03".replace(" ", ""))
    res = parse_results(payload)
    assert res[0] == Mode06Result(mid="01", tid="8B", uasid="0A", value=0x1234, minimum=0, maximum=0xFFFF,
                                  within_limits=True)
    assert res[1].tid == "8C" and res[1].value == 5 and res[1].within_limits is False


def test_min_greater_than_max_gives_unknown_limits():
    payload = bytes.fromhex("46 02 01 0A 00 05 00 09 00 03".replace(" ", ""))
    assert parse_results(payload)[0].within_limits is None


def test_incomplete_trailing_group_is_dropped_not_raised():
    payload = bytes.fromhex("46 01 8B 0A 12 34 00 00 FF FF  8C 0A 00".replace(" ", ""))
    assert [r.tid for r in parse_results(payload)] == ["8B"]


def test_not_a_mode06_payload_returns_nothing():
    assert parse_results(b"") == [] and parse_results(b"\x41\x01\x00") == [] and parse_results(b"\x46") == []
```

- [ ] **Step 2: Run to verify failure, then implement**

Run: `.venv/bin/python -m pytest tests/test_mode06.py -q --tb=line 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.mode06'`.

Create `src/obd_reader/mode06.py`:

```python
"""Mode 06 (on-board monitoring test results) over CAN.

Layout used here (J1979 description, NOT yet verified on hardware): `46 MID` then
repeated 8-byte groups `TID UASID VAL_H VAL_L MIN_H MIN_L MAX_H MAX_L`. Values are
raw integers: the UASID unit/scaling table is not applied.
"""
from pydantic import BaseModel

from obd_reader.elm import decode_supported


class Mode06Result(BaseModel):
    mid: str
    tid: str
    uasid: str
    value: int
    minimum: int
    maximum: int
    within_limits: bool | None


def supported_mids(payloads: list[bytes], base: int) -> set[str]:
    out: set[str] = set()
    for p in payloads:
        if len(p) >= 6 and p[0] == 0x46 and p[1] == base:
            out.update(decode_supported(base, p[2:6]))
    return out


def parse_results(payload: bytes) -> list[Mode06Result]:
    if len(payload) < 2 or payload[0] != 0x46:
        return []
    mid, body = f"{payload[1]:02X}", payload[2:]
    out = []
    for i in range(0, len(body) - 7, 8):
        g = body[i : i + 8]
        value, lo, hi = (int.from_bytes(g[a : a + 2], "big") for a in (2, 4, 6))
        out.append(Mode06Result(
            mid=mid, tid=f"{g[0]:02X}", uasid=f"{g[1]:02X}", value=value, minimum=lo, maximum=hi,
            within_limits=(lo <= value <= hi) if lo <= hi else None,
        ))
    return out
```

- [ ] **Step 3: Run to verify pass, commit**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -3`
Expected: all pass.

```bash
git add src/obd_reader/mode06.py tests/test_mode06.py
git commit -m "feat: Mode 06 parser (layout unverified on hardware; raw values only)"
```

---

### Task 8: Offline snapshot tools

**Files:**
- Create: `src/obd_reader/tools.py`
- Test: `tests/test_tools_offline.py`

**Interfaces:**
- Consumes: `Session`, `SnapshotStore`, snapshot models, `PIDS`/`pid_name`.
- Produces: `tools.build_tools(session: Session) -> dict[str, Callable]` (Task 9 extends it with the live tools), `tools.TOOL_NAMES: frozenset[str]` (the complete expected set, updated in Task 9), `tools.NoSnapshotError(LookupError)`. Offline tools take `snapshot_id: str | None = None` where `None` means "the newest saved snapshot". Offline tool names: `list_snapshots`, `get_snapshot`, `import_snapshot`, `read_dtcs`, `freeze_frame`, `readiness`, `vehicle_info`, `list_supported_pids`, `compare_snapshots`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_offline.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.session import Config, Session
from obd_reader.store import InvalidSnapshotId
from obd_reader.tools import NoSnapshotError, build_tools
from obd_reader.transport import Transport

FIX = Path(__file__).parent / "fixtures"


def snapshot_from(name, sid, protocol):
    port = ReplayPort(load_transcript(FIX / name))
    return scan(Transport(port), snapshot_id=sid, captured_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
                protocol=protocol, symptoms="rough idle")


@pytest.fixture
def session(tmp_path):
    s = Session(Config(port=None, home=tmp_path))
    s.store.save(snapshot_from("synthetic_sedan.jsonl", "sedan-1", "6"))
    s.store.save(snapshot_from("ridgeline_2024_can29.jsonl", "ridge-1", "0"))
    return s


@pytest.fixture
def tools(session):
    return build_tools(session)


def test_list_and_get(tools):
    rows = tools["list_snapshots"]()["snapshots"]
    assert {r["snapshot_id"] for r in rows} == {"sedan-1", "ridge-1"}
    got = tools["get_snapshot"]("sedan-1")
    assert got["vehicle"]["vin"] == "1HGCM82633A004352"


def test_default_is_the_newest_snapshot_and_empty_store_is_a_clear_error(tmp_path):
    empty = build_tools(Session(Config(port=None, home=tmp_path)))
    with pytest.raises(NoSnapshotError):
        empty["read_dtcs"]()


def test_read_dtcs_kinds(tools):
    out = tools["read_dtcs"]("sedan-1", "stored")
    assert [d["code"] for d in out["dtcs"]] == ["P0171"] and out["mil"]["on"] is True
    assert tools["read_dtcs"]("sedan-1", "pending")["dtcs"] == []
    assert [d["code"] for d in tools["read_dtcs"]("sedan-1", "all")["dtcs"]] == ["P0171"]
    with pytest.raises(ValueError):
        tools["read_dtcs"]("sedan-1", "everything")


def test_freeze_frame(tools):
    ff = tools["freeze_frame"]("sedan-1")["freeze_frame"]
    assert ff["dtc"] == "P0171" and ff["pids"]["0C"]["value"] == 1726.0
    assert tools["freeze_frame"]("ridge-1")["freeze_frame"] is None


def test_readiness_summarises_incomplete_and_unsupported(tools):
    r = tools["readiness"]("ridge-1")
    assert r["ignition_type"] == "spark" and r["incomplete"] == []
    assert "heated_catalyst" in r["not_supported"] and "catalyst" in r["monitors"]


def test_vehicle_info_has_no_raw_transcript_path_leak_beyond_the_snapshot(tools):
    v = tools["vehicle_info"]("ridge-1")
    assert v["vin"] == "5FPYK3F51RB000001" and v["protocol"] == "ISO 15765-4 (CAN 29/500)"
    assert v["adapter"]["genuine_stn"] is True and "02" in v["supported_mode09_pids"]


def test_list_supported_pids_names_decodable_pids(tools):
    out = tools["list_supported_pids"]("ridge-1")["mode01"]
    by = {p["pid"]: p for p in out}
    assert by["05"]["name"] == "coolant_temp" and by["0C"]["decodable"] is True
    assert by["01"]["decodable"] is False and by["01"]["name"] == "unknown"


def test_compare_snapshots_reports_differences(tools):
    d = tools["compare_snapshots"]("sedan-1", "ridge-1")
    assert d["dtcs"]["only_in_a"] == ["P0171"] and d["dtcs"]["only_in_b"] == []
    assert d["mil"] == {"a": True, "b": False}
    assert d["protocol"]["a"] != d["protocol"]["b"]
    assert "08" in d["supported_pids"]["only_in_b"]  # supported by the Ridgeline's ECU 1, not by the sedan


def test_unsafe_ids_are_refused(tools):  # Review Focus 2
    for bad in ("../x", "a/b", "/etc/passwd"):
        with pytest.raises(InvalidSnapshotId):
            tools["get_snapshot"](bad)


def test_import_snapshot_inside_home_only(tools, session, tmp_path):  # Review Focus 2
    src = tmp_path / "copy.json"
    snap = session.store.load("sedan-1").model_copy(update={"snapshot_id": "sedan-copy"})
    src.write_text(snap.model_dump_json())
    assert tools["import_snapshot"](str(src))["snapshot_id"] == "sedan-copy"
    with pytest.raises(ValueError):
        tools["import_snapshot"]("/etc/hostname")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_tools_offline.py -q --tb=line 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.tools'`.

- [ ] **Step 3: Implement**

Create `src/obd_reader/tools.py`:

```python
"""Tool functions shared by every front end. Offline tools read saved snapshots;
live tools (added in the next task) are the only ones that open the adapter."""
from pathlib import Path
from typing import Callable

from obd_reader.pids import PIDS, pid_name
from obd_reader.session import Session
from obd_reader.snapshot import Snapshot

OFFLINE_TOOLS = frozenset({
    "list_snapshots", "get_snapshot", "import_snapshot", "read_dtcs", "freeze_frame",
    "readiness", "vehicle_info", "list_supported_pids", "compare_snapshots",
})
LIVE_TOOLS: frozenset[str] = frozenset()  # filled in by the live-tools task
TOOL_NAMES = OFFLINE_TOOLS | LIVE_TOOLS


class NoSnapshotError(LookupError):
    """No snapshot has been saved yet."""


def _dump(model) -> dict:
    return model.model_dump(mode="json")


def build_tools(session: Session) -> dict[str, Callable]:
    store = session.store

    def latest_or(snapshot_id: str | None) -> Snapshot:
        if snapshot_id is not None:
            return store.load(snapshot_id)
        rows = store.list()
        if not rows:
            raise NoSnapshotError("no snapshots saved yet; run `scan` first or import one")
        return store.load(rows[-1]["snapshot_id"])

    def list_snapshots() -> dict:
        """List saved vehicle snapshots, oldest first."""
        return {"snapshots": store.list()}

    def get_snapshot(snapshot_id: str | None = None) -> dict:
        """Return a saved snapshot (the newest if no id is given)."""
        return _dump(latest_or(snapshot_id))

    def import_snapshot(path: str) -> dict:
        """Import a snapshot JSON file that already sits inside the data directory."""
        snap = store.import_file(Path(path))
        return {"snapshot_id": snap.snapshot_id}

    def read_dtcs(snapshot_id: str | None = None, kind: str = "stored") -> dict:
        """Diagnostic trouble codes from a snapshot: kind is stored, pending, permanent or all."""
        if kind not in ("stored", "pending", "permanent", "all"):
            raise ValueError("kind must be stored, pending, permanent or all")
        s = latest_or(snapshot_id)
        kinds = ("stored", "pending", "permanent") if kind == "all" else (kind,)
        dtcs = [{**_dump(d), "kind": k} for k in kinds for d in getattr(s.dtcs, k)]
        return {"snapshot_id": s.snapshot_id, "kind": kind, "dtcs": dtcs, "mil": _dump(s.mil)}

    def freeze_frame(snapshot_id: str | None = None) -> dict:
        """The freeze frame stored with the first DTC, if the snapshot has one."""
        s = latest_or(snapshot_id)
        return {"snapshot_id": s.snapshot_id, "freeze_frame": _dump(s.freeze_frame) if s.freeze_frame else None}

    def readiness(snapshot_id: str | None = None) -> dict:
        """Emissions readiness monitors: which are supported and which are not yet complete."""
        s = latest_or(snapshot_id)
        mons = {n: _dump(m) for n, m in s.readiness.items() if m.supported}
        return {
            "snapshot_id": s.snapshot_id,
            "ignition_type": s.ignition_type,
            "monitors": mons,
            "incomplete": [n for n, m in s.readiness.items() if m.supported and m.complete is False],
            "not_supported": [n for n, m in s.readiness.items() if not m.supported],
        }

    def vehicle_info(snapshot_id: str | None = None) -> dict:
        """VIN, protocol, adapter, ECUs and supported Mode 09 items from a snapshot."""
        s = latest_or(snapshot_id)
        return {
            "snapshot_id": s.snapshot_id,
            "vin": s.vehicle.vin,
            "vin_source": s.vehicle.vin_source,
            "decoded": _dump(s.vehicle.decoded) if s.vehicle.decoded else None,
            "protocol": s.protocol.name,
            "adapter": _dump(s.source.adapter),
            "ecus": [_dump(e) for e in s.ecus],
            "supported_mode09_pids": s.supported_pids.get("09", []),
            "user_context": _dump(s.user_context),
            "warnings": s.warnings,
        }

    def list_supported_pids(snapshot_id: str | None = None) -> dict:
        """Mode 01 PIDs the car supports, with names for the ones we can decode."""
        s = latest_or(snapshot_id)
        return {
            "snapshot_id": s.snapshot_id,
            "mode01": [
                {"pid": p, "name": pid_name(p), "unit": PIDS[p].unit if p in PIDS else None,
                 "decodable": p in PIDS}
                for p in s.supported_pids.get("01", [])
            ],
        }

    def compare_snapshots(a: str, b: str) -> dict:
        """Differences between two snapshots: DTCs, MIL, protocol, supported PIDs, readiness."""
        sa, sb = store.load(a), store.load(b)

        def codes(s):
            return {d.code for k in ("stored", "pending", "permanent") for d in getattr(s.dtcs, k)}

        pa, pb = set(sa.supported_pids.get("01", [])), set(sb.supported_pids.get("01", []))
        return {
            "a": a, "b": b,
            "dtcs": {"only_in_a": sorted(codes(sa) - codes(sb)), "only_in_b": sorted(codes(sb) - codes(sa))},
            "mil": {"a": sa.mil.on, "b": sb.mil.on},
            "protocol": {"a": sa.protocol.name, "b": sb.protocol.name},
            "supported_pids": {"only_in_a": sorted(pa - pb), "only_in_b": sorted(pb - pa)},
            "incomplete_monitors": {
                "a": sorted(n for n, m in sa.readiness.items() if m.complete is False),
                "b": sorted(n for n, m in sb.readiness.items() if m.complete is False),
            },
        }

    return {f.__name__: f for f in (
        list_snapshots, get_snapshot, import_snapshot, read_dtcs, freeze_frame,
        readiness, vehicle_info, list_supported_pids, compare_snapshots,
    )}
```

- [ ] **Step 4: Run to verify pass, commit**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -3`
Expected: all pass.

```bash
git add src/obd_reader/tools.py tests/test_tools_offline.py
git commit -m "feat: offline snapshot tools (dtcs, freeze frame, readiness, vehicle info, compare)"
```

---

### Task 9: Live tools

**Files:**
- Modify: `src/obd_reader/tools.py`
- Test: `tests/test_tools_live.py`

**Interfaces:**
- Consumes: `Session.connection`, `adapter.identify`, `capture`, `live.sample/summarize/downsample/validate_pids`, `mode06`, `pids.decode_pid`.
- Produces: live tools in `build_tools`: `adapter_info()`, `scan(label="scan", protocol="0", symptoms="")`, `read_pid(pid)`, `live_data(pids, seconds=10, hz=2, conditions="")`, `trim_summary(seconds=15, hz=2)`, `mode06_tests(mid=None)`. `LIVE_TOOLS` becomes `frozenset({"adapter_info","scan","read_pid","live_data","trim_summary","mode06_tests"})`, so `TOOL_NAMES` has 15 names.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_live.py`:

```python
import inspect
from pathlib import Path

import pytest

from obd_reader.allowlist import check_command
from obd_reader.live import LiveLimitError
from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.session import AdapterBusy, Config, NoAdapterError, Session
from obd_reader.tools import LIVE_TOOLS, OFFLINE_TOOLS, TOOL_NAMES, build_tools

from conftest import FakeClock, ScriptedPort

FIX = Path(__file__).parent / "fixtures"
FORBIDDEN_PARAMS = {"cmd", "command", "raw", "hex", "at", "payload", "data"}


def live_session(tmp_path, factory, clk=None):
    clk = clk or FakeClock()
    return Session(Config(port="fake", home=tmp_path, timeout=0.2), port_factory=factory,
                   clock=clk.now, sleep=clk.sleep)


def test_tool_names_are_exactly_the_reviewed_set(tmp_path):
    tools = build_tools(live_session(tmp_path, lambda: ScriptedPort({})))
    assert set(tools) == set(TOOL_NAMES) == set(OFFLINE_TOOLS | LIVE_TOOLS)
    assert len(TOOL_NAMES) == 15


def test_no_tool_accepts_a_command_string(tmp_path):
    tools = build_tools(live_session(tmp_path, lambda: ScriptedPort({})))
    for name, fn in tools.items():
        assert FORBIDDEN_PARAMS.isdisjoint(inspect.signature(fn).parameters), name


def test_read_pid_decodes_and_records(tmp_path):
    s = live_session(tmp_path, lambda: ScriptedPort({"0C": "1AF8"}))
    out = build_tools(s)["read_pid"]("0c")
    assert out["pid"] == "0C" and out["name"] == "engine_rpm" and out["value"] == 1726.0
    assert list((tmp_path / "transcripts").glob("*-read-pid.jsonl"))


def test_read_pid_without_data_says_so(tmp_path):
    s = live_session(tmp_path, lambda: ScriptedPort({}))
    out = build_tools(s)["read_pid"]("0C")
    assert out["value"] is None and "no data" in out["note"].lower()


@pytest.mark.parametrize("bad", ["0C\r04", "ZZ", "", "0C0", "0c\n", "FF"])
def test_read_pid_refuses_smuggled_commands(tmp_path, bad):  # Review Focus 1
    ports = []
    s = live_session(tmp_path, lambda: ports.append(ScriptedPort({})) or ports[-1])
    with pytest.raises(LiveLimitError):
        build_tools(s)["read_pid"](bad)
    assert ports == []  # validation happens before any port is opened


def test_live_data_returns_stats_and_at_most_120_points(tmp_path):  # Review Focus 5
    s = live_session(tmp_path, lambda: ScriptedPort({"0C": "1AF8", "05": "7B"}))
    out = build_tools(s)["live_data"](["0C", "05"], seconds=120, hz=10)
    rpm = out["series"]["0C"]
    assert len(rpm["samples"]) <= 120 and 1199 <= rpm["stats"]["n"] <= 1202  # 120 s x 10 Hz, float ticks
    assert rpm["stats"]["min"] == rpm["stats"]["max"] == 1726.0
    assert out["duration_s"] == 120 and out["hz"] == 10


def test_live_data_limits(tmp_path):
    tools = build_tools(live_session(tmp_path, lambda: ScriptedPort({})))
    with pytest.raises(LiveLimitError):
        tools["live_data"](["0C"], seconds=500)
    with pytest.raises(LiveLimitError):
        tools["live_data"]([f"{i:02X}" for i in range(9)])


def test_trim_summary_covers_supported_trims_only(tmp_path):
    s = live_session(tmp_path, lambda: ScriptedPort({"06": "80", "07": "6B"}))
    out = build_tools(s)["trim_summary"](seconds=2, hz=1)
    assert out["series"]["07"]["stats"]["mean"] == pytest.approx(-16.4, abs=0.1)
    assert out["series"]["08"]["stats"] == {"n": 0} and "no data" in out["notes"]["08"].lower()


def test_adapter_info_reports_identity_and_voltage(tmp_path):
    recs = [{"tx": "ATZ", "rx": ["ELM327 v1.4b"]}, {"tx": "ATE0", "rx": ["OK"]}, {"tx": "ATL0", "rx": ["OK"]},
            {"tx": "ATH0", "rx": ["OK"]}, {"tx": "ATSP0", "rx": ["OK"]},
            {"tx": "ATI", "rx": ["ELM327 v1.4b"]}, {"tx": "STI", "rx": ["STN2232 v5.12.4"]},
            {"tx": "STDI", "rx": ["OBDLink EX r2.7.1"]}, {"tx": "ATRV", "rx": ["12.6V"]}]
    s = live_session(tmp_path, lambda: ReplayPort(recs))
    out = build_tools(s)["adapter_info"]()
    assert out["chip"] == "STN2232" and out["genuine_stn"] is True
    assert out["device"] == "OBDLink EX r2.7.1" and out["supply_voltage"] == "12.6V"


def test_scan_saves_a_snapshot_the_offline_tools_can_read(tmp_path):
    recs = load_transcript(FIX / "synthetic_sedan.jsonl")
    s = live_session(tmp_path, lambda: ReplayPort(recs))
    tools = build_tools(s)
    out = tools["scan"]("bench", "6", "rough idle")
    assert out["vin"] == "1HGCM82633A004352" and out["stored_dtcs"] == ["P0171"]
    assert tools["read_dtcs"](out["snapshot_id"])["dtcs"][0]["code"] == "P0171"
    assert tools["get_snapshot"](out["snapshot_id"])["user_context"]["symptoms"] == "rough idle"


def test_scan_rejects_bad_labels_and_protocols_before_traffic(tmp_path):  # Review Focus 1
    ports = []
    s = live_session(tmp_path, lambda: ports.append(ReplayPort([])) or ports[-1])
    for label, proto in (("../x", "0"), ("ok", "0\r04"), ("ok", "Z")):
        with pytest.raises(ValueError):
            build_tools(s)["scan"](label, proto)
    assert all(p.written == [] for p in ports)


def test_mode06_lists_supported_tests_then_reads_them(tmp_path):
    recs = [{"tx": c, "rx": ["OK"]} for c in ("ATZ", "ATE0", "ATL0", "ATH0", "ATSP0")]
    recs += [{"tx": "0600", "rx": ["46 00 80 00 00 00"]},
             {"tx": "0601", "rx": ["46 01 8B 0A 12 34 00 00 FF FF"]}]
    s = live_session(tmp_path, lambda: ReplayPort(recs))
    out = build_tools(s)["mode06_tests"]()
    assert out["supported_mids"] == ["01"]
    assert out["results"][0]["tid"] == "8B" and out["results"][0]["within_limits"] is True
    assert "unverified" in out["note"].lower()


def test_mode06_rejects_a_bad_mid(tmp_path):  # Review Focus 1
    tools = build_tools(live_session(tmp_path, lambda: ScriptedPort({})))
    for bad in ("0", "ZZ", "01\r04", "001", "0G", ""):
        with pytest.raises(ValueError):
            tools["mode06_tests"](bad)


def test_live_tools_fail_clearly_without_an_adapter(tmp_path):  # Review Focus 4
    s = Session(Config(port=None, home=tmp_path))
    for name, args in (("adapter_info", ()), ("read_pid", ("0C",)), ("scan", ("x",)), ("mode06_tests", ())):
        with pytest.raises(NoAdapterError):
            build_tools(s)[name](*args)


def test_silent_adapter_gives_a_structured_answer_not_a_hang(tmp_path):  # Review Focus 4
    class Silent(ScriptedPort):
        def write(self, data):
            self.writes.append(data.decode().rstrip("\r"))
            self._pending = ""

    s = live_session(tmp_path, lambda: Silent({}))
    out = build_tools(s)["read_pid"]("0C")
    assert out["value"] is None


def test_concurrent_live_calls_fail_fast(tmp_path):  # Review Focus 3
    s = live_session(tmp_path, lambda: ScriptedPort({"0C": "1AF8"}))
    tools = build_tools(s)
    with s.connection("holder"):
        with pytest.raises(AdapterBusy):
            tools["read_pid"]("0C")


def test_every_live_command_stays_inside_the_allowlist(tmp_path):
    ports = []
    s = live_session(tmp_path, lambda: ports.append(ScriptedPort({"0C": "1AF8", "05": "7B"})) or ports[-1])
    tools = build_tools(s)
    tools["read_pid"]("0C")
    tools["live_data"](["0C", "05"], seconds=1, hz=2)
    tools["trim_summary"](seconds=1, hz=1)
    tools["mode06_tests"]("01")
    for p in ports:
        for c in p.writes:
            assert check_command(c) == c
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_tools_live.py -q --tb=line 2>&1 | grep -E "KeyError|Error|passed|failed" | head -4`
Expected: failures such as `KeyError: 'read_pid'` (tools not defined yet).

- [ ] **Step 3: Implement the live tools**

In `src/obd_reader/tools.py`:
1. Set `LIVE_TOOLS = frozenset({"adapter_info", "scan", "read_pid", "live_data", "trim_summary", "mode06_tests"})`.
2. Add imports: `re`, `from obd_reader.adapter import identify`, `from obd_reader.capture import capture`, `from obd_reader.elm import parse_all`, `from obd_reader.live import LiveLimitError, downsample, sample, summarize, validate_pids`, `from obd_reader.mode06 import parse_results, supported_mids`, `from obd_reader.pids import decode_pid`, `from obd_reader.transport import Transport`.
3. Add module constants: `_MID_RE = re.compile(r"[0-9A-Fa-f]{2}")`, `_LABEL_RE = re.compile(r"[a-z0-9-]{1,40}")`, `_PROTO_RE = re.compile(r"[0-9A-Ca-c]")`, `MAX_MODE06_MIDS = 40`.
4. Inside `build_tools`, before the final `return`, add these tool functions:

```python
    def _series_out(ls) -> dict:
        return {p: {"name": s.name, "unit": s.unit, "stats": summarize(s),
                    "samples": downsample(s.samples)} for p, s in ls.series.items()}

    def adapter_info() -> dict:
        """Identify the connected adapter (chip, firmware, device id) and read its supply voltage."""
        with session.connection("adapter-info") as t:
            a = identify(t)
            device = (t.send("STDI") or [None])[0]
            volts = (t.send("ATRV") or [None])[0]
        return {"ati": a.ati, "sti": a.sti, "chip": a.chip, "genuine_stn": a.genuine_stn,
                "device": device, "supply_voltage": volts}

    def scan(label: str = "scan", protocol: str = "0", symptoms: str = "") -> dict:
        """Run a full read-only scan of the car and save a snapshot. protocol is 0 (auto) or an ATSP digit 1-C."""
        if not _LABEL_RE.fullmatch(label):
            raise ValueError("label must be 1-40 chars of [a-z0-9-]")
        if not _PROTO_RE.fullmatch(protocol):
            raise ValueError("protocol must be one character 0-9 or A-C")
        with session.raw_port() as port:  # same lock as every live tool; capture records its own transcript
            snap, s_path, t_path = capture(
                port, session.config.home, label=label, protocol=protocol.upper(),
                timeout=session.config.timeout, symptoms=symptoms,
            )
        return {"snapshot_id": snap.snapshot_id, "vin": snap.vehicle.vin, "protocol": snap.protocol.name,
                "stored_dtcs": [d.code for d in snap.dtcs.stored], "mil": _dump(snap.mil),
                "ecus": [e.header for e in snap.ecus], "warnings": snap.warnings}

    def read_pid(pid: str) -> dict:
        """Read one Mode 01 PID once (the PID must be in the decoder table)."""
        pid = validate_pids([pid])[0]
        with session.connection("read-pid") as t:
            payloads = parse_all(t.send(f"01{pid}"), 0x41)
        for p in payloads:
            if len(p) >= 3 and p[1] == int(pid, 16):
                v = decode_pid(pid, p[2:])
                if v is not None:
                    return {"pid": pid, "name": v.name, "value": v.value, "unit": v.unit, "raw": v.raw}
        return {"pid": pid, "name": PIDS[pid].name, "value": None, "unit": PIDS[pid].unit,
                "note": "no data: the ECU did not answer this PID"}

    def live_data(pids: list[str], seconds: float = 10, hz: float = 2, conditions: str = "") -> dict:
        """Poll up to 8 Mode 01 PIDs for up to 120 s at up to 10 Hz; returns stats plus a downsampled series."""
        validate_pids(pids)
        with session.connection("live") as t:
            ls = sample(t, pids, seconds, hz=hz, clock=session.clock, sleep=session.sleep)
        return {"duration_s": ls.duration_s, "hz": ls.rate_hz, "conditions": conditions,
                "series": _series_out(ls)}

    def trim_summary(seconds: float = 15, hz: float = 2) -> dict:
        """Fuel-trim statistics (short and long term, both banks) over a short sample."""
        with session.connection("trims") as t:
            ls = sample(t, ["06", "07", "08", "09"], seconds, hz=hz, clock=session.clock, sleep=session.sleep)
        out = _series_out(ls)
        notes = {p: "no data: the ECU did not answer this PID" for p, s in ls.series.items() if not s.samples}
        return {"duration_s": ls.duration_s, "hz": ls.rate_hz, "series": out, "notes": notes}

    def mode06_tests(mid: str | None = None) -> dict:
        """Read Mode 06 on-board test results (raw values; format unverified on hardware). mid is a 2-digit hex monitor id, or omit for all supported."""
        if mid is not None and not _MID_RE.fullmatch(mid):
            raise ValueError("mid must be 2 hex digits")
        with session.connection("mode06") as t:
            if mid is None:
                mids: set[str] = set()
                base = 0x00
                while base <= 0xE0:
                    found = supported_mids(parse_all(t.send(f"06{base:02X}"), 0x46), base)
                    if not found:
                        break
                    mids |= found
                    if f"{base + 0x20:02X}" not in found:
                        break
                    base += 0x20
                wanted = sorted(mids)[:MAX_MODE06_MIDS]
            else:
                mids, wanted = {mid.upper()}, [mid.upper()]
            results = []
            for m in wanted:
                for payload in parse_all(t.send(f"06{m}"), 0x46):
                    results += [r.model_dump() for r in parse_results(payload)]
        return {"supported_mids": sorted(mids), "results": results,
                "note": "Mode 06 layout is unverified on real hardware; values are raw integers with no unit scaling."}
```

5. Extend the returned dict: append `adapter_info, scan, read_pid, live_data, trim_summary, mode06_tests` to the tuple in the final `return`. Define `LIVE_TOOLS` before `TOOL_NAMES` so the union sees it.

(`Session.raw_port()` and its test were added in Task 6.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -4`
Expected: everything passes. If `test_live_data_returns_stats_and_at_most_120_points` reports `n != 1201`, the fake-clock tick count is the cause (120 s × 10 Hz + the t=0 sample); fix the test's expectation only if the arithmetic in `live.sample` (sample at `t = 0, 0.1, …, 120.0`) is confirmed correct.

- [ ] **Step 5: Commit**

```bash
git add src/obd_reader/tools.py src/obd_reader/session.py tests/test_tools_live.py tests/test_session.py
git commit -m "feat: live tools (adapter_info, scan, read_pid, live_data, trim_summary, mode06_tests)"
```

---

### Task 10: MCP server and entry point

**Files:**
- Create: `src/obd_reader/mcp_server.py`
- Modify: `pyproject.toml`, `README.md`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `build_tools`, `TOOL_NAMES`, `Session`, `Config`.
- Produces: `mcp_server.build_server(session: Session) -> MCPServer`, `mcp_server.INSTRUCTIONS: str`, `mcp_server.main() -> None` (stdio). Dependency `mcp>=2.2,<3`; console script `shadetree-ai-mcp`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml` set `dependencies = ["pydantic>=2.6", "pyserial>=3.5", "mcp>=2.2,<3"]` and add:

```toml
[project.scripts]
shadetree-ai-mcp = "obd_reader.mcp_server:main"
```

Run: `.venv/bin/pip install -q -e ".[dev]"`
Expected: installs `mcp` 2.x without error.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_mcp_server.py`:

```python
import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from obd_reader.mcp_server import INSTRUCTIONS, build_server
from obd_reader.session import Config, Session
from obd_reader.tools import TOOL_NAMES

from conftest import ScriptedPort


def server(tmp_path):
    return build_server(Session(Config(port="fake", home=tmp_path), port_factory=lambda: ScriptedPort({"0C": "1AF8"})))


def test_exactly_the_reviewed_tools_are_registered_and_all_read_only(tmp_path):
    tools = asyncio.run(server(tmp_path).list_tools())
    assert {t.name for t in tools} == set(TOOL_NAMES)
    for t in tools:
        assert t.annotations is not None and t.annotations.read_only_hint is True, t.name
        assert t.annotations.destructive_hint is False, t.name


def test_tool_schemas_never_expose_a_command_parameter(tmp_path):
    for t in asyncio.run(server(tmp_path).list_tools()):
        props = set((t.input_schema or {}).get("properties", {}))
        assert not props & {"cmd", "command", "raw", "hex", "at", "payload", "data"}, t.name


def test_a_tool_call_round_trips_through_the_server(tmp_path):
    res = asyncio.run(server(tmp_path).call_tool("read_pid", {"pid": "0C"}))
    assert res.is_error is False
    assert json.loads(res.content[0].text)["value"] == 1726.0


def test_bad_arguments_surface_our_message_as_a_tool_error(tmp_path):
    # In mcp 2.x a plain ValueError is hidden behind "Error executing tool"; ToolError keeps the message.
    with pytest.raises(ToolError) as e:
        asyncio.run(server(tmp_path).call_tool("read_pid", {"pid": "0C\r04"}))
    assert "2-digit hex PID" in str(e.value)


def test_adapter_busy_reaches_the_caller_readably(tmp_path):
    s = Session(Config(port="fake", home=tmp_path), port_factory=lambda: ScriptedPort({"0C": "1AF8"}))
    with s.connection("holder"):
        with pytest.raises(ToolError) as e:
            asyncio.run(build_server(s).call_tool("read_pid", {"pid": "0C"}))
    assert "busy" in str(e.value).lower()


def test_no_adapter_configured_is_a_readable_error(tmp_path):
    srv = build_server(Session(Config(port=None, home=tmp_path)))
    with pytest.raises(ToolError) as e:
        asyncio.run(srv.call_tool("adapter_info", {}))
    assert "SHADETREE_PORT" in str(e.value)


def test_schemas_survive_the_error_wrapper(tmp_path):
    by_name = {t.name: t for t in asyncio.run(server(tmp_path).list_tools())}
    assert set(by_name["read_pid"].input_schema["properties"]) == {"pid"}
    assert set(by_name["live_data"].input_schema["properties"]) == {"pids", "seconds", "hz", "conditions"}


def test_instructions_state_the_read_only_and_grounding_contracts():
    assert "read-only" in INSTRUCTIONS.lower() and "never clear" in INSTRUCTIONS.lower()
    assert "general knowledge, unverified" in INSTRUCTIONS
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_mcp_server.py -q --tb=line 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.mcp_server'`.

- [ ] **Step 4: Implement**

Create `src/obd_reader/mcp_server.py`:

```python
"""MCP front end. Every tool is registered read-only; the tool list is the reviewed
set in tools.TOOL_NAMES and no tool takes a command string."""
import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from obd_reader.session import Config, Session
from obd_reader.tools import TOOL_NAMES, build_tools

INSTRUCTIONS = (
    "shadetree-ai is a READ-ONLY OBD-II assistant. It can read codes, freeze frames, readiness "
    "monitors, live data and Mode 06 test results; it can never clear codes, write to an ECU or "
    "run actuator tests, and no tool accepts a raw command. If asked to clear codes, say so and "
    "tell the user to use their own scan tool after the repair. Cite a tool result or a reference "
    "record for every diagnostic claim; label anything else 'general knowledge, unverified'. "
    "Live tools need the car parked with the ignition on; offline tools read saved snapshots."
)


def _surface_errors(fn):
    """mcp 2.x hides an ordinary exception's message behind 'Error executing tool'; ToolError
    keeps it, so Claude sees 'adapter is busy' or 'not a 2-digit hex PID' and can react."""

    @functools.wraps(fn)  # keeps the signature, so the generated input schema is unchanged
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, RuntimeError, LookupError, OSError) as e:
            raise ToolError(str(e)) from None

    return wrapper


def build_server(session: Session) -> MCPServer:
    server = MCPServer("shadetree-ai", instructions=INSTRUCTIONS)
    tools = build_tools(session)
    assert set(tools) == set(TOOL_NAMES), "tool registry drifted from the reviewed set"
    for name, fn in tools.items():
        server.tool(
            name=name,
            annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False),
        )(_surface_errors(fn))
    return server


def main() -> None:
    build_server(Session(Config.from_env())).run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -4`
Expected: everything passes (`Tool.input_schema` and `ToolError` behavior were verified against mcp 2.2.0 while writing this plan).

- [ ] **Step 6: Document usage and commit**

Add to `README.md` a "Use with Claude Code" section:

```
claude mcp add shadetree-ai -e SHADETREE_PORT=/dev/serial/by-id/<your-EX> -e SHADETREE_HOME=$HOME/shadetree-data -- /path/to/shadetree-ai/.venv/bin/python -m obd_reader.mcp_server
```

Note that the exact flags come from `claude mcp add --help`; `SHADETREE_HOME` holds `snapshots/` and `transcripts/` (VINs: keep it out of git).

```bash
git add src/obd_reader/mcp_server.py pyproject.toml README.md tests/test_mcp_server.py
git commit -m "feat: read-only MCP server exposing the tool layer"
```

---

### Task 11: Hardware smoke test (asks Neil first)

**Files:** none (no repo changes unless a bug is found)

- [ ] **Step 1: Ask Neil** for permission to open the EX on this machine with no car attached and run only `adapter_info` through the MCP server code path. Do not proceed without a yes.

- [ ] **Step 2: Run** (with the EX on USB, no car):

```bash
SHADETREE_PORT=/dev/serial/by-id/usb-ScanTool.net_LLC_OBDLink_EX_223230414498-if00-port0 SHADETREE_HOME=/tmp/shadetree-smoke .venv/bin/python -c "import asyncio, json; from obd_reader.mcp_server import build_server; from obd_reader.session import Config, Session; s = build_server(Session(Config.from_env())); print(asyncio.run(s.call_tool('adapter_info', {})).content[0].text)"
```

Expected: JSON with `"chip": "STN2232"`, `"genuine_stn": true`, `"device": "OBDLink EX r2.7.1"`, and a `supply_voltage` near `0.0V` (no car). A transcript appears under `/tmp/shadetree-smoke/transcripts/`.

- [ ] **Step 3: Register with Claude Code** (only if Neil asks): run the `claude mcp add` command from the README and confirm `list_tools` shows 15 tools.

- [ ] **Step 4: Ask Neil to run `mode06_tests` on the Ridgeline** to validate the Mode 06 layout (Task 7), and paste the transcript lines for `06xx` so the fixture can be added with a synthetic VIN.

---

## Self-Review (done)

- **Spec coverage:** allowlist widening (Task 1); PID table, readiness, freeze frame, symptoms, ECU union already shipped (Tasks 2–4); live sampler with §7 limits (Task 5); store, session, transcripts (Task 6); Mode 06 (Task 7); §7 tools `scan`, `get_snapshot`, `list_snapshots`, `read_dtcs`, `freeze_frame`, `live_data`, `import_snapshot` (Tasks 8–9) plus extras (`adapter_info`, `readiness`, `vehicle_info`, `list_supported_pids`, `compare_snapshots`, `read_pid`, `trim_summary`, `mode06_tests`); MCP server with read-only annotations and tool-name-set test (Task 10). Not covered here by design: `decode_vin`, `lookup_reference`, `get_playbook`, `check_citations`, recalls/complaints/TSBs (Phase 3b plan); UDS `0x19` (own plan); Mode 05 tool (Phase 4, non-CAN).
- **Placeholders:** none. Two deliberate "simplify while implementing" notes (Task 6 factory check, Task 9 `raw_port`) name the exact final behavior and the tests that pin it.
- **Type consistency:** `parse_all`, `decode_supported`, `decode_pid`, `PIDS`, `Session.connection(label, protocol)`, `Session.raw_port()`, `build_tools`, `TOOL_NAMES` are used with the same names across tasks.
- **Known limits carried forward:** Mode 06 layout unverified on hardware; 29-bit ECU header parsing unverified; compression-ignition monitor names are placeholders; O2 PID `14`–`1B` decode uses only the voltage byte; non-CAN DTC/VIN decode still skipped.
