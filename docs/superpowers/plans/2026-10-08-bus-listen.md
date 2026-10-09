# Bus listen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `shadetree-ai listen`: a time-limited, listen-only bus capture (ATMA / STN STMA) with a guided action script, written as JSON Lines under `captures/`, plus a payload-free summary.

**Architecture:** The allowlist gains the monitor commands. `transport.py` (still the only pyserial importer) gains a stateful raw-mode gate and `Transport.monitor()`, a generator of timestamped frame/gap/idle events with a guaranteed stop-and-restore in `finally`. `bus_capture.py` writes and summarizes capture files; `listen.py` runs the standard scan, the setup and the guided script over the monitor events. `SimPort` streams made-up broadcast frames so everything runs without a car.

**Tech Stack:** Python 3.11+, pyserial, pydantic (unchanged), pytest + hypothesis. No new dependencies (`termios`, `select`, `msvcrt` are stdlib).

**Spec:** `docs/superpowers/specs/2026-10-08-bus-listen-design.md` (approved by Neil 2026-10-08). Read it before Task 1.

## Global Constraints

- Read-only: from the moment a monitor command is written until the adapter's `>` prompt returns, nothing is transmitted on the bus. No command that sends data to the car is added.
- `ATCAF0` is never on the allowlist. Only `Transport.monitor()` sends it, and while it is on, every command that is not `AT`/`ST` is refused before the port, in `Transport.send` and again in `SerialPort.write`. `ATCAF1` is restored in a `finally`.
- `ATMA` / `STMA` are on the allowlist (so `SerialPort.write` passes them), but `Transport.send` refuses them: only `Transport.monitor()` starts a monitor.
- On a CAN protocol, `ATCSM1` is sent first and anything but `OK` stops the listen before any monitor command (`SilentModeUnsupported`). J1850 and K-line skip it.
- Monitor time: `0 < seconds <= 900`. Script: window 10 s, rest 5 s, baseline 30 s.
- `transport.py` stays the only module that imports `serial`.
- Public repo: no VINs and no real captures committed. `captures/` is gitignored and guarded by `tests/test_no_real_vins.py`. Simulator frames and IDs are made up. Summaries never contain payload bytes.
- Run tests in a worktree with `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest` and the page test with `node tests/js/page_logic_test.js src/obd_reader/web/console.html` (untouched here, but the full suite runs it).
- Commits: only on the feature branch, only after Neil has allowed commits for this branch, staged by name, and with no attribution trailer (project rule). Never merge or push without his word.
- Match the surrounding style: one-line docstrings, short `#` comments that say why, lazy imports inside CLI handlers.

## Review Focus

1. Ctrl-C during a capture: the adapter must still be stopped and `ATCAF1` restored, the file must end with an `end` record (`interrupted`), and the CLI must say where the partial capture is (exit 130, no traceback). Tested in Task 5 (`run_capture`) and Task 6 (CLI).
2. A frame line split across two serial reads must be joined into one frame, not recorded as two halves. Tested in Task 2.
3. A silent bus (the Ridgeline behind a gateway): a capture with zero frames must finish, and its summary must say so instead of dividing by zero. Tested in Tasks 4 and 5.
4. stdin that is not a terminal (piped, IDE run, pytest): no crash; the script runs without `s`/`q`. Tested in Task 5.
5. The adapter unplugged mid-capture (`read_available` raises `OSError`): the file keeps an `end` record (`error`), stays readable, and summarizes. Tested in Task 5, plus the truncated-file test in Task 4.

---

### Task 1: Allowlist entries and the SerialPort raw gate

**Files:**
- Modify: `src/obd_reader/allowlist.py`
- Modify: `src/obd_reader/transport.py` (class `SerialPort` only)
- Modify: `tests/test_allowlist.py`
- Create: `tests/test_serial_gate.py`

**Interfaces:**
- Produces: `allowlist.MONITOR_COMMANDS: frozenset[str]` (`{"ATMA", "STMA"}`), `allowlist.RAW_ON: str` (`"ATCAF0"`); `SerialPort.read_available(timeout: float) -> str`; `SerialPort.interrupt() -> None`; `SerialPort.write` accepts `ATCAF0` and then refuses non-AT/ST bodies until `ATCAF1`, `ATZ` or `ATD`.

- [ ] **Step 1: Update the allowlist tests (they fail first)**

In `tests/test_allowlist.py`: add `"ATMA", "STMA", "AT CSM 1", "ATAL"` to `ALLOWED`; remove `"ATMA"` from `FORBIDDEN` and add `"ATCSM0", "ATCSM", "ATMA1", "STMAX"`; keep `"ATCAF0", "ATCAF 0"` in `FORBIDDEN`. In `test_fuzz_near_miss_strings` replace the AT/ST branch with:

```python
    if canon[:2] in ("AT", "ST"):
        assert not canon.startswith(("ATPP", "STPX", "ATCAF0", "ATCSM0"))
        if canon.startswith(("ATMA", "STMA")):
            assert canon in ("ATMA", "STMA")
```

Add at the end of the file:

```python
def test_monitor_commands_and_raw_mode_constants():
    from obd_reader.allowlist import MONITOR_COMMANDS, RAW_ON

    assert MONITOR_COMMANDS == frozenset({"ATMA", "STMA"})
    assert all(check_command(c) == c for c in MONITOR_COMMANDS)
    with pytest.raises(ForbiddenCommand):
        check_command(RAW_ON)  # only Transport.monitor() sends it
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_allowlist.py -q`
Expected: FAIL (`ATMA` refused, `MONITOR_COMMANDS` missing).

- [ ] **Step 3: Change the allowlist**

In `src/obd_reader/allowlist.py`, replace the docstring's last paragraph and add the constants and patterns:

```python
"""Read-only command allowlist: the single source of truth for what may be sent.

`check_command` returns the canonical (uppercase, spaceless, ASCII) command that
the transport writes. Anything else raises ForbiddenCommand.

Not enabled yet (see docs/design.md §13): UDS 0x19 / 0x22, STIX-style STN
commands (unverified on hardware), ATPPS.

ATCAF0 (raw CAN frames) is not on the list: only Transport.monitor() sends it,
inside a listen-only monitor, and while it is on every non-AT/ST command is
refused (CAF0 + 0104 would put a raw clear-codes frame on the bus).
"""
import re

ALLOWED_MODES = frozenset({0x01, 0x02, 0x03, 0x05, 0x06, 0x07, 0x09, 0x0A})
MONITOR_COMMANDS = frozenset({"ATMA", "STMA"})  # stream until stopped: Transport.send refuses them, only Transport.monitor() starts one
RAW_ON = "ATCAF0"
```

and in `_PATTERNS`, after `r"ATCAF1", r"ATAT[012]",  # ...`:

```python
        r"ATCSM1", r"ATAL",  # silent CAN monitoring on (ATCSM0 refused); allow long messages
        r"ATMA",  # listen-only bus monitor (approved by the maintainer 2026-10-08)
```

and after `r"STI", r"STDI",`:

```python
        r"STMA",  # STN monitor all (listen only)
```

- [ ] **Step 4: Run the allowlist tests**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_allowlist.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing SerialPort tests**

Create `tests/test_serial_gate.py`:

```python
import time

import pytest

from obd_reader.allowlist import ForbiddenCommand
from obd_reader.transport import SerialPort


def test_raw_mode_refuses_obd_commands_until_caf1(elm_server):
    url = elm_server([{"tx": "ATCAF0", "rx": ["OK"]}, {"tx": "ATCAF1", "rx": ["OK"]}, {"tx": "0104", "rx": ["41 04 00"]}])
    sp = SerialPort(url)
    try:
        sp.write(b"ATCAF0\r")
        assert "OK" in sp.read_until_prompt(2)
        with pytest.raises(ForbiddenCommand, match="raw CAN mode"):
            sp.write(b"0104\r")  # with CAF0 this would be a raw clear-codes frame
        sp.write(b"ATCAF1\r")
        assert "OK" in sp.read_until_prompt(2)
        sp.write(b"0104\r")
        assert "41 04 00" in sp.read_until_prompt(2)
    finally:
        sp.close()


def test_atcaf0_is_the_only_off_list_body_and_other_junk_is_still_refused():
    sp = SerialPort("loop://")
    try:
        for bad in (b"ATCAF 0\r", b"atcaf0\r", b"04\r", b"ATCSM0\r"):
            with pytest.raises(ForbiddenCommand):
                sp.write(bad)
    finally:
        sp.close()


def test_interrupt_sends_a_cr_only_while_a_reply_is_outstanding():
    sp = SerialPort("loop://")  # loop:// echoes what is written
    try:
        sp.interrupt()
        time.sleep(0.05)
        assert sp.read_available(0.2) == ""  # at the prompt a CR would repeat the last command
        sp.write(b"ATI\r")
        sp.interrupt()
        time.sleep(0.05)
        assert sp.read_available(0.3) == "ATI\r\r"
    finally:
        sp.close()
```

- [ ] **Step 6: Run them to see them fail**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_serial_gate.py -q`
Expected: FAIL (`ATCAF0` refused as not canonical; no `interrupt`/`read_available`).

- [ ] **Step 7: Implement the SerialPort changes**

In `src/obd_reader/transport.py` change the import to `from obd_reader.allowlist import RAW_ON, ForbiddenCommand, check_command`. In `SerialPort.__init__` add after `self.recovery_s = 2.0 ...`:

```python
        self._raw = False  # ATCAF0 sent and not undone: only AT/ST commands may follow
```

Replace `SerialPort.write` with:

```python
    def write(self, data: bytes) -> None:
        # Second gate: SerialPort is public, so it refuses anything that is not
        # exactly one canonical allowlisted command (or the monitor's ATCAF0) plus a single CR.
        if not data.endswith(b"\r") or not data[:-1].isascii():
            raise ForbiddenCommand(f"not one CR-terminated ASCII command: {data!r}")
        body = data[:-1].decode("ascii")
        if body != RAW_ON and check_command(body) != body:
            raise ForbiddenCommand(f"not a canonical command: {data!r}")
        if self._raw and body[:2] not in ("AT", "ST"):
            raise ForbiddenCommand(f"raw CAN mode (ATCAF0) is on: {body!r} is refused")
        if not self._prompt_seen:
            self._wait_for_prompt()
        self._ser.reset_input_buffer()  # drop any late reply to the previous command
        self._ser.write(data)
        self._prompt_seen = False
        if body == RAW_ON:
            self._raw = True
        elif body in ("ATCAF1", "ATZ", "ATD"):
            self._raw = False
```

Add after `read_until_prompt`:

```python
    def read_available(self, timeout: float) -> str:
        """What the adapter sends within `timeout` (a monitor stream); a '>' means it is back at the prompt."""
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._ser.read(self._ser.in_waiting or 1)
            if chunk:
                buf += chunk
                if b">" in chunk:
                    self._prompt_seen = True
                    break
            elif buf:
                break
        return buf.decode("ascii", errors="replace")

    def interrupt(self) -> None:
        """Stop a monitor stream: one CR, and only while no prompt has come back (at a prompt a CR repeats the last command)."""
        if not self._prompt_seen:
            self._ser.write(b"\r")
```

- [ ] **Step 8: Run the gate tests and the transport-related suite**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_serial_gate.py tests/test_allowlist.py tests/test_probe.py -q`
Expected: PASS.

- [ ] **Step 9: Commit (branch only, if allowed)**

```bash
git add src/obd_reader/allowlist.py src/obd_reader/transport.py tests/test_allowlist.py tests/test_serial_gate.py
git commit -m "feat: the allowlist takes the listen-only monitor commands (ATMA, STMA, ATCSM1, ATAL); SerialPort accepts ATCAF0 only as a raw-mode switch and then refuses every non-AT/ST command until ATCAF1, ATZ or ATD, reads a monitor stream and stops it with one CR only while no prompt has come back"
```

---

### Task 2: `Transport.monitor()`

**Files:**
- Modify: `src/obd_reader/transport.py` (class `Transport`, new `MonitorEvent`, `SilentModeUnsupported`, `MAX_MONITOR_S`)
- Create: `tests/test_monitor.py`

**Interfaces:**
- Consumes: `MONITOR_COMMANDS`, `RAW_ON` (Task 1); a port with `read_available(timeout) -> str` and `interrupt() -> None`.
- Produces:
  - `MAX_MONITOR_S = 900.0`
  - `@dataclass(frozen=True) class MonitorEvent: kind: str; t: float; text: str = ""; seconds: float = 0.0`. `kind` is `"frame"` (text = the raw line), `"gap"` (text = what stopped the stream, seconds = time until frames resumed or the monitor ended) or `"idle"` (a read with nothing in it). `t` is seconds since the transport opened.
  - `class SilentModeUnsupported(RuntimeError)`
  - `Transport.now -> float` (property, seconds since the transport opened)
  - `Transport.monitor(cmd: str, seconds: float, *, can: bool) -> Iterator[MonitorEvent]`. Checks run eagerly (before the first `next`). Closing the iterator (or an exception) stops the adapter and restores `ATCAF1`.
  - `Transport.send` refuses `MONITOR_COMMANDS` and, while raw mode is on, every non-AT/ST command.
- Stop lines (`ADAPTER_STOPS`): `"BUFFER FULL"`, `"CAN ERROR"`, `"BUS ERROR"`, `"STOPPED"`, `"?"`; they are never recorded as frames.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_monitor.py`:

```python
import pytest
from hypothesis import given, settings, strategies as st

from conftest import FakeClock, ScriptedPort
from obd_reader.allowlist import ForbiddenCommand
from obd_reader.transport import MonitorEvent, SilentModeUnsupported, Transport


class StreamPort:
    """A monitor-capable fake: commands get replies from a table; after ATMA/STMA, each read returns the next chunk."""

    def __init__(self, chunks=(), replies=None, clock=None, fail_on_read=None):
        self.replies = {"ATCSM1": "OK", "ATCAF0": "OK", "ATCAF1": "OK", **(replies or {})}
        self.chunks, self.clock, self.fail_on_read = list(chunks), clock, fail_on_read
        self.writes, self.interrupts, self.reads, self._pending = [], 0, 0, ""

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        self.writes.append(cmd)
        self._pending = "" if cmd in ("ATMA", "STMA") else self.replies.get(cmd, "OK") + "\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def read_available(self, timeout: float) -> str:
        self.reads += 1
        if self.fail_on_read == self.reads:
            raise OSError("adapter unplugged")
        if self.clock:
            self.clock.sleep(0.1)
        return self.chunks.pop(0) if self.chunks else ""

    def interrupt(self) -> None:
        self.interrupts += 1
        self._pending = "STOPPED\r"

    def close(self) -> None:
        pass


def run(chunks, seconds=0.35, can=True, **kw):
    clk = FakeClock()
    port = StreamPort(chunks, clock=clk, **kw)
    t = Transport(port, clock=clk.now)
    return port, t, list(t.monitor("ATMA", seconds, can=can))


def test_frames_stream_with_times_and_the_adapter_is_stopped_and_restored():
    port, _, ev = run(["0C9 01 02\r1F5 00\r"])
    assert [(e.kind, e.text) for e in ev if e.kind == "frame"] == [("frame", "0C9 01 02"), ("frame", "1F5 00")]
    assert ev[0].t == pytest.approx(0.1)
    assert port.writes == ["ATCSM1", "ATCAF0", "ATMA", "ATCAF1"] and port.interrupts == 1


def test_a_line_split_across_reads_is_one_frame():
    _, _, ev = run(["0C9 01 02", " 03\r1F5 00\r"])
    assert [e.text for e in ev if e.kind == "frame"] == ["0C9 01 02 03", "1F5 00"]


def test_buffer_full_gives_a_gap_with_its_length_and_a_restart():
    port, _, ev = run(["0C9 01\rBUFFER FULL\r>", "", "0C9 02\r"], seconds=0.45)
    kinds = [(e.kind, e.text) for e in ev if e.kind != "idle"]
    assert kinds == [("frame", "0C9 01"), ("gap", "BUFFER FULL"), ("frame", "0C9 02")]
    gap = next(e for e in ev if e.kind == "gap")
    assert gap.t == pytest.approx(0.1) and gap.seconds == pytest.approx(0.2)
    assert port.writes.count("ATMA") == 2


def test_a_prompt_at_the_end_needs_no_interrupt_and_the_gap_runs_to_the_end():
    port, _, ev = run(["0C9 01\rSTOPPED\r>"], seconds=0.1)
    assert [(e.kind, e.text) for e in ev] == [("frame", "0C9 01"), ("gap", "STOPPED")]
    assert port.interrupts == 0 and port.writes[-1] == "ATCAF1"


def test_raw_mode_refuses_obd_commands_only_while_monitoring():
    clk = FakeClock()
    port = StreamPort(["0C9 01\r"], clock=clk)
    t = Transport(port, clock=clk.now)
    it = t.monitor("ATMA", 5, can=True)
    next(it)
    with pytest.raises(ForbiddenCommand, match="raw CAN mode"):
        t.send("0104")
    assert t.send("ATRV") == ["OK"]  # AT commands still pass
    it.close()
    assert port.interrupts == 1 and port.writes[-1] == "ATCAF1"
    assert t.send("0104") == ["OK"]


def test_an_exception_mid_stream_still_stops_and_restores():
    clk = FakeClock()
    port = StreamPort(["0C9 01\r"], clock=clk, fail_on_read=2)
    t = Transport(port, clock=clk.now)
    with pytest.raises(OSError):
        list(t.monitor("ATMA", 5, can=True))
    assert port.interrupts == 1 and port.writes[-1] == "ATCAF1"


@settings(max_examples=60, deadline=None)
@given(st.from_regex(r"0[0-9A][0-9A-F]{0,4}", fullmatch=True))
def test_while_raw_every_obd_command_is_refused_before_the_port(cmd):
    clk = FakeClock()
    port = StreamPort(["0C9 01\r"], clock=clk)
    t = Transport(port, clock=clk.now)
    it = t.monitor("ATMA", 5, can=True)
    next(it)
    n = len(port.writes)
    with pytest.raises(ForbiddenCommand):
        t.send(cmd)
    assert len(port.writes) == n
    it.close()


def test_can_needs_silent_mode_and_refusal_sends_no_monitor():
    port = StreamPort(replies={"ATCSM1": "?"})
    with pytest.raises(SilentModeUnsupported):
        Transport(port).monitor("ATMA", 1, can=True)
    assert port.writes == ["ATCSM1"]


def test_j1850_skips_silent_mode_and_raw_mode():
    port, _, _ = run(["88 FE 10 0B 01 02 AA\r"], can=False)
    assert port.writes == ["ATMA"]


@pytest.mark.parametrize("seconds", [0, -1, 901, float("nan"), float("inf")])
def test_seconds_must_be_in_range(seconds):
    with pytest.raises(ValueError):
        Transport(StreamPort()).monitor("ATMA", seconds, can=False)


def test_send_refuses_monitor_commands_and_monitor_refuses_other_commands():
    port = StreamPort()
    t = Transport(port)
    for cmd in ("ATMA", "STMA", "at ma"):
        with pytest.raises(ForbiddenCommand):
            t.send(cmd)
    with pytest.raises(ForbiddenCommand):
        t.monitor("ATI", 1, can=False)
    assert port.writes == []


def test_a_port_that_cannot_stream_is_refused():
    with pytest.raises(ValueError, match="cannot monitor"):
        Transport(ScriptedPort({})).monitor("ATMA", 1, can=False)


def test_now_counts_from_the_transport_opening():
    clk = FakeClock()
    clk.t = 5.0
    t = Transport(StreamPort(), clock=clk.now)
    clk.t = 7.5
    assert t.now == pytest.approx(2.5)
    assert MonitorEvent("idle", 1.0).text == ""
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_monitor.py -q`
Expected: FAIL (`ImportError: cannot import name 'MonitorEvent'`).

- [ ] **Step 3: Implement**

In `src/obd_reader/transport.py`: imports become

```python
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

from obd_reader.allowlist import MONITOR_COMMANDS, RAW_ON, ForbiddenCommand, check_command
```

Add after `class AdapterNotReady`:

```python
class SilentModeUnsupported(RuntimeError):
    """The adapter did not accept ATCSM1, so it might ACK frames on a CAN bus; nothing was monitored."""


MAX_MONITOR_S = 900.0
ADAPTER_STOPS = frozenset({"BUFFER FULL", "CAN ERROR", "BUS ERROR", "STOPPED", "?"})  # the adapter's reasons for leaving a monitor


@dataclass(frozen=True)
class MonitorEvent:
    kind: str  # "frame" (text = the raw line), "gap" (text = what stopped the stream) or "idle" (a read with nothing in it)
    t: float  # seconds since the transport opened
    text: str = ""
    seconds: float = 0.0  # gap: until frames resumed, or the monitor ended
```

In `Transport.__init__` add `self._raw = False  # ATCAF0 on (inside monitor() only)`. Add the property after `transcript_path`:

```python
    @property
    def now(self) -> float:
        return self._clock() - self._t0
```

Replace `send` with `send` + `_exchange`:

```python
    def send(self, cmd: str, timeout: float | None = None) -> list[str]:
        canon = check_command(cmd)  # raises before anything touches the port
        if canon in MONITOR_COMMANDS:
            raise ForbiddenCommand(f"{canon} streams until stopped: only Transport.monitor() sends it")
        if self._raw and canon[:2] not in ("AT", "ST"):
            raise ForbiddenCommand(f"raw CAN mode (ATCAF0) is on: {canon!r} is refused")
        return self._exchange(canon, timeout)

    def _exchange(self, canon: str, timeout: float | None = None) -> list[str]:
        self._port.write(canon.encode("ascii") + b"\r")
        raw = self._port.read_until_prompt(self._default_timeout if timeout is None else timeout)
        lines = [ln.strip() for ln in raw.replace("\r", "\n").split("\n") if ln.strip()]
        if self._recorder is not None:
            self._recorder.record(self._clock() - self._t0, canon, lines)
        return lines
```

Add `monitor` and `_stream` after `_exchange`:

```python
    def monitor(self, cmd: str, seconds: float, *, can: bool) -> Iterator[MonitorEvent]:
        """Listen only: stream every bus frame for up to `seconds`. Nothing is transmitted between the monitor
        command and the returning prompt; closing the iterator stops the adapter and restores ATCAF1."""
        canon = check_command(cmd)
        if canon not in MONITOR_COMMANDS:
            raise ForbiddenCommand(f"not a monitor command: {cmd!r}")
        if not (isinstance(seconds, (int, float)) and math.isfinite(seconds) and 0 < seconds <= MAX_MONITOR_S):
            raise ValueError(f"seconds must be in (0, {MAX_MONITOR_S:g}]")
        if not (hasattr(self._port, "read_available") and hasattr(self._port, "interrupt")):
            raise ValueError("this port cannot monitor (no streaming read)")
        if can:
            reply = self.send("ATCSM1")
            if "OK" not in reply:
                raise SilentModeUnsupported(f"the adapter answered {reply!r} to ATCSM1 (silent CAN monitoring); nothing was monitored")
        return self._stream(canon, seconds, can)

    def _stream(self, canon: str, seconds: float, can: bool) -> Iterator[MonitorEvent]:
        port, prompt = self._port, True
        try:
            if can and "OK" in self._exchange(RAW_ON):
                self._raw = True
            end = self._clock() + seconds
            self._start(canon)
            prompt = False
            buf, gap = "", None
            while self._clock() < end:
                chunk = port.read_available(0.1)
                now = self.now
                if not chunk:
                    yield MonitorEvent("idle", now)
                    continue
                if ">" in chunk:
                    chunk, prompt = chunk.split(">", 1)[0], True  # back at the prompt: the stream ended
                *lines, buf = (buf + chunk).replace("\r", "\n").split("\n")
                if prompt:
                    lines, buf = lines + [buf], ""
                for ln in (x.strip() for x in lines):
                    if not ln:
                        continue
                    if ln in ADAPTER_STOPS:
                        gap = gap or (now, ln)
                        continue
                    if gap:
                        yield MonitorEvent("gap", gap[0], gap[1], now - gap[0])
                        gap = None
                    yield MonitorEvent("frame", now, ln)
                if prompt:
                    gap = gap or (now, "prompt")
                    if self._clock() < end:
                        self._start(canon)
                        prompt = False
            if gap:
                yield MonitorEvent("gap", gap[0], gap[1], self.now - gap[0])
        finally:
            if not prompt:
                port.interrupt()
                port.read_until_prompt(self._default_timeout)  # drains "STOPPED" and the prompt
            if self._raw:
                self._exchange("ATCAF1")
                self._raw = False

    def _start(self, canon: str) -> None:
        self._port.write(canon.encode("ascii") + b"\r")  # no read_until_prompt: the reply is the stream
        if self._recorder is not None:
            self._recorder.record(self.now, canon, ["(monitor stream: see the capture file)"])
```

- [ ] **Step 4: Run the monitor tests**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_monitor.py -q`
Expected: PASS. If `test_buffer_full_gives_a_gap_with_its_length_and_a_restart` fails on timing, check that the gap time is the read that saw `BUFFER FULL` (0.1) and its length runs to the first frame after the restart (0.3).

- [ ] **Step 5: Run the full suite (send() changed for every caller)**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit (branch only, if allowed)**

```bash
git add src/obd_reader/transport.py tests/test_monitor.py
git commit -m "feat: Transport.monitor(): a listen-only, time-limited stream of frame, gap and idle events; CAN needs ATCSM1 (refusal stops it before any monitor command) and runs in raw mode, during which send() refuses every non-AT/ST command; BUFFER FULL and other stops become timed gaps with a restart; closing or an error stops the adapter (one CR, only without a prompt) and restores ATCAF1; send() refuses ATMA and STMA"
```

---

### Task 3: Simulator monitor mode

**Files:**
- Modify: `src/obd_reader/simulator.py` (class `SimPort`)
- Modify: `tests/test_simulator.py`

**Interfaces:**
- Consumes: `Transport.monitor` (Task 2) in one test.
- Produces: `SimPort(scenario="rich", clock=time.monotonic, seed=7, bus=None, sleep=time.sleep)`; `bus` is `None` (today's behaviour: `ATDPN` answers `OK`, so existing simulator-based tests are unchanged), `"can"` or `"j1850"`; with a bus, `ATDPN` answers `A6` (CAN) or `A2` (J1850); after `ATMA`/`STMA`, `read_available` returns made-up broadcast frames due since the last read; `interrupt()` ends the stream and the next `read_until_prompt` returns `"STOPPED\r"`.
- Made-up traffic. CAN (ATH1/ATS1 layout): `0C9` at 50 Hz (`hi lo` of rpm x 4, a 4-bit counter, five `00`), `1F5` at 20 Hz (seven `00` and a counter), `3B4` at 5 Hz (`20 00 00 00`). J1850: `88 FE 10 0B hi lo ck` at 10 Hz, `8A FE 40 01 00 ck` at 2 Hz, where `ck` is the byte sum & 0xFF (not a real J1850 CRC).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_simulator.py` (it already imports `FakeClock` from conftest; add `from collections import Counter`, `from obd_reader.transport import Transport` and `from obd_reader.vin import find_vins` if missing):

```python
@pytest.mark.parametrize("bus,dpn", [("can", "A6"), ("j1850", "A2")])
def test_atdpn_names_the_simulated_bus(bus, dpn):
    sim = SimPort("healthy", bus=bus)
    sim.write(b"ATDPN\r")
    assert sim.read_until_prompt(1) == dpn + "\r"


def test_an_unknown_bus_is_refused():
    with pytest.raises(ValueError):
        SimPort("healthy", bus="flexray")


def test_can_monitor_streams_made_up_frames_at_their_rates_and_stops():
    clk = FakeClock()
    sim = SimPort("healthy", clock=clk.now, sleep=clk.sleep, bus="can")
    assert sim.read_available(0.1) == ""  # nothing before a monitor command
    sim.write(b"ATMA\r")
    clk.sleep(1.0)
    lines = [ln for ln in sim.read_available(0.1).split("\r") if ln]
    ids = Counter(ln.split()[0] for ln in lines)
    assert ids["0C9"] == 50 and ids["1F5"] == 20 and ids["3B4"] == 5
    assert all(len(tok) in (2, 3) and int(tok, 16) >= 0 for ln in lines for tok in ln.split())
    assert find_vins(" ".join(lines)) == []
    sim.interrupt()
    assert sim.read_until_prompt(1) == "STOPPED\r" and sim.read_available(0.1) == ""


def test_j1850_frames_have_a_three_byte_header_and_a_sum_byte():
    clk = FakeClock()
    sim = SimPort("healthy", clock=clk.now, sleep=clk.sleep, bus="j1850")
    sim.write(b"ATMA\r")
    clk.sleep(1.0)
    lines = [ln.split() for ln in sim.read_available(0.1).split("\r") if ln]
    assert Counter(" ".join(t[:3]) for t in lines) == {"88 FE 10": 10, "8A FE 40": 2}
    assert all(int(t[-1], 16) == sum(int(x, 16) for x in t[:-1]) & 0xFF for t in lines)


def test_a_transport_monitors_the_simulator():
    clk = FakeClock()
    t = Transport(SimPort("healthy", clock=clk.now, sleep=clk.sleep, bus="can"), clock=clk.now)
    frames = [e for e in t.monitor("ATMA", 1.0, can=True) if e.kind == "frame"]
    assert 70 <= len(frames) <= 80
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_simulator.py -q`
Expected: FAIL (`unexpected keyword argument 'bus'`).

- [ ] **Step 3: Implement**

In `SimPort.__init__` change the signature and add the state (keep the existing body):

```python
    def __init__(self, scenario: str = "rich", clock: Callable[[], float] = time.monotonic, seed: int = 7,
                 bus: str | None = None, sleep: Callable[[float], None] = time.sleep):
        if scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        if bus is not None and bus not in BUSES:
            raise ValueError(f"bus must be one of {tuple(BUSES)}")
        ...  # existing lines unchanged
        self.bus, self._sleep = bus, sleep
        self._monitoring, self._mon_last = False, 0.0
```

Add at module level near `SCENARIOS`:

```python
# made-up broadcast traffic for `listen --port sim` (ids, rates and payloads are invented; no VIN)
BUSES = {"can": (("0C9", 0.02), ("1F5", 0.05), ("3B4", 0.2)), "j1850": (("88 FE 10", 0.1), ("8A FE 40", 0.5))}
```

In `write()`, before the final `else:` branch add:

```python
        elif cmd == "ATDPN" and self.bus:  # opt-in, so existing simulator runs keep their protocol answers
            self._pending = ("A6" if self.bus == "can" else "A2") + "\r"
        elif cmd in ("ATMA", "STMA"):
            self._monitoring, self._mon_last, self._pending = True, self._clock(), ""
```

Add methods after `read_until_prompt`:

```python
    def read_available(self, timeout: float) -> str:
        if not self._monitoring:
            return ""
        lines = self._broadcast()
        if not lines:
            self._sleep(min(timeout, 0.02))
            lines = self._broadcast()
        return "".join(ln + "\r" for ln in lines)

    def interrupt(self) -> None:
        if self._monitoring:
            self._monitoring, self._pending = False, "STOPPED\r"

    def _broadcast(self) -> list[str]:
        now, lines = self._clock(), []
        for key, period in BUSES[self.bus or "can"]:
            first, last = int((self._mon_last - self._t0) / period + 1e-9), int((now - self._t0) / period + 1e-9)
            lines += [self._frame(key, k) for k in range(first + 1, last + 1)]
        self._mon_last = now
        return lines

    def _frame(self, key: str, k: int) -> str:
        rpm = int(self._rpm * 4) & 0xFFFF
        data = {"0C9": [rpm >> 8, rpm & 0xFF, k & 0x0F, 0, 0, 0, 0, 0], "1F5": [0] * 7 + [k & 0x0F], "3B4": [0x20, 0, 0, 0],
                "88 FE 10": [0x0B, rpm >> 8, rpm & 0xFF], "8A FE 40": [0x01, 0x00]}[key]
        if self.bus == "j1850":
            head = [int(x, 16) for x in key.split()]
            data = data + [sum(head + data) & 0xFF]
        return key + " " + " ".join(f"{b:02X}" for b in data)
```

- [ ] **Step 4: Run the simulator tests, then the full suite**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_simulator.py -q` and then `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q` (the console hub and MCP tools run on `SimPort`; they must not change)
Expected: PASS. If a rate count is off by one, the boundary maths in `_broadcast` is wrong: a frame is due at each multiple of the period after the monitor started, none at the start instant.

- [ ] **Step 5: Commit (branch only, if allowed)**

```bash
git add src/obd_reader/simulator.py tests/test_simulator.py
git commit -m "feat: the simulator answers ATDPN and, after ATMA/STMA, streams made-up broadcast frames (three CAN ids at 50/20/5 Hz or two J1850 ids at 10/2 Hz, invented payloads, no VIN) until interrupted"
```

---

### Task 4: Capture file writer, reader and summary

**Files:**
- Create: `src/obd_reader/bus_capture.py`
- Create: `tests/test_bus_capture.py`

**Interfaces:**
- Produces:
  - `SCHEMA = 1`
  - `class CaptureWriter(path: Path)`: opens with mode `"x"` (creating `captures/`), methods `header(**fields)`, `frame(t: float, raw: str)`, `step(t: float, step: str, phase: str)`, `gap(t: float, reason: str, seconds: float)`, `end(t: float, reason: str)`, `close()`; attributes `frames: int`, `gaps: int`, `gap_seconds: float`. Every record carries `"type"` (`header|frame|step|gap|end`) and is flushed as written.
  - `read_records(path: Path) -> Iterator[dict]`: stops quietly at a truncated or malformed line.
  - `split_frame(raw: str, id_tokens: int) -> tuple[str, list[str]] | None`
  - `id_tokens_for(protocol: str) -> int`: `ATDPN` number (`"A6"`, `"7"`...) to header tokens: CAN 29-bit (`7`, `9`) 4, J1850/ISO/KWP (`1`-`5`) 3, otherwise 1.
  - `summarize(path: Path) -> str` (Markdown) and `summarize_file(path: Path) -> Path` (writes `<capture>.md`, overwriting; returns its path).
- Header fields `listen.py` writes (Task 5): `tool_version, started, adapter, protocol, protocol_name, can, vehicle_key, snapshot_id, monitor_command, setup, script, rest_s`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bus_capture.py`:

```python
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_bus_capture.py -q`
Expected: FAIL (`ModuleNotFoundError: obd_reader.bus_capture`).

- [ ] **Step 3: Implement**

Create `src/obd_reader/bus_capture.py`:

```python
"""Bus capture files (captures/<id>.jsonl, local and gitignored: payloads may hold the VIN) and their payload-free summary."""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

SCHEMA = 1
_HEX = re.compile(r"[0-9A-F]{2,3}")


class CaptureWriter:
    """One JSON object per line, flushed as written, so a crash leaves every written line readable."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "x", encoding="utf-8")  # never overwrite a capture
        self.frames, self.gaps, self.gap_seconds = 0, 0, 0.0

    def _put(self, rec: dict) -> None:
        self._fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self._fh.flush()

    def header(self, **fields) -> None:
        self._put({"type": "header", "schema": SCHEMA, **fields})

    def frame(self, t: float, raw: str) -> None:
        self.frames += 1
        self._put({"type": "frame", "t": round(t, 4), "raw": raw})

    def step(self, t: float, step: str, phase: str) -> None:
        self._put({"type": "step", "t": round(t, 4), "step": step, "phase": phase})

    def gap(self, t: float, reason: str, seconds: float) -> None:
        self.gaps, self.gap_seconds = self.gaps + 1, self.gap_seconds + seconds
        self._put({"type": "gap", "t": round(t, 4), "gap": reason, "seconds": round(seconds, 4)})

    def end(self, t: float, reason: str) -> None:
        self._put({"type": "end", "t": round(t, 4), "reason": reason, "frames": self.frames, "gaps": self.gaps,
                   "gap_seconds": round(self.gap_seconds, 4)})

    def close(self) -> None:
        self._fh.close()


def read_records(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                return  # a truncated last line (the run died mid-write)
            if not isinstance(rec, dict):
                return
            yield rec


def id_tokens_for(protocol: str) -> int:
    """How many leading tokens of a headers-on line are the message id, from the ATDPN protocol number."""
    num = str(protocol).upper().lstrip("A")
    return 4 if num in ("7", "9") else 3 if num in ("1", "2", "3", "4", "5") else 1


def split_frame(raw: str, id_tokens: int) -> tuple[str, list[str]] | None:
    toks = raw.split()
    if not toks or not all(_HEX.fullmatch(t) for t in toks):
        return None
    n = 1 if len(toks[0]) == 3 else id_tokens  # a 3-digit first token is an 11-bit CAN id
    return (" ".join(toks[:n]), toks[n:]) if len(toks) > n else None


def summarize(path: Path) -> str:
    path = Path(path)
    recs = list(read_records(path))
    head = next((r for r in recs if r.get("type") == "header"), {})
    end = next((r for r in recs if r.get("type") == "end"), None)
    n_id = id_tokens_for(head.get("protocol", ""))
    windows, opened = [], {}
    for r in recs:
        if r.get("type") == "step":
            if r["phase"] == "start":
                opened[r["step"]] = r["t"]
            elif r["step"] in opened:
                windows.append((r["step"], opened.pop(r["step"]), r["t"]))
    frames, other, last_t = defaultdict(list), 0, 0.0
    for r in recs:
        last_t = max(last_t, r.get("t", 0.0))
        if r.get("type") == "frame":
            sf = split_frame(r["raw"], n_id)
            if sf:
                frames[sf[0]].append((r["t"], sf[1]))
            else:
                other += 1
    gaps = [r for r in recs if r.get("type") == "gap"]
    out = [f"# Bus capture {path.stem}", "",
           f"- protocol: {head.get('protocol_name') or head.get('protocol') or 'unknown'}; monitor: {head.get('monitor_command', '?')}",
           f"- vehicle key: {head.get('vehicle_key') or 'not read'}",
           f"- ended: {end['reason'] if end else 'no end record (the run stopped early)'}; {last_t:.1f} s",
           f"- frames: {sum(len(v) for v in frames.values())}; other lines: {other}; gaps: {len(gaps)} ({sum(g['seconds'] for g in gaps):.1f} s)", ""]
    if not frames:
        return "\n".join(out + ["No frames were received: the bus was silent at this port, or the adapter did not pass them on.", ""])
    out += ["| ID | frames | Hz | bytes | changing bytes | most change in |", "|---|---|---|---|---|---|"]
    for fid in sorted(frames):
        seq = frames[fid]
        length = Counter(len(d) for _, d in seq).most_common(1)[0][0]
        first = seq[0][1]
        changing = sum(1 for i in range(max(len(d) for _, d in seq)) if any(i < len(d) and (i >= len(first) or d[i] != first[i]) for _, d in seq))
        per_step = Counter()
        for (_, prev), (t, cur) in zip(seq, seq[1:]):
            if cur != prev:
                per_step.update(s for s, a, b in windows if a <= t <= b)
        top = ", ".join(s for s, _ in per_step.most_common(3)) or "—"
        hz = len(seq) / last_t if last_t > 0 else 0.0
        out.append(f"| {fid} | {len(seq)} | {hz:.1f} | {length} | {changing} | {top} |")
    return "\n".join(out + [""])


def summarize_file(path: Path) -> Path:
    md = Path(path).with_suffix(".md")
    md.write_text(summarize(path), encoding="utf-8")
    return md
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_bus_capture.py -q`
Expected: PASS. Check the 1F5 row by hand if it fails: 100 frames over `last_t` = 10.0 s (the `end` record's `t`) is 10.0 Hz, data length 2, only the second byte changes.

- [ ] **Step 5: Commit (branch only, if allowed)**

```bash
git add src/obd_reader/bus_capture.py tests/test_bus_capture.py
git commit -m "feat: bus capture files: a JSON Lines writer (header, frame, step, gap and end records, flushed, never overwritten), a reader that stops at a truncated line, and a Markdown summary per message id (frames, Hz, length, changing byte positions, the steps where it changed most) with no payload bytes"
```

---

### Task 5: The guided script and `listen()`

**Files:**
- Create: `src/obd_reader/listen.py`
- Create: `tests/test_listen.py`

**Interfaces:**
- Consumes: `Transport.monitor`, `Transport.now`, `MonitorEvent` (Task 2); `CaptureWriter`, `summarize` (Task 4); `SimPort(bus=...)` (Task 3); `scan(...)` from `obd_reader.scanner`; `Session.connection`, `Session.store.save`; `vehicle_key` from `obd_reader.vehicle`; `__version__` from `obd_reader`.
- Produces:
  - `@dataclass(frozen=True) class Step: id: str; prompt: str; window_s: float = 10.0`
  - `REST_S = 5.0`, `SCRIPT: tuple[Step, ...]` (14 steps, baseline 30 s), `script_seconds(script) -> float`
  - `class Keys` (context manager; `Keys(stream=sys.stdin)`; `poll() -> str | None`, lower-case single key or None; no-op when the stream is not a terminal)
  - `run_capture(events, writer, script, keys, out, start) -> str` returns the end reason `finished | quit | time_limit | error | interrupted`; always writes the `end` record and closes `events`; re-raises errors and `KeyboardInterrupt`.
  - `listen(session, *, label, protocol, seconds, out, keys, now=None) -> Path` (the capture path). `seconds=None` runs the script; a number runs a plain listen with no script.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_listen.py`:

```python
import io
import json

import pytest

from obd_reader.bus_capture import CaptureWriter, read_records
from obd_reader.listen import REST_S, SCRIPT, Keys, Step, listen, run_capture, script_seconds
from obd_reader.session import Config, Session
from obd_reader.simulator import SIM_VIN, SimPort
from obd_reader.transport import MonitorEvent
from obd_reader.vehicle import vehicle_key
from obd_reader.vin import find_vins

TWO = (Step("a", "Do A", 2.0), Step("b", "Do B", 2.0))  # a: 0-2, rest to 7, b: 7-9, rest to 14


class FakeKeys:
    def __init__(self, at=None):
        self.at, self.t = dict(at or {}), None

    def poll(self):
        return self.at.pop(self.t, None)


def feed(ts, keys=None, extra=()):
    """Idle events at the given times (plus extra events), with keys keyed by event time."""
    closed = []

    def gen():
        try:
            for t in ts:
                if keys is not None:
                    keys.t = t
                yield MonitorEvent("idle", t)
                for e in extra:
                    if e.t == t:
                        yield e
        finally:
            closed.append(True)
    return gen(), closed


def capture(tmp_path, events, script=TWO, keys=None, start=0.0):
    out, w = [], CaptureWriter(tmp_path / "c.jsonl")
    reason = run_capture(events, w, script, keys or FakeKeys(), out.append, start)
    w.close()
    return reason, list(read_records(w.path)), out


def steps(recs):
    return [(r["step"], r["phase"], r["t"]) for r in recs if r["type"] == "step"]


def test_the_script_runs_its_windows_and_rests_on_schedule(tmp_path):
    ev, closed = feed([x / 2 for x in range(0, 40)])
    reason, recs, out = capture(tmp_path, ev)
    assert reason == "finished" and closed == [True]
    assert steps(recs) == [("a", "start", 0.0), ("a", "end", 2.0), ("b", "start", 7.0), ("b", "end", 9.0)]
    assert recs[-1]["type"] == "end" and recs[-1]["reason"] == "finished"
    assert any("[1/2] Do A" in ln for ln in out) and any("[2/2] Do B" in ln for ln in out)


def test_s_skips_the_current_step_and_q_stops_and_keeps_the_file(tmp_path):
    keys = FakeKeys({0.5: "s", 8.0: "q"})
    ev, closed = feed([x / 2 for x in range(0, 40)], keys)
    reason, recs, _ = capture(tmp_path, ev, keys=keys)
    assert steps(recs) == [("a", "start", 0.0), ("a", "skipped", 0.5), ("b", "start", 5.5), ("b", "end", 7.5)]
    assert reason == "quit" and recs[-1]["reason"] == "quit" and closed == [True]


def test_frames_and_gaps_are_written_relative_to_the_start(tmp_path):
    extra = [MonitorEvent("frame", 101.0, "0C9 01"), MonitorEvent("gap", 101.5, "BUFFER FULL", 0.3)]
    ev, _ = feed([100 + x / 2 for x in range(0, 40)], extra=extra)
    _, recs, _ = capture(tmp_path, ev, start=100.0)
    assert {"type": "frame", "t": 1.0, "raw": "0C9 01"} in recs
    assert any(r["type"] == "gap" and r["t"] == 1.5 and r["seconds"] == 0.3 for r in recs)


def test_a_plain_listen_finishes_when_the_monitor_does(tmp_path):
    ev, _ = feed([0.0, 0.5, 1.0])
    reason, recs, _ = capture(tmp_path, ev, script=())
    assert reason == "finished" and steps(recs) == []


def test_a_script_cut_short_by_the_time_limit_says_so(tmp_path):
    ev, _ = feed([0.0, 0.5, 1.0])
    assert capture(tmp_path, ev)[0] == "time_limit"


@pytest.mark.parametrize("exc,reason", [(OSError("unplugged"), "error"), (KeyboardInterrupt(), "interrupted")])
def test_an_error_or_ctrl_c_still_ends_the_file_and_stops_the_monitor(tmp_path, exc, reason):
    closed = []

    def gen():
        try:
            yield MonitorEvent("frame", 0.1, "0C9 01")
            raise exc
        finally:
            closed.append(True)
    w = CaptureWriter(tmp_path / "c.jsonl")
    with pytest.raises(type(exc)):
        run_capture(gen(), w, TWO, FakeKeys(), lambda s: None, 0.0)
    w.close()
    recs = list(read_records(w.path))
    assert recs[-1]["type"] == "end" and recs[-1]["reason"] == reason and recs[-1]["frames"] == 1 and closed == [True]


def test_keys_on_a_stream_that_is_not_a_terminal_never_fire():
    with Keys(stream=io.StringIO("sq")) as keys:
        assert keys.poll() is None


def test_the_script_is_the_specified_one():
    assert SCRIPT[0] == Step("baseline", SCRIPT[0].prompt, 30.0) and len(SCRIPT) == 14
    assert all(s.window_s == 10.0 for s in SCRIPT[1:]) and REST_S == 5.0
    assert script_seconds(SCRIPT) == 30 + 13 * 10 + 14 * 5


def test_listen_on_the_simulator_scans_sets_up_and_captures(tmp_path):
    session = Session(Config(port="sim", home=tmp_path, timeout=1.0), port_factory=lambda: SimPort("healthy", bus="can"))
    out = []
    path = listen(session, label="t", protocol="0", seconds=1.0, out=out.append, keys=FakeKeys())
    recs = list(read_records(path))
    head, end = recs[0], recs[-1]
    assert path.parent == tmp_path / "captures" and path.suffix == ".jsonl"
    assert head["type"] == "header" and head["monitor_command"] == "ATMA" and head["can"] is True and head["protocol"] == "A6"
    assert head["vehicle_key"] == vehicle_key(SIM_VIN) and head["script"] == []
    assert [s["tx"] for s in head["setup"]] == ["ATH1", "ATS1", "ATAL"]
    assert (tmp_path / "snapshots" / f"{head['snapshot_id']}.json").exists()
    assert find_vins(json.dumps(head)) == [] and end["reason"] == "finished" and end["frames"] > 20
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_listen.py -q`
Expected: FAIL (`ModuleNotFoundError: obd_reader.listen`).

- [ ] **Step 3: Implement**

Create `src/obd_reader/listen.py`:

```python
"""`shadetree-ai listen`: the standard scan, then a listen-only bus capture driven by a guided action script."""
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from obd_reader import __version__
from obd_reader.bus_capture import CaptureWriter
from obd_reader.scanner import scan
from obd_reader.session import Session
from obd_reader.transport import MonitorEvent
from obd_reader.vehicle import vehicle_key


@dataclass(frozen=True)
class Step:
    id: str
    prompt: str
    window_s: float = 10.0


REST_S = 5.0  # between steps, so each action's changes stand apart
SCRIPT = (  # engine running, in Park, parking brake on; the same list for every car so captures compare
    Step("baseline", "Idle: hands off, touch nothing", 30.0),
    Step("brake", "Press the brake pedal 3 times"),
    Step("throttle", "Blip the throttle 3 times (in Park)"),
    Step("steering", "Turn the steering wheel lock to lock"),
    Step("signal_left", "Left turn signal on, then off"),
    Step("signal_right", "Right turn signal on, then off"),
    Step("hazards", "Hazard lights on, then off"),
    Step("headlights", "Headlights on, then off"),
    Step("high_beams", "High beams on, then off"),
    Step("driver_door", "Open the driver door, then close it"),
    Step("windows", "Driver window down a little, then up"),
    Step("hvac_fan", "HVAC fan to high, then back"),
    Step("locks", "Lock the doors, then unlock them"),
    Step("shifter", "Foot on the brake: shift P-R-N-D, then back to P"),
)


def script_seconds(script) -> float:
    return sum(s.window_s + REST_S for s in script)


class Keys:
    """Single key presses without Enter, when stdin is a terminal; otherwise poll() is always None."""

    def __init__(self, stream=None):
        self._stream, self._restore, self._win = stream if stream is not None else sys.stdin, None, False

    def __enter__(self) -> "Keys":
        try:
            if not self._stream.isatty():
                return self
        except Exception:  # pytest's captured stdin and closed streams: no keys
            return self
        try:
            import termios
            import tty

            fd = self._stream.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            self._restore = lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except ImportError:  # Windows
            self._win = True
        return self

    def poll(self) -> str | None:
        if self._win:
            import msvcrt

            return msvcrt.getwch().lower() if msvcrt.kbhit() else None
        if self._restore is None:
            return None
        import select

        if select.select([self._stream], [], [], 0)[0]:
            return self._stream.read(1).lower()
        return None

    def __exit__(self, *exc) -> None:
        if self._restore is not None:
            self._restore()


def run_capture(events: Iterator[MonitorEvent], writer: CaptureWriter, script, keys, out: Callable[[str], None], start: float) -> str:
    """Write the monitor's events and the script's step records; `start` is the transport time the capture counts from."""
    idx, in_window, deadline, t, ids, last_status = 0, False, 0.0, 0.0, set(), 0.0
    reason = "finished" if not script else "time_limit"

    def begin(i: int, at: float) -> float:
        writer.step(at, script[i].id, "start")
        out(f"[{i + 1}/{len(script)}] {script[i].prompt} ({script[i].window_s:g} s)")
        return at + script[i].window_s

    try:
        if script:
            deadline, in_window = begin(0, 0.0), True
        for ev in events:
            t = ev.t - start
            key = keys.poll()
            if key == "q":
                reason = "quit"
                break
            if script:
                if key == "s" and in_window:
                    writer.step(t, script[idx].id, "skipped")
                    in_window, deadline = False, t + REST_S
                while t >= deadline:
                    if in_window:
                        writer.step(deadline, script[idx].id, "end")
                        in_window, deadline = False, deadline + REST_S
                    else:
                        idx += 1
                        if idx >= len(script):
                            break
                        deadline, in_window = begin(idx, deadline), True
                if idx >= len(script):
                    reason = "finished"
                    break
            if ev.kind == "frame":
                writer.frame(t, ev.text)
                ids.add(ev.text.split(" ", 1)[0])
            elif ev.kind == "gap":
                writer.gap(t, ev.text, ev.seconds)
            if t - last_status >= 5.0:
                last_status = t
                out(f"  {t:5.0f} s · {writer.frames} frames · {len(ids)} ids · {writer.gaps} gaps")
    except KeyboardInterrupt:
        writer.end(t, "interrupted")
        raise
    except Exception:
        writer.end(t, "error")
        raise
    finally:
        events.close()  # stops the adapter and restores ATCAF1 (Transport.monitor's finally)
    writer.end(t, reason)
    return reason


def listen(session: Session, *, label: str, protocol: str, seconds: float | None, out: Callable[[str], None], keys,
           now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    sid = f"{now:%Y-%m-%dT%H-%M-%SZ}-{label}"
    script = () if seconds else SCRIPT
    path = Path(session.config.home) / "captures" / f"{sid}.jsonl"
    with session.connection("listen", protocol) as t:
        transcript = t.transcript_path.relative_to(session.config.home).as_posix() if t.transcript_path else None
        snap = scan(t, snapshot_id=sid, captured_at=now, kind="live", protocol=protocol, transcript=transcript, mode06=True)
        session.store.save(snap)
        dpn = (t.send("ATDPN") or [""])[0].strip().upper()
        can = dpn.lstrip("A") in ("6", "7", "8", "9")
        setup = [{"tx": c, "rx": t.send(c)} for c in ("ATH1", "ATS1", "ATAL")]
        adapter = snap.source.adapter
        mon = "STMA" if adapter.genuine_stn else "ATMA"
        events = t.monitor(mon, seconds or script_seconds(script) + 2.0, can=can)  # SilentModeUnsupported raises here, before any file
        writer = CaptureWriter(path)
        try:
            writer.header(tool_version=__version__, started=now.isoformat(timespec="seconds"),
                          adapter={"ati": adapter.ati, "sti": adapter.sti}, protocol=dpn,
                          protocol_name=snap.protocol.name if snap.protocol else None, can=can,
                          vehicle_key=vehicle_key(snap.vehicle.vin) if snap.vehicle else None, snapshot_id=sid,
                          monitor_command=mon, setup=setup,
                          script=[{"id": s.id, "prompt": s.prompt, "window_s": s.window_s} for s in script], rest_s=REST_S)
            out(f"listening ({mon}, {'CAN' if can else 'protocol ' + dpn}): s skips a step, q stops")
            run_capture(events, writer, script, keys, out, t.now)
        finally:
            writer.close()
    return path
```

Before running, check two facts against the code and adjust `listen()` if they differ: that `snap.protocol` and `snap.vehicle` can be `None` (the guards above assume they can), and that `snap.source.adapter` is always set after `scan`. Keep the guards if unsure.

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_listen.py -q`
Expected: PASS. The simulator test runs about 1 s of real time.

- [ ] **Step 5: Commit (branch only, if allowed)**

```bash
git add src/obd_reader/listen.py tests/test_listen.py
git commit -m "feat: listen(): the probe's standard scan, then ATH1/ATS1/ATAL and a listen-only monitor (STMA on an STN, else ATMA) written to captures/<id>.jsonl, driven by a 14-step guided script (30 s baseline, 10 s windows, 5 s rests; s skips, q stops) or a plain timed listen; an error or Ctrl-C still writes the end record and stops the adapter"
```

---

### Task 6: CLI, gitignore, VIN guard and docs

**Files:**
- Modify: `src/obd_reader/__main__.py` (new `listen` subparser and `_listen` handler, next to `probe`)
- Modify: `.gitignore` (add `captures/` after `probes/`)
- Modify: `tests/test_no_real_vins.py` (`test_capture_directories_are_gitignored`: add `"captures/x.jsonl"` to the tuple)
- Create: `tests/test_listen_cli.py`
- Modify: `docs/design.md` (a **Bus listen** paragraph after the quirks-file paragraph, and the status line's built list)
- Modify: `CLAUDE.md` (the read-only decision line)

**Interfaces:**
- Consumes: `listen`, `Keys` (Task 5); `summarize_file` (Task 4); `SimPort` (Task 3); `_LABEL_RE` from `obd_reader.capture`.
- Produces: `shadetree-ai listen --port DEV|sim [--protocol N] [--baud B] [--timeout S] [--seconds N] [--label L] [--out-dir D]` and `shadetree-ai listen --summarize CAPTURE.jsonl`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_listen_cli.py`:

```python
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


def test_captures_stay_gitignored():
    assert subprocess.run(["git", "check-ignore", "-q", "captures/x.jsonl"], cwd=ROOT).returncode == 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_listen_cli.py -q`
Expected: FAIL (`invalid choice: 'listen'`).

- [ ] **Step 3: Implement the CLI**

In `src/obd_reader/__main__.py`, add the handler next to `_probe`:

```python
def _listen(args) -> int:
    from obd_reader.bus_capture import summarize_file

    if args.summarize:
        md = summarize_file(args.summarize)
        print(md.read_text(encoding="utf-8"), end="")
        return 0
    from obd_reader.capture import _LABEL_RE
    from obd_reader.listen import Keys, listen
    from obd_reader.session import Config, Session

    if not _LABEL_RE.fullmatch(args.label):
        raise ValueError("label must be 1-40 chars of [a-z0-9-]")
    if args.seconds is not None and not 0 < args.seconds <= 900:
        raise ValueError("--seconds must be in (0, 900]")
    if args.port == "sim":
        from obd_reader.simulator import SimPort

        session = Session(Config(port="sim", home=args.out_dir, timeout=1.0), port_factory=lambda: SimPort("healthy", bus="can"))
    else:
        session = Session(Config(port=args.port, baud=args.baud, timeout=args.timeout, home=args.out_dir))
    try:
        with Keys() as keys:
            path = listen(session, label=args.label, protocol=args.protocol or "0", seconds=args.seconds,
                          out=lambda s: print(s, flush=True), keys=keys)
    except KeyboardInterrupt:
        caps = sorted((Path(args.out_dir) / "captures").glob(f"*-{args.label}.jsonl"))
        print(f"stopped: the partial capture is {caps[-1]}" if caps else "stopped before the capture began")
        return 130
    md = summarize_file(path)
    print(md.read_text(encoding="utf-8"), end="")
    print(f"capture (raw bus data, may hold the VIN, keep local): {path}\nsummary (no payload bytes): {md}")
    return 0
```

and the subparser after the `probe` block in `build_parser()`:

```python
    ls = sub.add_parser("listen", help="listen-only bus capture with a guided action script; writes captures/<id>.jsonl (raw bus data, keep local)")
    src = ls.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="serial device or pyserial URL, or 'sim' for the simulator")
    src.add_argument("--summarize", type=Path, metavar="CAPTURE", help="print and save the summary of a capture (no adapter)")
    ls.add_argument("--protocol", default=None, help="ATSP value; default 0 = automatic search")
    ls.add_argument("--baud", type=int, default=115200)
    ls.add_argument("--timeout", type=float, default=10.0, help="seconds to wait per command")
    ls.add_argument("--seconds", type=float, default=None, help="plain listen for N seconds (max 900) instead of the guided script")
    ls.add_argument("--label", default="listen", help="short name for the capture, [a-z0-9-]")
    ls.add_argument("--out-dir", type=Path, default=Path("."), help="captures/ (and snapshots/, transcripts/) go here")
    ls.set_defaults(func=_listen)
```

Make sure `Path` is imported in `__main__.py` (it already is).

- [ ] **Step 4: Gitignore and the VIN guard**

Add `captures/` to `.gitignore` on the line after `probes/`. In `tests/test_no_real_vins.py::test_capture_directories_are_gitignored`, add `"captures/x.jsonl"` to the tuple of paths.

- [ ] **Step 5: Run the CLI tests and the guard**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_listen_cli.py tests/test_no_real_vins.py -q`
Expected: PASS. The Ctrl-C test relies on `run_capture` writing the `end` record (`"interrupted"`), whose last field is `gap_seconds`.

- [ ] **Step 6: Docs**

In `docs/design.md`, after the **Quirks file** paragraph, add:

```markdown
**Bus listen** (`listen.py`, `bus_capture.py`; spec `docs/superpowers/specs/2026-10-08-bus-listen-design.md`): `shadetree-ai listen --port DEV` runs the probe's standard scan (saved as a private snapshot), sends `ATH1`, `ATS1`, `ATAL`, then a listen-only monitor (`STMA` on an STN, else `ATMA`) through `Transport.monitor()`: on CAN it first requires `ATCSM1` (anything but OK stops it) and runs in raw mode (`ATCAF0`, sent only here; while it is on, the transport and `SerialPort` refuse every non-AT/ST command; `ATCAF1` is restored in a `finally`). Nothing is transmitted between the monitor command and the returning prompt; `BUFFER FULL` and other stops become timed gaps and the monitor restarts; at most 900 s. A guided script (30 s baseline, 13 actions of 10 s with 5 s rests, engine running in Park; `s` skips, `q` stops) marks each action's window; `--seconds N` is a plain listen. The capture is `captures/<id>.jsonl` (local, gitignored: header, frame, step, gap and end records, raw adapter lines verbatim); `captures/<id>.md` and `listen --summarize` give per-ID frames, Hz, length, changing byte positions and the steps where it changed most, never payload bytes. `--port sim` streams made-up CAN or J1850 frames. Decoding and mapping are sub-project 2 (not built). Unverified on hardware.
```

and add "the listen-only bus capture (`listen`)" to the status line's built list. In `CLAUDE.md`, change the read-only decision's "Allowed:" sentence to end with: `... (+ explicit AT/STN identify list; 05/06 approved 2026-09-30; listen-only monitor ATMA/STMA with ATCSM1 and ATAL approved 2026-10-08, ATCAF0 only inside Transport.monitor()).`

- [ ] **Step 7: Full suite**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q`
Expected: PASS (the previous count plus the new tests).

- [ ] **Step 8: Commit (branch only, if allowed)**

```bash
git add src/obd_reader/__main__.py .gitignore tests/test_no_real_vins.py tests/test_listen_cli.py docs/design.md CLAUDE.md
git commit -m "feat: shadetree-ai listen (--port DEV or sim, --seconds for a plain listen, --summarize for an existing capture); captures/ is gitignored and guarded; Ctrl-C reports the partial capture; design.md and CLAUDE.md record the listen-only allowlist decision"
```

---

## Hardware (Neil, after the branch is reviewed)

0. Bench, OBDLink EX, no car (~10 min): `shadetree-ai listen --port /dev/serial/by-id/<adapter> --seconds 10 --label bench`. Expect either `SilentModeUnsupported` (then STN silent monitoring needs a decision before CAN listening) or a capture with no frames. Keep the transcript; it has no VIN and can become a fixture.
1. GMC truck, Ridgeline, 4Runner (~10 min each): `shadetree-ai listen --port ... --label <car>`, follow the prompts, then read the printed summary.
