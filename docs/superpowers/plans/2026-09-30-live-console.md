# Live Console (three layouts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, read-only web console that shows live vehicle data as it is sampled, in three layouts (A Cockpit, B Scope, C Guided test), fed by one shared sampler that Claude's tools can also read.

**Architecture:** A `LiveHub` background thread owns the adapter (through the existing `Session` lock and gated `Transport`), samples a fixed set of Mode 01 PIDs into ring buffers, and exposes `state(after)`. A stdlib `http.server` `ConsoleServer` serves one static page plus a small token-protected JSON API (`/api/state`, `/api/start`, `/api/stop`, `/api/save`, `/api/sim`); the page polls every 400 ms (the same pattern MCP Apps use, so the front end can later be wrapped as an MCP App). A `SimPort` (a pretend car behind the same `Port` interface) powers `console --demo` and the tests. Two new MCP tools, `open_console` and `console_data`, let Claude start the console and read the same numbers the page shows.

**Tech Stack:** Python 3.11+ stdlib (`http.server`, `threading`), existing `obd_reader` modules, `mcp` 2.x for the tools, vanilla JS/canvas/SVG in one HTML file (no external assets).

**Spec:** `docs/design.md` (§7 tools, new §7b console). Visual reference: `docs/mocks/console-mock.html` (published: https://staging.voygent.ai/mocks/shadetree-ai-console-mock.html). Neil approved all three layouts on 2026-09-30 ("Build all 3").

## Global Constraints

- **Read-only.** The console can only start/stop sampling and save a run file. Sampling uses `Transport.send("01PP")` for validated PIDs (`live.validate_pids`) through `Session.connection`; nothing new is added to the allowlist. No API route accepts a command string.
- **Local by default.** The server binds `127.0.0.1`. Binding any other address requires the explicit flag `--allow-lan` and prints a warning. Every request needs the random token (`?t=` query or `X-Console-Token` header, compared with `hmac.compare_digest`) AND an allowed `Host` header (DNS-rebinding defence); POSTs with an `Origin` header must match the page's own origin. No CORS headers are ever sent. Request bodies are capped at 4096 bytes. The server never logs request lines (they contain the token).
- **One adapter owner.** While the hub samples it holds the `Session` lock; other live tools get `AdapterBusy` with a message that points to `console_data`.
- **Limits:** ≤8 PIDs, sampling rate 0.1–10 Hz, one run ≤1800 s (default 600 s), ring buffer 600 sweeps, silent-bus stop after 3 sweeps with no data, `state()` returns at most 600 sweeps per call.
- **No new dependencies.** The page is one self-contained HTML file with no external URLs; a test asserts that.
- **Tool set:** after Task 6 the reviewed MCP tool list has 17 tools (the 15 existing plus `open_console`, `console_data`); `tests/conftest.py::REVIEWED_TOOLS` is the literal source of truth and is updated in Task 6.
- **Repo rules:** work in a worktree; commit per batch (Neil's standing rule: A = Tasks 1–2, B = Tasks 3–4, C = Tasks 5–6, then review fixes); merge to `main` and push only when Neil says so; never touch hardware without asking (Task 7 hardware step); real runs/snapshots (`runs/`, `snapshots/`, `transcripts/`) stay gitignored.

## Review Focus

Failure modes the spec implies but happy-path tests would miss; each has a test in the owning task:

1. Another web page in the browser calling the console API (CSRF / DNS rebinding): wrong token, wrong `Host`, and foreign `Origin` must all be refused, and refusals must not leak state. → Task 4.
2. `start` request with smuggled PIDs (`"0C\r04"`, `"ZZ"`, 9 PIDs), `hz` 0 or 1e-9 or NaN, `seconds` huge or NaN, bodies that are not JSON, huge, or the wrong content type. → Task 4 (server) and Task 3 (hub).
3. The sampler thread dying or hanging (adapter unplugged, silent bus, `AdapterNotReady`): the hub must end in `status: "error"` or `"stopped"` with a readable message, release the adapter lock, and never leave a zombie thread holding the port. → Task 3.
4. Client reconnect and multiple viewers: two browser tabs polling with different `after` values must both get correct increments; a page opened mid-run must see history; a new run resets `seq` and clients must reset their buffers. → Tasks 3 and 5.
5. `console_data` and Claude's other live tools while the hub is running: no interleaved bytes on the port, clear message, and `console_data` values equal what `/api/state` reports. → Task 6.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/obd_reader/live.py` (modify) | Add `read_pid_value`, reuse it in `sample` |
| `src/obd_reader/simulator.py` (new) | `SimPort`: pretend car (healthy / rich / lean, rev) |
| `src/obd_reader/hub.py` (new) | `LiveHub`, `HubBusy` |
| `src/obd_reader/console.py` (new) | `ConsoleServer`, `ConsoleService` (shared by CLI and MCP tools) |
| `src/obd_reader/web/__init__.py`, `src/obd_reader/web/console.html` (new) | The single-file front end (three layouts), shipped as package data |
| `src/obd_reader/session.py` (modify) | Clearer `AdapterBusy` message |
| `src/obd_reader/__main__.py` (modify) | `console` subcommand |
| `src/obd_reader/tools.py` (modify) | `open_console`, `console_data`; tool sets |
| `pyproject.toml` (modify) | Package data for `web/console.html` |
| `tests/test_simulator.py`, `test_hub.py`, `test_console.py`, `test_console_page.py`, `test_console_tools.py` (new) | Tests |
| `docs/design.md`, `README.md` (modify) | Document the console |

---

### Task 1: `read_pid_value` (shared single-PID read)

**Files:**
- Modify: `src/obd_reader/live.py`
- Test: `tests/test_live.py`

**Interfaces:**
- Produces: `live.read_pid_value(transport: Transport, pid: str) -> float | int | None` — sends `01<pid>` (pid already validated, upper-case, in `PIDS`), returns the decoded value of the first payload whose PID byte matches, else `None`. `live.sample` calls it.

- [ ] **Step 1: Write the failing test** — append to `tests/test_live.py`:

```python
def test_read_pid_value_decodes_or_returns_none():
    from obd_reader.live import read_pid_value

    port = ScriptedPort({"0C": "1AF8"})
    t = Transport(port)
    assert read_pid_value(t, "0C") == 1726.0
    assert read_pid_value(t, "0D") is None  # ECU answers NO DATA
    assert port.writes == ["010C", "010D"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_live.py -q --tb=line -p no:cacheprovider 2>&1 | grep -E "ImportError|passed|failed" | head -3`
Expected: `ImportError: cannot import name 'read_pid_value'`.

- [ ] **Step 3: Implement** — in `src/obd_reader/live.py` add above `sample`:

```python
def read_pid_value(transport: Transport, pid: str) -> float | int | None:
    """One Mode 01 request for an already-validated PID; None if no ECU answered it."""
    d = PIDS[pid]
    for payload in parse_all(transport.send(f"01{pid}"), 0x41):
        if len(payload) >= 2 + d.nbytes and payload[1] == int(pid, 16):
            return d.decode(payload[2 : 2 + d.nbytes])
    return None
```

and replace the inner loop in `sample` (the `for p in pids:` body that builds `d`, loops over `parse_all(...)` and appends) with:

```python
        for p in pids:
            v = read_pid_value(transport, p)
            if v is not None:
                series[p].samples.append((round(t, 3), v))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider 2>&1 | tail -3`
Expected: the whole suite passes (the existing sampler tests cover the refactor).

---

### Task 2: The pretend car (`SimPort`)

**Files:**
- Create: `src/obd_reader/simulator.py`
- Test: `tests/test_simulator.py`

**Interfaces:**
- Consumes: `pids.decode_pid` (in tests).
- Produces: `simulator.SCENARIOS = ("healthy", "rich", "lean")`; `simulator.SimPort(scenario="rich", clock=time.monotonic, seed=7)` implementing the `Port` protocol (`write(bytes)`, `read_until_prompt(timeout) -> str`, `close()`), with public `scenario: str`, `rev: bool`, and `set_scenario(name)` (raises `ValueError` for an unknown name). It answers `01<PID>` for `0C 05 06 07 08 09 10 42`, `ATI` → `SIM327 (simulated)`, `STI` → `?`, `ATDP` → `SIMULATED (no car)`, other `AT*`/`ST*` → `OK`, unsupported `01xx` → `NO DATA`. Model time advances only when `010C` is requested (once per sweep), using `clock`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_simulator.py`:

```python
import pytest

from obd_reader.pids import decode_pid
from obd_reader.simulator import SCENARIOS, SimPort
from obd_reader.transport import Transport

from conftest import FakeClock

PIDS8 = ["0C", "05", "06", "07", "08", "09", "10", "42"]


def sweep(sim, t):
    vals = {}
    for pid in PIDS8:
        lines = t.send(f"01{pid}")
        raw = bytes.fromhex(lines[0].replace(" ", ""))
        assert raw[0] == 0x41 and raw[1] == int(pid, 16)
        vals[pid] = decode_pid(pid, raw[2:]).value
    return vals


def run(scenario, seconds=30, rev=False):
    clk = FakeClock()
    sim = SimPort(scenario, clock=clk.now)
    sim.rev = rev
    t = Transport(sim)
    out = []
    for _ in range(int(seconds / 0.4)):
        clk.sleep(0.4)
        out.append(sweep(sim, t))
    return out


def test_every_scenario_stays_in_physical_ranges():
    for sc in SCENARIOS:
        for rev in (False, True):
            for v in run(sc, rev=rev):
                assert 400 <= v["0C"] <= 3200 and 20 <= v["05"] <= 110
                for p in ("06", "07", "08", "09"):
                    assert -30 <= v[p] <= 30
                assert 0 <= v["10"] <= 80 and 11 <= v["42"] <= 15


def test_rich_scenario_reads_a_cold_coolant_and_negative_trims_at_idle_and_at_2500():
    idle, rev = run("rich")[-10:], run("rich", rev=True)[-10:]
    for rows in (idle, rev):
        assert all(r["05"] < 50 for r in rows)
        assert all(r["07"] < -15 and r["09"] < -15 for r in rows)


def test_lean_scenario_trims_fade_as_airflow_rises():
    idle, rev = run("lean")[-10:], run("lean", rev=True)[-10:]
    assert all(r["07"] > 10 for r in idle) and all(r["07"] < 8 for r in rev)


def test_healthy_scenario_has_small_trims_and_a_warm_engine():
    rows = run("healthy", seconds=60)[-10:]
    assert all(abs(r["07"]) < 5 and abs(r["09"]) < 5 for r in rows) and all(r["05"] > 80 for r in rows)


def test_rev_moves_engine_speed_to_about_2500():
    assert 2300 < run("healthy", rev=True)[-1]["0C"] < 2700
    assert run("healthy")[-1]["0C"] < 900


def test_non_pid_commands_and_unsupported_pids():
    t = Transport(SimPort())
    assert t.send("ATE0") == ["OK"]
    assert t.send("ATDP") == ["SIMULATED (no car)"]
    assert t.send("STI") == ["?"]
    assert t.send("0111") == ["NO DATA"]


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError):
        SimPort("bogus")
    with pytest.raises(ValueError):
        SimPort().set_scenario("bogus")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_simulator.py -q --tb=line -p no:cacheprovider 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.simulator'`.

- [ ] **Step 3: Implement** — create `src/obd_reader/simulator.py`:

```python
"""A pretend car: a Port that answers Mode 01 PID reads, for `console --demo` and tests.

It sits behind the same gated Transport as a real adapter, so demo runs exercise the
real code path. Numbers follow the Suburban mock: 'rich' has a coolant sensor that
reads cold and trims near -20 %, 'lean' has a vacuum leak whose trims fade as airflow
rises, 'healthy' is unremarkable.
"""
import math
import random
import time
from typing import Callable

SCENARIOS = ("healthy", "rich", "lean")


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _u16(n: int) -> bytes:
    return _clamp(n, 0, 65535).to_bytes(2, "big")


def _trim(pct: float) -> bytes:
    return bytes([_clamp(round(pct * 128 / 100 + 128), 0, 255)])


# raw data bytes for each supported PID, given the model value (inverse of pids.py decoders)
ENCODERS: dict[str, Callable[[float], bytes]] = {
    "0C": lambda v: _u16(round(v * 4)),
    "05": lambda v: bytes([_clamp(round(v + 40), 0, 255)]),
    "06": _trim, "07": _trim, "08": _trim, "09": _trim,
    "10": lambda v: _u16(round(v * 100)),
    "42": lambda v: _u16(round(v * 1000)),
}
_KEY = {"0C": "rpm", "05": "ect", "06": "s1", "07": "l1", "08": "s2", "09": "l2", "10": "maf", "42": "volts"}


class SimPort:
    def __init__(self, scenario: str = "rich", clock: Callable[[], float] = time.monotonic, seed: int = 7):
        if scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        self.scenario, self.rev = scenario, False
        self._clock, self._rng = clock, random.Random(seed)
        self._t0 = self._last = clock()
        self._rpm, self._ect = 700.0, 88.0
        self._values: dict[str, float] = {}
        self._pending = ""
        self._advance()

    def set_scenario(self, name: str) -> None:
        if name not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        self.scenario = name

    def _rnd(self) -> float:
        return self._rng.random() - 0.5

    def _advance(self) -> None:
        now = self._clock()
        dt = min(2.0, max(0.05, now - self._last))
        self._last, t = now, now - self._t0
        k = min(1.0, dt / 0.4)
        target = 2500.0 if self.rev else 700 + (60 * math.sin(t * 2.1) if self.scenario == "lean" else 25 * math.sin(t * 1.3))
        self._rpm += (target - self._rpm) * 0.38 * k + self._rnd() * (30 if self.rev else 14)
        load = max(0.0, min(1.0, (self._rpm - 700) / 1800))
        if self.scenario == "rich":
            self._ect += (41 - self._ect) * 0.2 * k + self._rnd() * 0.3
        else:
            self._ect += (91 - self._ect) * 0.02 * k + self._rnd() * 0.2
        if self.scenario == "rich":
            l1, l2 = -21 + self._rnd() * 0.5, -19 + self._rnd() * 0.5
            s1, s2 = -12 + 4 * math.sin(t * 1.7) + self._rnd(), -10 + 4 * math.sin(t * 1.5 + 1) + self._rnd()
        elif self.scenario == "lean":
            f = 15 * (1 - load) + 2
            l1, l2 = f + self._rnd() * 0.5, f - 1 + self._rnd() * 0.5
            s1, s2 = 3 + 4 * math.sin(t * 1.9) + self._rnd(), 3 + 4 * math.sin(t * 1.6 + 1) + self._rnd()
        else:
            l1, l2 = 1.2 + self._rnd() * 0.4, 0.8 + self._rnd() * 0.4
            s1, s2 = 3 * math.sin(t * 2.3) + self._rnd(), 3 * math.sin(t * 2.0 + 1) + self._rnd()
        maf = 3.2 + load * 42 + (1.6 if self.scenario == "rich" else 0) + self._rnd() * 0.5
        self._values = {"rpm": self._rpm, "ect": self._ect, "s1": s1, "l1": l1, "s2": s2, "l2": l2,
                        "maf": maf, "volts": 13.9 + self._rnd() * 0.12}

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        if cmd == "010C":
            self._advance()  # one model step per sweep
        if cmd.startswith("01") and len(cmd) == 4:
            pid = cmd[2:]
            if pid in ENCODERS:
                raw = ENCODERS[pid](self._values[_KEY[pid]])
                self._pending = f"41 {pid} " + " ".join(f"{b:02X}" for b in raw) + "\r"
            else:
                self._pending = "NO DATA\r"
        elif cmd == "ATI":
            self._pending = "SIM327 (simulated)\r"
        elif cmd == "STI":
            self._pending = "?\r"
        elif cmd == "ATDP":
            self._pending = "SIMULATED (no car)\r"
        else:
            self._pending = "OK\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def close(self) -> None:
        pass
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider 2>&1 | tail -3`
Expected: whole suite passes. If a range assertion in `test_every_scenario_stays_in_physical_ranges` fails, print the offending row and fix the model (not the bounds) unless the bound itself is physically wrong.

- [ ] **Step 5: Commit batch A**

```bash
git add src/obd_reader/live.py src/obd_reader/simulator.py tests/test_live.py tests/test_simulator.py docs/mocks/console-mock.html docs/superpowers/plans/2026-09-30-live-console.md
git commit -m "feat: shared single-PID read and a pretend car for the console demo (batch A)"
```

---

### Task 3: `LiveHub` (the shared sampler)

**Files:**
- Create: `src/obd_reader/hub.py`
- Modify: `src/obd_reader/session.py` (message only)
- Test: `tests/test_hub.py`

**Interfaces:**
- Consumes: `Session.connection`, `live.validate_pids/read_pid_value/MIN_HZ/MAX_HZ/summarize`, `adapter.identify`, `pids.PIDS`, `snapshot.LiveSample/Series`, `simulator.SimPort` (optional `sim` handle).
- Produces: `hub.HubBusy(RuntimeError)`; `hub.MAX_RUN_S = 1800.0`, `hub.DEFAULT_PIDS = ["0C","05","06","07","08","09","10","42"]`; `hub.LiveHub(session, *, sim: SimPort | None = None, max_buffer=600, clock=time.monotonic)` with:
  - `start(pids, hz=2.5, seconds=600.0) -> None` (validates, resets buffers, starts a daemon thread; `HubBusy` if already running).
  - `stop(timeout=5.0) -> None`.
  - `state(after: int = 0) -> dict` with keys `status` (`idle|running|stopped|error`), `message`, `demo`, `seq`, `now`, `since_last_sample`, `hz`, `hz_measured`, `seconds_left`, `adapter` (`{chip, ati, protocol}`), `channels` (`{pid: {name, unit, samples: [[seq, t, v], ...]}}` only samples with `seq > after`, at most 600 sweeps).
  - `recent(seconds: float) -> dict` — `{pid: {"name","unit","stats": summarize(...), "latest": v}}` over the last `seconds` of buffered time.
  - `save_run(label: str) -> Path` — writes `<home>/runs/<UTC time>-<label>.json` (`"x"` mode), `label` matches `[a-z0-9-]{1,40}`, `ValueError("nothing sampled yet")` if `seq == 0`.
  - `set_sim(scenario: str | None = None, rev: bool | None = None) -> None` — `ValueError` when no `sim`.
- `AdapterBusy` message becomes: `"the adapter is busy (another tool call, or the live console is sampling); use console_data for live values, or stop the console first"` (still contains the word "busy").

- [ ] **Step 1: Write the failing tests** — create `tests/test_hub.py`:

```python
import json
import time

import pytest

from obd_reader.hub import DEFAULT_PIDS, HubBusy, LiveHub
from obd_reader.live import LiveLimitError
from obd_reader.session import AdapterBusy, Config, Session
from obd_reader.simulator import SimPort

from conftest import ScriptedPort


def make(tmp_path, port_factory=None, sim=None):
    sim = sim or SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=port_factory or (lambda: sim))
    return LiveHub(s, sim=sim), s, sim


def wait_for(cond, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_hub_samples_and_reports_increments(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 5)
    st = hub.state(after=0)
    assert st["status"] == "running" and st["demo"] is True and set(st["channels"]) == set(DEFAULT_PIDS)
    assert st["channels"]["0C"]["name"] == "engine_rpm" and st["channels"]["0C"]["unit"] == "rpm"
    first = st["seq"]
    assert wait_for(lambda: hub.state()["seq"] > first + 2)
    inc = hub.state(after=first)
    assert all(s[0] > first for s in inc["channels"]["0C"]["samples"]) and inc["channels"]["0C"]["samples"]
    assert st["adapter"]["protocol"] in (None, "SIMULATED (no car)")
    hub.stop()
    assert hub.state()["status"] == "stopped"


def test_two_viewers_with_different_after_values_both_get_correct_increments(tmp_path):  # Review Focus 4
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 6)
    hub.stop()
    full = hub.state(0)["channels"]["0C"]["samples"]
    a, b = hub.state(2)["channels"]["0C"]["samples"], hub.state(4)["channels"]["0C"]["samples"]
    assert [s[0] for s in a] == [s[0] for s in full if s[0] > 2]
    assert [s[0] for s in b] == [s[0] for s in full if s[0] > 4]


def test_a_new_run_resets_seq_and_buffers(tmp_path):  # Review Focus 4
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 4)
    hub.stop()
    old = hub.state()["seq"]
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 1)
    assert hub.state()["seq"] < old + 2 and hub.state(0)["channels"]["0C"]["samples"][0][0] == 1
    hub.stop()


@pytest.mark.parametrize("pids", [[], ["0C\r04"], ["ZZ"], ["FF"], [f"{i:02X}" for i in range(9)]])
def test_bad_pids_are_refused_before_any_traffic(tmp_path, pids):  # Review Focus 2
    opened = []
    hub, _, _ = make(tmp_path, port_factory=lambda: opened.append(1) or ScriptedPort({}))
    with pytest.raises(LiveLimitError):
        hub.start(pids)
    assert opened == [] and hub.state()["status"] == "idle"


@pytest.mark.parametrize("hz,seconds", [(0, 10), (1e-9, 10), (11, 10), (float("nan"), 10), (2, 0), (2, -1),
                                        (2, 1801), (2, float("inf")), (2, float("nan"))])
def test_bad_rate_or_duration_is_refused(tmp_path, hz, seconds):  # Review Focus 2
    hub, _, _ = make(tmp_path)
    with pytest.raises(LiveLimitError):
        hub.start(DEFAULT_PIDS, hz=hz, seconds=seconds)


def test_starting_twice_is_refused(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    with pytest.raises(HubBusy):
        hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    hub.stop()


def test_hub_holds_the_adapter_lock_while_running_and_releases_it(tmp_path):  # Review Focus 3
    hub, session, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 1)
    with pytest.raises(AdapterBusy) as e:
        with session.connection("other"):
            pass
    assert "console_data" in str(e.value)
    hub.stop()
    with session.connection("after"):
        pass


def test_silent_bus_ends_the_run_with_a_message(tmp_path):  # Review Focus 3
    hub, _, _ = make(tmp_path, port_factory=lambda: ScriptedPort({}), sim=SimPort())
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["status"] != "running")
    st = hub.state()
    assert st["status"] == "stopped" and "no data" in st["message"].lower() and st["seq"] == 0


def test_a_failing_adapter_ends_in_error_and_frees_the_lock(tmp_path):  # Review Focus 3
    class Boom(ScriptedPort):
        def write(self, data):
            raise RuntimeError("cable unplugged")

    hub, session, _ = make(tmp_path, port_factory=lambda: Boom({}), sim=SimPort())
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["status"] == "error")
    assert "cable unplugged" in hub.state()["message"]
    with session.connection("after"):  # lock released, no zombie
        pass


def test_run_auto_stops_at_the_deadline(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=0.5)
    assert wait_for(lambda: hub.state()["status"] == "stopped", 4.0)
    assert "auto-stopped" in hub.state()["message"]


def test_recent_reports_exact_stats_over_the_window(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 8)
    hub.stop()
    r = hub.recent(30)
    assert r["0C"]["name"] == "engine_rpm" and r["0C"]["stats"]["n"] >= 8
    assert r["0C"]["latest"] == hub.state(hub.state()["seq"] - 1)["channels"]["0C"]["samples"][-1][2]


def test_save_run_writes_a_json_file_and_never_overwrites(tmp_path):
    hub, _, _ = make(tmp_path)
    with pytest.raises(ValueError):
        hub.save_run("early")  # nothing sampled yet
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 3)
    hub.stop()
    p = hub.save_run("bench-idle")
    data = json.loads(p.read_text())
    assert p.parent == (tmp_path / "runs") and data["live_sample"]["series"]["0C"]["samples"]
    for bad in ("../x", "A b", "", "x" * 41):
        with pytest.raises(ValueError):
            hub.save_run(bad)


def test_set_sim_only_in_demo(tmp_path):
    hub, _, sim = make(tmp_path)
    hub.set_sim(scenario="lean", rev=True)
    assert sim.scenario == "lean" and sim.rev is True
    with pytest.raises(ValueError):
        hub.set_sim(scenario="bogus")
    real = LiveHub(Session(Config(port="x", home=tmp_path), port_factory=lambda: ScriptedPort({})))
    with pytest.raises(ValueError):
        real.set_sim(rev=True)
```

- [ ] **Step 2: Run to verify failure**

Run: `timeout 60 .venv/bin/python -m pytest tests/test_hub.py -q --tb=line -p no:cacheprovider 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.hub'`.

- [ ] **Step 3: Implement** — first change the message in `src/obd_reader/session.py`:

```python
            raise AdapterBusy(
                "the adapter is busy (another tool call, or the live console is sampling); "
                "use console_data for live values, or stop the console first"
            )
```

then create `src/obd_reader/hub.py`:

```python
"""One sampler, many viewers: a background thread reads a fixed set of Mode 01 PIDs
through the Session (lock + gated transport + transcript) into ring buffers that the
console page and Claude's tools both read."""
import json
import math
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from obd_reader.adapter import identify
from obd_reader.live import MAX_HZ, MIN_HZ, LiveLimitError, read_pid_value, summarize, validate_pids
from obd_reader.pids import PIDS
from obd_reader.session import Session
from obd_reader.simulator import SimPort
from obd_reader.snapshot import LiveSample, Series

MAX_RUN_S = 1800.0
DEFAULT_PIDS = ["0C", "05", "06", "07", "08", "09", "10", "42"]
_SILENT_SWEEPS = 3
_LABEL_RE = re.compile(r"[a-z0-9-]{1,40}")


class HubBusy(RuntimeError):
    """The hub is already sampling."""


class LiveHub:
    def __init__(self, session: Session, *, sim: SimPort | None = None, max_buffer: int = 600,
                 clock: Callable[[], float] = time.monotonic):
        self._s, self._sim, self._max, self._clock = session, sim, max_buffer, clock
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reset()

    def _reset(self) -> None:
        self.status, self.message, self.seq, self.hz = "idle", None, 0, None
        self._ch: dict[str, deque] = {}
        self._sweep_t: deque = deque(maxlen=12)
        self._t0 = self._last_at = self._deadline = None
        self._adapter: dict = {"chip": None, "ati": None, "protocol": None}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, pids: list[str], hz: float = 2.5, seconds: float = 600.0) -> None:
        pids = validate_pids(pids)
        if not (isinstance(hz, (int, float)) and math.isfinite(hz) and MIN_HZ <= hz <= MAX_HZ):
            raise LiveLimitError(f"hz must be between {MIN_HZ:g} and {MAX_HZ:g}")
        if not (isinstance(seconds, (int, float)) and math.isfinite(seconds) and 0 < seconds <= MAX_RUN_S):
            raise LiveLimitError(f"seconds must be in (0, {MAX_RUN_S:g}]")
        with self._lock:
            if self.running:
                raise HubBusy("the console is already sampling; stop it first")
            self._reset()
            self.hz, self.status = float(hz), "running"
            self._ch = {p: deque(maxlen=self._max) for p in pids}
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, args=(pids, float(hz), float(seconds)), daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout)

    def _run(self, pids: list[str], hz: float, seconds: float) -> None:
        try:
            with self._s.connection("console") as t:
                a = identify(t)
                self._adapter.update(chip=a.chip, ati=a.ati)
                t0 = self._clock()
                self._t0, self._deadline = t0, t0 + seconds
                silent, period = 0, 1.0 / hz
                while not self._stop.is_set():
                    now = self._clock() - t0
                    if now > seconds:
                        self.message = f"auto-stopped after {seconds:g} s"
                        break
                    if self._sweep(t, pids, now):
                        silent = 0
                        if self._adapter["protocol"] is None:
                            dp = (t.send("ATDP") or [None])[0]
                            self._adapter["protocol"] = dp.removeprefix("AUTO, ") if dp else None
                    else:
                        silent += 1
                        if silent >= _SILENT_SWEEPS:
                            self.message = "no data: the ECU did not answer any PID (car off or not connected?)"
                            break
                    self._stop.wait(max(0.0, period - (self._clock() - t0 - now)))
        except Exception as e:  # never let the thread die silently: report it and free the adapter
            self.status, self.message = "error", f"{type(e).__name__}: {e}"
        finally:
            if self.status != "error":
                self.status = "stopped"

    def _sweep(self, t, pids: list[str], now: float) -> bool:
        seq, got = self.seq + 1, False
        for p in pids:
            v = read_pid_value(t, p)
            if v is not None:
                self._ch[p].append((seq, round(now, 3), v))
                got = True
        if got:
            self.seq = seq
            self._last_at = self._clock()
            self._sweep_t.append(now)
        return got

    def state(self, after: int = 0) -> dict:
        now = (self._clock() - self._t0) if self._t0 is not None else 0.0
        st = list(self._sweep_t)
        measured = (len(st) - 1) / (st[-1] - st[0]) if len(st) >= 2 and st[-1] > st[0] else None
        return {
            "status": self.status, "message": self.message, "demo": self._sim is not None,
            "seq": self.seq, "now": round(now, 3),
            "since_last_sample": None if self._last_at is None else round(self._clock() - self._last_at, 2),
            "hz": self.hz, "hz_measured": None if measured is None else round(measured, 2),
            "seconds_left": (max(0.0, round(self._deadline - self._clock(), 1))
                             if self.status == "running" and self._deadline else None),
            "adapter": dict(self._adapter),
            "channels": {
                p: {"name": PIDS[p].name, "unit": PIDS[p].unit,
                    "samples": [[s, tt, v] for s, tt, v in list(d) if s > after]}
                for p, d in self._ch.items()
            },
        }

    def recent(self, seconds: float) -> dict:
        out: dict[str, dict] = {}
        for p, d in self._ch.items():
            rows = list(d)
            if not rows:
                out[p] = {"name": PIDS[p].name, "unit": PIDS[p].unit, "stats": {"n": 0}, "latest": None}
                continue
            cut = rows[-1][1] - seconds
            win = [(tt, v) for _, tt, v in rows if tt >= cut]
            out[p] = {"name": PIDS[p].name, "unit": PIDS[p].unit,
                      "stats": summarize(Series(name=PIDS[p].name, unit=PIDS[p].unit, samples=win)),
                      "latest": rows[-1][2]}
        return out

    def save_run(self, label: str) -> Path:
        if not _LABEL_RE.fullmatch(label):
            raise ValueError("label must be 1-40 chars of [a-z0-9-]")
        if self.seq == 0:
            raise ValueError("nothing sampled yet")
        series = {p: Series(name=PIDS[p].name, unit=PIDS[p].unit, samples=[(tt, v) for _, tt, v in d])
                  for p, d in self._ch.items()}
        ls = LiveSample(duration_s=self.state()["now"], rate_hz=self.hz or 0.0, series=series)
        rdir = Path(self._s.config.home) / "runs"
        rdir.mkdir(parents=True, exist_ok=True)
        path = rdir / f"{datetime.now(timezone.utc):%Y-%m-%dT%H-%M-%SZ}-{label}.json"
        with open(path, "x", encoding="utf-8") as fh:
            json.dump({"kind": "live_run", "demo": self._sim is not None, "adapter": self._adapter,
                       "live_sample": ls.model_dump(mode="json")}, fh, indent=2)
        return path

    def set_sim(self, scenario: str | None = None, rev: bool | None = None) -> None:
        if self._sim is None:
            raise ValueError("simulator controls exist only in demo mode")
        if scenario is not None:
            self._sim.set_scenario(scenario)
        if rev is not None:
            self._sim.rev = bool(rev)
```

- [ ] **Step 4: Run to verify pass**

Run: `timeout 120 .venv/bin/python -m pytest -q --tb=short -p no:cacheprovider 2>&1 | tail -4`
Expected: everything passes. The tests use real threads at 10 Hz and finish in a few seconds; if `test_a_new_run_resets_seq_and_buffers` is flaky, the cause is a race between `stop()` joining the thread and the second `start()`: confirm `stop()` joined (thread dead) before changing anything else.

---

### Task 4: The console HTTP server

**Files:**
- Create: `src/obd_reader/console.py`, `src/obd_reader/web/__init__.py` (empty), `src/obd_reader/web/console.html` (a placeholder page for this task, replaced in Task 5)
- Modify: `pyproject.toml` (package data)
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `LiveHub`, `HubBusy`, `live.LiveLimitError`, `session.AdapterBusy/NoAdapterError`.
- Produces: `console.ConsoleServer(hub, *, host="127.0.0.1", port=0, token=None, allow_lan=False)` with `.token`, `.host`, `.port`, `.url` (`http://<host>:<port>/?t=<token>`), `.start()`, `.stop()`. Routes: `GET /` (page), `GET /api/state?after=N`, `POST /api/start`, `/api/stop`, `/api/save`, `/api/sim`. Refusals: `401` bad/missing token, `403` bad Host or foreign Origin, `404`, `405`, `409` (`HubBusy`, `AdapterBusy`), `400` (validation, `NoAdapterError`), `413` body > 4096, `415` POST without `application/json`.

- [ ] **Step 1: Placeholder page and package data**

Create `src/obd_reader/web/__init__.py` (empty file) and `src/obd_reader/web/console.html`:

```html
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>shadetree-ai console</title></head>
<body><h1>shadetree-ai console</h1><p>placeholder page</p></body></html>
```

In `pyproject.toml` add:

```toml
[tool.setuptools.package-data]
"obd_reader.web" = ["console.html"]
```

Run: `.venv/bin/pip install -q -e ".[dev]"`
Expected: installs cleanly.

- [ ] **Step 2: Write the failing tests** — create `tests/test_console.py`:

```python
import http.client
import json
import time

import pytest

from obd_reader.console import ConsoleServer
from obd_reader.hub import DEFAULT_PIDS, LiveHub
from obd_reader.session import Config, Session
from obd_reader.simulator import SimPort

from conftest import ScriptedPort


@pytest.fixture
def srv(tmp_path):
    sim = SimPort("rich")
    session = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(session, sim=sim)
    server = ConsoleServer(hub, token="tok123")
    server.start()
    yield server, hub, session
    hub.stop()
    server.stop()


def call(server, method, path, body=None, headers=None, token="tok123", host=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    sep = "&" if "?" in path else "?"
    url = path + (f"{sep}t={token}" if token is not None else "")
    h = {"Host": host or f"127.0.0.1:{server.port}"}
    h.update(headers or {})
    payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
    if payload is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    c.request(method, url, body=payload, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, data.decode("utf-8", "replace")


def wait_seq(server, n):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if call(server, "GET", "/api/state")[1]["seq"] >= n:
            return True
        time.sleep(0.03)
    return False


def test_page_and_state_need_the_token(srv):  # Review Focus 1
    server, _, _ = srv
    assert call(server, "GET", "/", token=None)[0] == 401
    assert call(server, "GET", "/api/state", token="wrong")[0] == 401
    status, body = call(server, "GET", "/api/state", token=None)
    assert status == 401 and "channels" not in json.dumps(body)  # a refusal leaks nothing
    assert call(server, "GET", "/")[0] == 200
    assert call(server, "GET", "/api/state", token=None, headers={"X-Console-Token": "tok123"})[0] == 200


def test_wrong_host_header_is_refused(srv):  # Review Focus 1 (DNS rebinding)
    server, _, _ = srv
    for host in ("evil.example", "evil.example:80", f"attacker.test:{server.port}", "127.0.0.1"):
        assert call(server, "GET", "/api/state", host=host)[0] == 403, host
    assert call(server, "GET", "/api/state", host=f"localhost:{server.port}")[0] == 200


def test_foreign_origin_on_post_is_refused(srv):  # Review Focus 1 (CSRF)
    server, hub, _ = srv
    st, _ = call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS}, headers={"Origin": "http://evil.example"})
    assert st == 403 and not hub.running
    own = f"http://127.0.0.1:{server.port}"
    assert call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10}, headers={"Origin": own})[0] == 200


def test_start_stop_and_state_flow(srv):
    server, hub, _ = srv
    assert call(server, "GET", "/api/state")[1]["status"] == "idle"
    st, body = call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10, "seconds": 30})
    assert st == 200 and body["ok"] is True
    assert wait_seq(server, 4)
    state = call(server, "GET", "/api/state?after=0")[1]
    assert state["status"] == "running" and state["demo"] is True and state["channels"]["0C"]["samples"]
    assert call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS})[0] == 409  # already sampling
    assert call(server, "POST", "/api/stop", {})[0] == 200
    assert call(server, "GET", "/api/state")[1]["status"] == "stopped"


@pytest.mark.parametrize("body", [
    {"pids": ["0C\r04"]}, {"pids": ["ZZ"]}, {"pids": [f"{i:02X}" for i in range(9)]}, {"pids": []},
    {"pids": ["0C"], "hz": 0}, {"pids": ["0C"], "hz": 1e-9}, {"pids": ["0C"], "seconds": 99999},
    {"pids": ["0C"], "hz": "fast"}, {"pids": "0C"}, {"pids": [None]}, {},
])
def test_bad_start_requests_are_400_and_nothing_starts(srv, body):  # Review Focus 2
    server, hub, _ = srv
    assert call(server, "POST", "/api/start", body)[0] == 400
    assert not hub.running and hub.state()["status"] == "idle"


def test_body_and_content_type_rules(srv):  # Review Focus 2
    server, hub, _ = srv
    assert call(server, "POST", "/api/start", raw="x" * 5000)[0] == 413
    assert call(server, "POST", "/api/start", raw="{not json")[0] == 400
    assert call(server, "POST", "/api/start", raw="[1,2]")[0] == 400
    assert call(server, "POST", "/api/start", raw="{}", headers={"Content-Type": "text/plain"})[0] == 415
    assert not hub.running


def test_routes_and_methods(srv):
    server, _, _ = srv
    assert call(server, "GET", "/nope")[0] == 404
    assert call(server, "GET", "/api/start")[0] == 405
    assert call(server, "POST", "/api/state", {})[0] == 405
    assert call(server, "DELETE", "/api/state")[0] == 405
    assert call(server, "GET", "/..%2f..%2fetc/passwd")[0] == 404


def test_save_and_sim_endpoints(srv, tmp_path):
    server, hub, _ = srv
    assert call(server, "POST", "/api/save", {"label": "early"})[0] == 400  # nothing sampled
    call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10, "seconds": 30})
    assert wait_seq(server, 3)
    call(server, "POST", "/api/stop", {})
    st, body = call(server, "POST", "/api/save", {"label": "bench"})
    assert st == 200 and body["path"].endswith("-bench.json")
    assert call(server, "POST", "/api/save", {"label": "../x"})[0] == 400
    assert call(server, "POST", "/api/sim", {"scenario": "lean", "rev": True})[0] == 200
    assert call(server, "POST", "/api/sim", {"scenario": "bogus"})[0] == 400


def test_sim_is_refused_when_not_in_demo(tmp_path):
    session = Session(Config(port="x", home=tmp_path), port_factory=lambda: ScriptedPort({}))
    server = ConsoleServer(LiveHub(session), token="tok123")
    server.start()
    try:
        assert call(server, "POST", "/api/sim", {"rev": True})[0] == 400
    finally:
        server.stop()


def test_a_second_tool_using_the_adapter_gets_a_409(srv):
    server, hub, session = srv
    with session.connection("holder"):
        st, body = call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10})
    assert st in (200, 409)  # the hub thread reports the lock error as status "error", not a crash
    time.sleep(0.3)
    hub.stop()


def test_binding_off_loopback_needs_the_explicit_flag(tmp_path):
    session = Session(Config(port="x", home=tmp_path), port_factory=lambda: ScriptedPort({}))
    with pytest.raises(ValueError):
        ConsoleServer(LiveHub(session), host="0.0.0.0")
    ConsoleServer(LiveHub(session), host="0.0.0.0", allow_lan=True).stop()


def test_security_headers_and_no_cors(srv):
    server, _, _ = srv
    c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    c.request("GET", "/?t=tok123", headers={"Host": f"127.0.0.1:{server.port}"})
    r = c.getresponse()
    r.read()
    hdr = {k.lower(): v for k, v in r.getheaders()}
    assert hdr["cache-control"] == "no-store" and hdr["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in hdr["content-security-policy"]
    assert not any(k.startswith("access-control-") for k in hdr)
    c.close()
```

- [ ] **Step 3: Run to verify failure**

Run: `timeout 60 .venv/bin/python -m pytest tests/test_console.py -q --tb=line -p no:cacheprovider 2>&1 | grep -E "ModuleNotFound|passed|failed" | head -3`
Expected: `ModuleNotFoundError: No module named 'obd_reader.console'`.

- [ ] **Step 4: Implement** — create `src/obd_reader/console.py`:

```python
"""Local web console: one page plus a small token-protected JSON API over a LiveHub."""
import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from obd_reader.hub import HubBusy, LiveHub
from obd_reader.live import LiveLimitError
from obd_reader.session import AdapterBusy, NoAdapterError

MAX_BODY = 4096
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_CSP = ("default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'")


class ConsoleServer:
    def __init__(self, hub: LiveHub, *, host: str = "127.0.0.1", port: int = 0,
                 token: str | None = None, allow_lan: bool = False):
        if host not in _LOOPBACK and not allow_lan:
            raise ValueError("binding to a non-loopback address needs allow_lan=True (--allow-lan)")
        self.hub, self.token = hub, token or secrets.token_urlsafe(16)
        self.httpd = ThreadingHTTPServer((host, port), self._handler())
        self.host, self.port = self.httpd.server_address[0], self.httpd.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        if host not in _LOOPBACK:
            self.allowed_hosts.add(f"{host}:{self.port}")  # LAN: the user opens it by the address it is bound to
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{'127.0.0.1' if self.host in ('0.0.0.0', '::') else self.host}:{self.port}/?t={self.token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            if self._thread is not None:
                self.httpd.shutdown()
        finally:
            self.httpd.server_close()

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "shadetree-console"
            sys_version = ""

            def log_message(self, *args):  # request lines carry the token: never log them
                pass

            # ---- plumbing ----
            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", _CSP)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, obj: dict) -> None:
                self._send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

            def _guard(self, post: bool) -> tuple[bool, dict]:
                if self.headers.get("Host", "") not in outer.allowed_hosts:
                    self._json(403, {"error": "forbidden"})
                    return False, {}
                if post:
                    origin = self.headers.get("Origin")
                    if origin is not None and origin not in {f"http://{h}" for h in outer.allowed_hosts}:
                        self._json(403, {"error": "forbidden"})
                        return False, {}
                q = parse_qs(urlparse(self.path).query)
                supplied = (q.get("t") or [self.headers.get("X-Console-Token", "")])[0]
                if not hmac.compare_digest(supplied.encode(), outer.token.encode()):
                    self._json(401, {"error": "unauthorized"})
                    return False, {}
                return True, q

            def _body(self) -> dict | None:
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    self._json(415, {"error": "send application/json"})
                    return None
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = -1
                if n < 0 or n > MAX_BODY:
                    self._json(413, {"error": "body too large"})
                    return None
                try:
                    data = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    self._json(400, {"error": "body is not valid JSON"})
                    return None
                if not isinstance(data, dict):
                    self._json(400, {"error": "body must be a JSON object"})
                    return None
                return data

            # ---- routes ----
            def do_GET(self):
                path = urlparse(self.path).path
                if path not in ("/", "/api/state"):
                    if path in ("/api/start", "/api/stop", "/api/save", "/api/sim"):
                        return self._json(405, {"error": "use POST"})
                    return self._json(404, {"error": "not found"})
                ok, q = self._guard(post=False)
                if not ok:
                    return
                if path == "/":
                    html = resources.files("obd_reader.web").joinpath("console.html").read_bytes()
                    return self._send(200, html, "text/html; charset=utf-8")
                try:
                    after = max(0, int((q.get("after") or ["0"])[0]))
                except ValueError:
                    return self._json(400, {"error": "after must be an integer"})
                self._json(200, outer.hub.state(after))

            def do_POST(self):
                path = urlparse(self.path).path
                if path not in ("/api/start", "/api/stop", "/api/save", "/api/sim"):
                    if path in ("/", "/api/state"):
                        return self._json(405, {"error": "use GET"})
                    return self._json(404, {"error": "not found"})
                ok, _ = self._guard(post=True)
                if not ok:
                    return
                body = self._body()
                if body is None:
                    return
                try:
                    if path == "/api/start":
                        outer.hub.start(body.get("pids"), hz=body.get("hz", 2.5), seconds=body.get("seconds", 600.0))
                        return self._json(200, {"ok": True})
                    if path == "/api/stop":
                        outer.hub.stop()
                        return self._json(200, {"ok": True})
                    if path == "/api/save":
                        return self._json(200, {"ok": True, "path": str(outer.hub.save_run(str(body.get("label", "run"))))})
                    outer.hub.set_sim(scenario=body.get("scenario"), rev=body.get("rev"))
                    return self._json(200, {"ok": True})
                except (HubBusy, AdapterBusy) as e:
                    return self._json(409, {"error": str(e)})
                except (LiveLimitError, ValueError, TypeError, NoAdapterError) as e:
                    return self._json(400, {"error": str(e)})

            def _not_allowed(self):
                self._json(405, {"error": "method not allowed"})

            do_PUT = do_DELETE = do_PATCH = _not_allowed

        return Handler
```

- [ ] **Step 5: Run to verify pass**

Run: `timeout 180 .venv/bin/python -m pytest -q --tb=short -p no:cacheprovider 2>&1 | tail -4`
Expected: everything passes. Notes: `{"pids": None}` (missing) reaches `validate_pids(None)`, which must raise a `ValueError`-family error; `validate_pids` already raises `LiveLimitError` for a non-list via `not pids` — if it raises `TypeError` for `"0C"` (a string, iterable of str) the server maps `TypeError` to 400 too, but confirm `{"pids": "0C"}` returns 400 and fix `validate_pids` to reject non-lists explicitly if it does not.

- [ ] **Step 6: Commit batch B**

```bash
git add src/obd_reader/hub.py src/obd_reader/session.py src/obd_reader/console.py src/obd_reader/web/__init__.py src/obd_reader/web/console.html pyproject.toml tests/test_hub.py tests/test_console.py
git commit -m "feat: live hub (shared sampler) and token-protected console server (batch B)"
```

---

### Task 5: The page — three layouts fed by the live API

**Files:**
- Modify: `src/obd_reader/web/console.html` (replace the placeholder)
- Test: `tests/test_console_page.py`

**Interfaces:**
- Consumes: the API from Task 4 (`state.channels[pid].samples = [[seq, t, v], ...]`, `state.status/message/demo/adapter/hz_measured/since_last_sample/seconds_left`).
- Produces: the page. Element ids the tests rely on: `chipLive`, `chipConn`, `pause`, `save`, `msg`, `simctl`, views `v1 v2 v3`, view buttons with `data-view`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_console_page.py`:

```python
import re
import shutil
import subprocess
from importlib import resources

import pytest

HTML = resources.files("obd_reader.web").joinpath("console.html").read_text(encoding="utf-8")


def test_page_is_self_contained_with_no_external_urls():
    assert not re.search(r"https?://", HTML)
    assert "<script src" not in HTML and "<link " not in HTML


def test_every_view_button_has_a_matching_section():
    for view in re.findall(r'data-view="([a-z0-9]+)"', HTML):
        assert f'id="{view}"' in HTML
    assert {"v1", "v2", "v3"} <= set(re.findall(r'data-view="([a-z0-9]+)"', HTML))


def test_required_controls_exist_and_no_simulator_is_baked_in():
    for element_id in ("chipLive", "chipConn", "pause", "save", "msg", "simctl", "rpmGauge", "c1trims",
                       "s_trim", "results", "verdict", "go_idle", "go_rev"):
        assert f'id="{element_id}"' in HTML, element_id
    assert "function tick" not in HTML  # the mock's fake data generator is gone
    assert "/api/state" in HTML and "/api/start" in HTML and "/api/stop" in HTML and "/api/save" in HTML


def test_page_states_it_is_read_only_and_marks_the_playbook_unreviewed():
    assert "READ-ONLY" in HTML and "unreviewed" in HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_inline_script_parses(tmp_path):
    js = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)
    f = tmp_path / "console.js"
    f.write_text(js)
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_console_page.py -q --tb=line -p no:cacheprovider 2>&1 | grep -E "^E |passed|failed" | head -4`
Expected: failures (the placeholder page has no controls).

- [ ] **Step 3: Build the page from the reviewed mock**

Copy `docs/mocks/console-mock.html` to `src/obd_reader/web/console.html`, then make exactly these edits.

**E1 — title:** `<title>Mock — shadetree-ai live console</title>` → `<title>shadetree-ai console</title>`.

**E2 — banner and brand line:** replace the `<div class="banner">Mock …</div>` line with:

```html
<div class="banner" id="demoBanner" hidden>Demo &mdash; simulated engine, no car connected</div>
```

and replace the brand sub-line `127.0.0.1:8765/?t=&hellip; (local page, token-protected)` with `local page, token-protected, read-only`.

**E3 — CSS additions** (append before `</style>`):

```css
  .banner[hidden], [hidden] { display: none !important; }
  .msgbar { padding: 8px 16px; background: #2a2114; border-bottom: 1px solid var(--amber); color: var(--amber); font-size: 13px; }
  .chip.err b::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 6px; background: var(--bad); }
  .chip.idle b::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 6px; border: 1px solid var(--muted); }
  .dash { color: var(--muted); }
```

**E4 — status bar markup:** replace the whole `<div class="status"> … </div>` block with:

```html
<div class="status">
  <span class="chip ro"><b>READ-ONLY</b> &middot; this page cannot send commands</span>
  <span class="chip" id="chipConn"><b>no adapter</b></span>
  <span class="chip idle" id="chipLive"><b>NOT SAMPLING</b></span>
  <span class="chip">rate <b id="rate">&mdash;</b></span>
  <span class="chip">last sample <b id="age">&mdash;</b></span>
  <span class="chip">auto-stop in <b id="autostop">&mdash;</b></span>
  <div class="ctl">
    <span id="simctl" hidden>
      <label class="chip">simulate
        <select class="b" id="scenario">
          <option value="healthy">Healthy engine</option>
          <option value="rich" selected>Rich: coolant sensor reads cold</option>
          <option value="lean">Lean at idle: vacuum leak</option>
        </select></label>
      <button class="b" id="rev">Rev to 2500 rpm (sim)</button>
    </span>
    <button class="b" id="pause">Start sampling</button>
    <button class="b primary" id="save">Save run</button>
  </div>
</div>
<div class="msgbar" id="msg" hidden></div>
```

**E5 — footer text:** replace the `<p class="foot">…</p>` content with: `Values come from one shared sampler, so Claude and this page see the same numbers. Nothing on this page can send a command to the car. The &plusmn;10 % trim window used for the OUTSIDE tag is general knowledge, unverified. The guided test is a draft, unreviewed playbook.`

**E6 — the script:** replace the entire `<script> … </script>` block with:

```html
<script>
(function () {
  'use strict';
  var TOKEN = new URLSearchParams(location.search).get('t') || '';
  function api(path) { return path + (path.indexOf('?') < 0 ? '?' : '&') + 't=' + encodeURIComponent(TOKEN); }
  var CH = [
    { id: 'rpm',   pid: '0C', name: 'Engine speed',   unit: 'rpm', dp: 0 },
    { id: 'ect',   pid: '05', name: 'Coolant temp',   unit: '°C', dp: 0 },
    { id: 'stft1', pid: '06', name: 'STFT bank 1',    unit: '%',   dp: 1 },
    { id: 'ltft1', pid: '07', name: 'LTFT bank 1',    unit: '%',   dp: 1 },
    { id: 'stft2', pid: '08', name: 'STFT bank 2',    unit: '%',   dp: 1 },
    { id: 'ltft2', pid: '09', name: 'LTFT bank 2',    unit: '%',   dp: 1 },
    { id: 'maf',   pid: '10', name: 'MAF',            unit: 'g/s', dp: 1 },
    { id: 'volts', pid: '42', name: 'Control module', unit: 'V',   dp: 2 }
  ];
  var PIDS = CH.map(function (c) { return c.pid; });
  var SPAN = 60;
  var PAL = { cyan: '#4fc3e8', amber: '#f2a93b', mute: '#93a0aa', line: '#2c343b' };
  var buf = {}, last = {}, lastSeq = 0, tNow = 0, state = null, fetchedAt = 0, events = [], cap = null, results = {};
  CH.forEach(function (c) { buf[c.id] = []; last[c.id] = null; });
  function $(id) { return document.getElementById(id); }
  function fmt(v, dp) { return v === null || v === undefined ? '—' : (dp === 0 ? String(Math.round(v)) : v.toFixed(dp)); }

  Array.prototype.forEach.call(document.querySelectorAll('canvas'), function (cv) {
    if (!cv.style.height && cv.getAttribute('height')) cv.style.height = cv.getAttribute('height') + 'px';
  });

  /* ---------- data in ---------- */
  function resetBuffers() { CH.forEach(function (c) { buf[c.id] = []; last[c.id] = null; }); lastSeq = 0; events = []; }
  function ingest(st) {
    if (st.seq < lastSeq) resetBuffers();          // a new run started: sequence numbers restart
    state = st; fetchedAt = performance.now(); tNow = st.now;
    var rows = {};
    CH.forEach(function (c) {
      var ch = st.channels[c.pid]; if (!ch) return;
      ch.samples.forEach(function (s) {              // [seq, t, v]
        if (s[0] <= lastSeq) return;
        buf[c.id].push({ t: s[1], v: s[2] }); last[c.id] = s[2];
        (rows[s[0]] = rows[s[0]] || { t: s[1] })[c.id] = s[2];
      });
    });
    if (st.seq > lastSeq) lastSeq = st.seq;
    CH.forEach(function (c) { var b = buf[c.id]; while (b.length && b[0].t < tNow - SPAN - 2) b.shift(); });
    Object.keys(rows).map(Number).sort(function (a, b) { return a - b; }).forEach(function (k) { capRow(rows[k]); });
  }

  /* ---------- drawing helpers (from the reviewed mock) ---------- */
  function setup(cv) {
    var dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return null;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    var g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    return { g: g, w: w, h: h };
  }
  function trend(cv, series, range, opt) {
    var c = setup(cv); if (!c) return;
    opt = opt || {};
    var g = c.g, l = 40, r = 8, tp = 8, bt = 16, iw = c.w - l - r, ih = c.h - tp - bt, lo = range[0], hi = range[1];
    function X(t) { return l + iw - ((tNow - t) / SPAN) * iw; }
    function Y(v) { return tp + ih - ((v - lo) / (hi - lo)) * ih; }
    g.font = '11px ui-monospace, monospace'; g.textBaseline = 'middle'; g.lineWidth = 1;
    var nt = c.h < 100 ? 2 : 4;
    for (var k = 0; k <= nt; k++) {
      var val = lo + (hi - lo) * k / nt, y = Y(val);
      g.strokeStyle = PAL.line; g.beginPath(); g.moveTo(l, y); g.lineTo(l + iw, y); g.stroke();
      g.fillStyle = PAL.mute; g.textAlign = 'right'; g.fillText(Number.isInteger(val) ? String(val) : val.toFixed(1), l - 6, y);
    }
    if (lo < 0 && hi > 0) { g.strokeStyle = PAL.mute; g.beginPath(); g.moveTo(l, Y(0)); g.lineTo(l + iw, Y(0)); g.stroke(); }
    if (opt.band) { g.fillStyle = 'rgba(127,207,148,.12)'; g.fillRect(l, Y(opt.band[1]), iw, Y(opt.band[0]) - Y(opt.band[1])); }
    events.forEach(function (e) {
      var x = X(e.t); if (x < l) return;
      g.strokeStyle = PAL.mute; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(x, tp); g.lineTo(x, tp + ih); g.stroke(); g.setLineDash([]);
      g.fillStyle = PAL.mute; g.textAlign = 'left'; g.fillText(e.label, x + 4, tp + 8);
    });
    series.forEach(function (s) {
      var b = buf[s.id]; if (b.length < 2) return;
      g.strokeStyle = s.color; g.lineWidth = s.width || 2; g.setLineDash(s.dash || []); g.beginPath();
      b.forEach(function (p, i) { var y = Y(Math.max(lo, Math.min(hi, p.v))); if (i) g.lineTo(X(p.t), y); else g.moveTo(X(p.t), y); });
      g.stroke(); g.setLineDash([]);
    });
    g.fillStyle = PAL.mute; g.textAlign = 'right'; g.fillText('now', l + iw, c.h - 5); g.textAlign = 'left'; g.fillText('−60 s', l, c.h - 5);
  }
  function arc(cx, cy, r, a0, a1) {
    var p0 = [cx + r * Math.cos(a0), cy + r * Math.sin(a0)], p1 = [cx + r * Math.cos(a1), cy + r * Math.sin(a1)];
    return 'M' + p0[0].toFixed(1) + ' ' + p0[1].toFixed(1) + ' A' + r + ' ' + r + ' 0 ' + ((a1 - a0) > Math.PI ? 1 : 0) + ' 1 ' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1);
  }
  function rpmGauge(v) {
    var A0 = Math.PI * 0.85, A1 = Math.PI * 2.15, f = Math.max(0, Math.min(1, (v || 0) / 4000)), a = A0 + (A1 - A0) * f, s = '';
    s += '<path d="' + arc(150, 135, 118, A0, A1) + '" fill="none" stroke="#2c343b" stroke-width="16" stroke-linecap="round"/>';
    s += '<path d="' + arc(150, 135, 118, A0, Math.max(A0 + 0.001, a)) + '" fill="none" stroke="#4fc3e8" stroke-width="16" stroke-linecap="round"/>';
    for (var k = 0; k <= 4; k++) {
      var aa = A0 + (A1 - A0) * k / 4, x = 150 + 92 * Math.cos(aa), y = 135 + 92 * Math.sin(aa);
      s += '<text x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" fill="#93a0aa" font-size="13" text-anchor="middle" dominant-baseline="middle">' + (k * 1000) + '</text>';
    }
    $('rpmGauge').innerHTML = s;
  }
  function trimTag(id, v) {
    var el = $(id);
    if (v === null || v === undefined) { el.textContent = 'no data'; el.className = 'tag'; return; }
    var out = Math.abs(v) > 10;
    el.textContent = out ? (v < 0 ? 'OUTSIDE ±10 % · less fuel' : 'OUTSIDE ±10 % · more fuel') : 'within ±10 %';
    el.className = 'tag ' + (out ? 'warn' : 'ok');
  }
  function biBar(id, v) {
    var el = $(id), p = Math.max(-25, Math.min(25, v || 0)) / 25 * 50;
    el.style.left = (p >= 0 ? 50 : 50 + p) + '%'; el.style.width = Math.abs(p) + '%';
  }

  /* ---------- guided test (layout C): captures are timed by the sample timestamps ---------- */
  function capRow(row) {
    if (!cap) return;
    if (cap.t0 === null) cap.t0 = row.t;
    ['stft1', 'ltft1', 'stft2', 'ltft2', 'maf', 'rpm'].forEach(function (k) { if (row[k] !== undefined) { cap.sum[k] += row[k]; cap.cnt[k]++; } });
    var el = row.t - cap.t0;
    $('pg_' + cap.id).style.width = Math.min(100, el / cap.secs * 100) + '%';
    if (el >= cap.secs) {
      var m = {}; Object.keys(cap.sum).forEach(function (k) { m[k] = cap.cnt[k] ? cap.sum[k] / cap.cnt[k] : null; });
      results[cap.id] = m; $('st_' + cap.id).className = 'step done'; $('tx_' + cap.id).textContent = 'captured';
      $('go_' + cap.id).disabled = false; cap = null; renderResults();
    }
  }
  function startCap(id) {
    if (cap) return;
    if (!state || state.status !== 'running') { showMsg('Start sampling first, then capture.'); return; }
    cap = { id: id, secs: 15, t0: null, sum: { stft1: 0, ltft1: 0, stft2: 0, ltft2: 0, maf: 0, rpm: 0 }, cnt: { stft1: 0, ltft1: 0, stft2: 0, ltft2: 0, maf: 0, rpm: 0 } };
    $('st_' + id).className = 'step active'; $('tx_' + id).textContent = 'capturing…'; $('go_' + id).disabled = true;
  }
  function renderResults() {
    var rows = '', keys = ['stft1', 'ltft1', 'stft2', 'ltft2', 'maf', 'rpm'], names = { idle: 'Warm idle', rev: '2500 rpm hold' };
    ['idle', 'rev'].forEach(function (id) {
      if (!results[id]) return;
      rows += '<tr><td>' + names[id] + '</td>' + keys.map(function (k) { return '<td>' + fmt(results[id][k], k === 'rpm' ? 0 : 1) + '</td>'; }).join('') + '</tr>';
    });
    $('results').innerHTML = rows || '<tr><td colspan="7" style="text-align:center;color:var(--muted)">No captures yet</td></tr>';
    var v = $('verdict');
    if (results.idle && results.rev && results.idle.ltft1 !== null && results.rev.ltft1 !== null) {
      var i = results.idle.ltft1, r = results.rev.ltft1, txt;
      if (i < -10 && r < -10) txt = 'Long-term trim stays strongly negative at higher airflow on both banks. That argues against a vacuum leak, which fades as airflow rises <span class="cite">[ref:playbook:rich-condition-v1#step-4]</span>. Next: check coolant temperature plausibility <span class="cite">[ref:playbook:rich-condition-v1#step-2]</span>.';
      else if (i > 10 && r < i - 8) txt = 'Long-term trim is high at idle and falls as airflow rises: consistent with an unmetered air leak <span class="cite">[ref:playbook:rich-condition-v1#step-4]</span>.';
      else txt = 'No large long-term trim error in this run.';
      v.innerHTML = '<b>Reading of this run</b> <span class="tag warn">draft, unreviewed</span><br>' + txt; v.style.display = 'block';
      $('st_cmp').className = 'step done';
    } else { v.style.display = 'none'; $('st_cmp').className = 'step'; }
  }

  /* ---------- render ---------- */
  function active() { var a = document.querySelector('.view.is-active'); return a ? a.id : 'v1'; }
  function showMsg(text) { var m = $('msg'); if (text) { m.textContent = text; m.hidden = false; } else { m.hidden = true; } }
  function chips() {
    var st = state || { status: 'disconnected' }, live = $('chipLive'), label = { running: 'LIVE', stopped: 'STOPPED', error: 'ERROR', idle: 'NOT SAMPLING', disconnected: 'DISCONNECTED' }[st.status] || st.status;
    live.className = 'chip ' + (st.status === 'running' ? 'live' : st.status === 'error' || st.status === 'disconnected' ? 'err' : st.status === 'stopped' ? 'paused' : 'idle');
    live.innerHTML = '<b>' + label + '</b>';
    var ad = st.adapter || {};
    $('chipConn').innerHTML = '<b>' + (ad.chip || ad.ati || 'no adapter') + '</b>' + (ad.protocol ? ' &middot; ' + ad.protocol : '');
    $('rate').textContent = st.hz_measured ? st.hz_measured.toFixed(1) + ' Hz' : '—';
    var age = st.since_last_sample === null || st.since_last_sample === undefined ? null : st.since_last_sample + (st.status === 'running' ? (performance.now() - fetchedAt) / 1000 : 0);
    $('age').textContent = age === null ? '—' : age.toFixed(1) + ' s ago';
    var sl = st.seconds_left; $('autostop').textContent = sl === null || sl === undefined ? '—' : Math.floor(sl / 60) + ':' + ('0' + Math.floor(sl % 60)).slice(-2);
    $('pause').textContent = st.status === 'running' ? 'Stop sampling' : 'Start sampling';
    $('simctl').hidden = !st.demo; $('demoBanner').hidden = !st.demo;
    if (st.message) showMsg(st.message); else if (st.status !== 'disconnected') showMsg('');
    if (st.status === 'disconnected') showMsg('Lost contact with the console server. Is shadetree-ai still running?');
  }
  function render() {
    chips();
    var view = active();
    CH.forEach(function (c) { var e = $('v1' + c.id); if (e) e.textContent = fmt(last[c.id], c.dp); });
    if (view === 'v1') {
      rpmGauge(last.rpm);
      $('v1ectbar').style.width = Math.max(0, Math.min(100, ((last.ect || 20) - 20))) + '%';
      ['stft1', 'ltft1', 'stft2', 'ltft2'].forEach(function (k) { trimTag('t1' + k, last[k]); biBar('b1' + k, last[k]); });
      trend($('c1maf'), [{ id: 'maf', color: PAL.cyan }], [0, 60]);
      trend($('c1volts'), [{ id: 'volts', color: PAL.amber }], [12, 15]);
      trend($('c1trims'), [{ id: 'stft1', color: PAL.cyan }, { id: 'ltft1', color: PAL.cyan, dash: [6, 4] }, { id: 'stft2', color: PAL.amber }, { id: 'ltft2', color: PAL.amber, dash: [6, 4] }], [-25, 25]);
    } else if (view === 'v2') {
      $('rail').innerHTML = CH.map(function (c) {
        var b = buf[c.id].map(function (p) { return p.v; }), mn = b.length ? Math.min.apply(null, b) : null, mx = b.length ? Math.max.apply(null, b) : null;
        return '<div class="row"><span style="width:10px;height:10px;border-radius:2px;background:' + (c.id.slice(-1) === '2' ? PAL.amber : PAL.cyan) + ';align-self:center"></span><span>' + c.name +
          '</span><span class="v">' + fmt(last[c.id], c.dp) + ' <span class="unit">' + c.unit + '</span></span><span class="mm">min ' + fmt(mn, c.dp) + ' · max ' + fmt(mx, c.dp) + '</span></div>';
      }).join('');
      trend($('s_rpm'), [{ id: 'rpm', color: PAL.cyan }], [0, 4000]);
      trend($('s_trim'), [{ id: 'stft1', color: PAL.cyan }, { id: 'ltft1', color: PAL.cyan, dash: [6, 4] }, { id: 'stft2', color: PAL.amber }, { id: 'ltft2', color: PAL.amber, dash: [6, 4] }], [-25, 25]);
      trend($('s_air'), [{ id: 'maf', color: PAL.cyan }, { id: 'ect', color: PAL.amber, dash: [6, 4] }], [0, 100]);
      trend($('s_volt'), [{ id: 'volts', color: PAL.cyan }], [12, 15]);
    } else {
      var inr = last.rpm !== null && last.rpm > 2300 && last.rpm < 2700;
      $('v3band').textContent = inr ? 'in range 2300–2700' : 'target 2300–2700';
      $('v3band').className = 'tag ' + (inr ? 'ok' : '');
      $('v3rpm').textContent = fmt(last.rpm, 0); $('v3ltft1').textContent = fmt(last.ltft1, 1);
      $('v3ltft2').textContent = fmt(last.ltft2, 1); $('v3ect').textContent = fmt(last.ect, 0);
      trend($('c3'), [{ id: 'rpm', color: PAL.mute, width: 1.5 }], [0, 4000], { band: [2300, 2700] });
    }
  }

  /* ---------- talking to the server ---------- */
  function post(path, body) {
    return fetch(api(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); });
  }
  function poll() {
    fetch(api('/api/state?after=' + lastSeq))
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (st) { ingest(st); render(); })
      .catch(function () { state = { status: 'disconnected' }; chips(); });
  }
  $('pause').addEventListener('click', function () {
    var running = state && state.status === 'running';
    post(running ? '/api/stop' : '/api/start', running ? {} : { pids: PIDS, hz: 2.5, seconds: 600 })
      .then(function (r) { if (!r.ok) showMsg(r.j.error || 'request failed'); poll(); });
  });
  $('save').addEventListener('click', function () {
    var b = $('save');
    post('/api/save', { label: 'run' }).then(function (r) {
      b.textContent = r.ok ? 'Saved ' + r.j.path.split('/').pop() : (r.j.error || 'nothing to save');
      setTimeout(function () { b.textContent = 'Save run'; }, 2500);
    });
  });
  $('scenario').addEventListener('change', function (e) { post('/api/sim', { scenario: e.target.value }); results = {}; renderResults(); });
  $('rev').addEventListener('click', function () {
    var on = $('rev').textContent.indexOf('Rev') === 0;
    post('/api/sim', { rev: on }).then(function () {
      $('rev').textContent = on ? 'Release throttle (sim)' : 'Rev to 2500 rpm (sim)';
      events.push({ t: tNow, label: on ? 'rev' : 'release' }); if (events.length > 8) events.shift();
    });
  });
  $('go_idle').addEventListener('click', function () { startCap('idle'); });
  $('go_rev').addEventListener('click', function () { startCap('rev'); });

  var btns = document.querySelectorAll('.vbtn'), views = document.querySelectorAll('.view');
  function show(id) {
    Array.prototype.forEach.call(btns, function (b) { b.classList.toggle('is-active', b.dataset.view === id); });
    Array.prototype.forEach.call(views, function (v) { v.classList.toggle('is-active', v.id === id); });
    render();
  }
  Array.prototype.forEach.call(btns, function (b) { b.addEventListener('click', function () { show(b.dataset.view); history.replaceState(null, '', location.search + '#' + b.dataset.view); }); });
  var init = (location.hash || '').replace('#', ''); if (init && $(init)) show(init);

  Array.prototype.forEach.call(document.querySelectorAll('#strips .card'), function (card) {
    var cv = card.querySelector('canvas'), cur = card.querySelector('.cursor'), tip = card.querySelector('.tip');
    card.addEventListener('mousemove', function (e) {
      var r = cv.getBoundingClientRect(), x = e.clientX - r.left, l = 40, iw = r.width - 48;
      if (x < l || x > l + iw) { cur.style.display = tip.style.display = 'none'; return; }
      var t = tNow - (1 - (x - l) / iw) * SPAN, id = cv.id;
      var parts = id === 's_rpm' ? ['rpm'] : id === 's_trim' ? ['stft1', 'ltft1', 'stft2', 'ltft2'] : id === 's_air' ? ['maf', 'ect'] : ['volts'];
      var lines = parts.map(function (p) {
        var c = CH.filter(function (q) { return q.id === p; })[0], b = buf[p], best = null;
        b.forEach(function (s) { if (best === null || Math.abs(s.t - t) < Math.abs(best.t - t)) best = s; });
        return best ? c.name + ' ' + fmt(best.v, c.dp) + ' ' + c.unit : null;
      }).filter(Boolean);
      if (!lines.length) { cur.style.display = tip.style.display = 'none'; return; }
      cur.style.display = tip.style.display = 'block'; cur.style.left = (x + 10) + 'px'; tip.style.left = Math.min(x + 20, r.width - 150) + 'px';
      tip.innerHTML = lines.join('<br>');
    });
    card.addEventListener('mouseleave', function () { cur.style.display = tip.style.display = 'none'; });
  });

  renderResults(); render();
  window.addEventListener('resize', render);
  setInterval(poll, 400);
  poll();
})();
</script>
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider 2>&1 | tail -3`
Expected: everything passes. If `test_inline_script_parses` fails, `node --check` prints the line; fix the script (usually a stray quote from the edits above).

- [ ] **Step 5: Visual check with the demo server (no hardware, ask nobody)** — after Task 6 exists, run `console --demo` and screenshot each layout with headless Chrome (see Task 7 Step 2). If Task 6 is not yet done, defer this check to Task 7.

---

### Task 6: CLI `console`, MCP tools `open_console` / `console_data`, docs

**Files:**
- Modify: `src/obd_reader/console.py` (add `ConsoleService`), `src/obd_reader/__main__.py`, `src/obd_reader/tools.py`, `tests/conftest.py`, `tests/test_tools_live.py`, `tests/test_mcp_server.py`, `docs/design.md`, `README.md`
- Test: `tests/test_console_tools.py`

**Interfaces:**
- Produces:
  - `console.ConsoleService(session, *, demo: bool = False, host="127.0.0.1", http_port=0, allow_lan=False)` with `.ensure() -> ConsoleServer` (creates hub + server once; demo uses a private `Session` whose port factory returns one shared `SimPort`), `.hub`, `.server`, `.stop()`.
  - CLI: `shadetree-ai console [--port PATH | --demo] [--scenario S] [--http-port N] [--host H --allow-lan] [--seconds N] [--no-start]` prints `console: <url>` and blocks until Ctrl-C. Function `console_main(args, block: bool = True) -> ConsoleService`.
  - Tools (registered read-only): `open_console(demo: bool = False, start: bool = True) -> {"url", "status", "demo"}` and `console_data(seconds: float = 30) -> {"status", "message", "seq", "channels": hub.recent(seconds)}`. `LIVE_TOOLS` gains both; `TOOL_NAMES` has 17 names.

- [ ] **Step 1: Update the literal tool list first (test-first)** — in `tests/conftest.py` add `"open_console"` and `"console_data"` to `REVIEWED_TOOLS`; in `tests/test_tools_live.py` change `assert len(TOOL_NAMES) == 15` to `== 17`; in `tests/test_mcp_server.py` nothing else changes (it compares against `REVIEWED_TOOLS`).

- [ ] **Step 2: Write the failing tests** — create `tests/test_console_tools.py`:

```python
import http.client
import json
import time

import pytest

from obd_reader.console import ConsoleService
from obd_reader.session import AdapterBusy, Config, NoAdapterError, Session
from obd_reader.simulator import SimPort
from obd_reader.tools import build_tools

from conftest import ScriptedPort


def demo_session(tmp_path):
    return Session(Config(port=None, home=tmp_path))


def get_state(url):
    host_port = url.split("//")[1].split("/")[0]
    token = url.split("t=")[1]
    c = http.client.HTTPConnection(host_port, timeout=5)
    c.request("GET", f"/api/state?t={token}", headers={"Host": host_port})
    r = c.getresponse()
    data = json.loads(r.read())
    c.close()
    return data


def wait_seq(url, n):
    end = time.monotonic() + 6
    while time.monotonic() < end:
        if get_state(url)["seq"] >= n:
            return True
        time.sleep(0.03)
    return False


def test_open_console_demo_starts_the_server_and_sampling(tmp_path):
    tl = build_tools(demo_session(tmp_path))
    out = tl["open_console"](demo=True)
    try:
        assert out["demo"] is True and out["url"].startswith("http://127.0.0.1:") and "t=" in out["url"]
        assert wait_seq(out["url"], 3)
        assert tl["open_console"](demo=True)["url"] == out["url"]  # same server, not a second one
    finally:
        ConsoleService.shutdown_all()


def test_console_data_matches_what_the_page_sees(tmp_path):  # Review Focus 5
    tl = build_tools(demo_session(tmp_path))
    out = tl["open_console"](demo=True)
    try:
        assert wait_seq(out["url"], 8)
        data = tl["console_data"](seconds=30)
        st = get_state(out["url"])
        assert data["status"] == "running" and data["seq"] <= st["seq"]
        assert data["channels"]["0C"]["name"] == "engine_rpm" and data["channels"]["0C"]["stats"]["n"] >= 8
        assert set(data["channels"]) == {"0C", "05", "06", "07", "08", "09", "10", "42"}
    finally:
        ConsoleService.shutdown_all()


def test_other_live_tools_are_refused_while_the_console_samples(tmp_path):  # Review Focus 5
    # a real (non-demo) session whose adapter is the console's: read_pid must not interleave bytes
    sim = SimPort("healthy")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    svc = ConsoleService(s)
    try:
        svc.ensure()
        svc.hub.start(["0C"], hz=10, seconds=30)
        end = time.monotonic() + 5
        while svc.hub.state()["seq"] < 2 and time.monotonic() < end:
            time.sleep(0.02)
        with pytest.raises(AdapterBusy) as e:
            build_tools(s)["read_pid"]("0C")
        assert "console_data" in str(e.value)
    finally:
        svc.stop()


def test_open_console_without_an_adapter_or_demo_is_a_clear_error(tmp_path):
    tl = build_tools(demo_session(tmp_path))
    with pytest.raises(NoAdapterError):
        tl["open_console"](demo=False)


def test_console_data_before_opening_says_so(tmp_path):
    tl = build_tools(demo_session(tmp_path))
    out = tl["console_data"](seconds=10)
    assert out["status"] == "idle" and "open_console" in out["message"]


def test_console_data_rejects_silly_windows(tmp_path):
    tl = build_tools(demo_session(tmp_path))
    for bad in (0, -5, 1e9, float("nan")):
        with pytest.raises(ValueError):
            tl["console_data"](seconds=bad)


def test_cli_console_demo_builds_a_working_service(tmp_path):
    from obd_reader.__main__ import build_parser, console_main

    args = build_parser().parse_args(["console", "--demo", "--http-port", "0", "--scenario", "lean"])
    svc = console_main(args, block=False)
    try:
        assert wait_seq(svc.server.url, 3)
        assert svc.hub.state()["demo"] is True
    finally:
        svc.stop()
```

- [ ] **Step 3: Run to verify failure**

Run: `timeout 60 .venv/bin/python -m pytest tests/test_console_tools.py tests/test_tools_live.py tests/test_mcp_server.py -q --tb=line -p no:cacheprovider 2>&1 | grep -E "ImportError|Error|passed|failed" | head -5`
Expected: `ImportError` for `ConsoleService` / `build_parser`, and the tool-name tests fail (15 tools vs the updated literal set).

- [ ] **Step 4: Implement `ConsoleService`** — append to `src/obd_reader/console.py`:

```python
import weakref

from obd_reader.hub import DEFAULT_PIDS
from obd_reader.session import Config, Session
from obd_reader.simulator import SimPort

_services: "weakref.WeakSet[ConsoleService]" = weakref.WeakSet()


class ConsoleService:
    """Owns one hub and one server for a Session (or a private simulated one for --demo)."""

    def __init__(self, session: Session, *, demo: bool = False, host: str = "127.0.0.1",
                 http_port: int = 0, allow_lan: bool = False, scenario: str = "rich"):
        self.demo, self._host, self._port, self._lan, self._scenario = demo, host, http_port, allow_lan, scenario
        self._session = session
        self.hub: LiveHub | None = None
        self.server: ConsoleServer | None = None
        _services.add(self)

    def ensure(self) -> ConsoleServer:
        if self.server is not None:
            return self.server
        if self.demo:
            sim = SimPort(self._scenario)
            session = Session(Config(port="sim", home=self._session.config.home, timeout=1.0),
                              port_factory=lambda: sim)
            self.hub = LiveHub(session, sim=sim)
        else:
            if not self._session.config.port:
                raise NoAdapterError("SHADETREE_PORT is not set; use demo=True to try the console without a car")
            self.hub = LiveHub(self._session)
        self.server = ConsoleServer(self.hub, host=self._host, port=self._port, allow_lan=self._lan)
        self.server.start()
        return self.server

    def start_sampling(self, pids: list[str] | None = None, hz: float = 2.5, seconds: float = 600.0) -> None:
        self.ensure()
        if not self.hub.running:
            self.hub.start(pids or DEFAULT_PIDS, hz=hz, seconds=seconds)

    def stop(self) -> None:
        if self.hub is not None:
            self.hub.stop()
        if self.server is not None:
            self.server.stop()
        self.hub = self.server = None

    @staticmethod
    def shutdown_all() -> None:
        for svc in list(_services):
            svc.stop()
```

- [ ] **Step 5: Implement the CLI** — in `src/obd_reader/__main__.py`: split parser construction out of `main` into `build_parser()` (return the `ArgumentParser`; `main` calls it), add a `console` subparser and `console_main`:

```python
def console_main(args, block: bool = True):
    from obd_reader.console import ConsoleService
    from obd_reader.session import Config, Session

    session = Session(Config(port=args.port, home=args.out_dir))
    svc = ConsoleService(session, demo=args.demo, host=args.host, http_port=args.http_port,
                         allow_lan=args.allow_lan, scenario=args.scenario)
    server = svc.ensure()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("warning: the console is reachable from your network; anyone with the link can watch live data", file=sys.stderr)
    if not args.no_start:
        svc.start_sampling(seconds=args.seconds)
    print(f"console: {server.url}", flush=True)
    if block:
        try:
            import time
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            svc.stop()
    return svc
```

and register the subparser in `build_parser`:

```python
    co = sub.add_parser("console", help="open the live console web page (read-only)")
    co.add_argument("--port", default=None, help="adapter serial device (not needed with --demo)")
    co.add_argument("--demo", action="store_true", help="use the built-in simulated car instead of an adapter")
    co.add_argument("--scenario", default="rich", choices=["healthy", "rich", "lean"], help="demo scenario")
    co.add_argument("--http-port", type=int, default=8765, help="local web port (0 = any free port)")
    co.add_argument("--host", default="127.0.0.1", help="bind address (non-loopback needs --allow-lan)")
    co.add_argument("--allow-lan", action="store_true", help="allow binding a non-loopback address")
    co.add_argument("--seconds", type=float, default=600.0, help="auto-stop after this many seconds")
    co.add_argument("--no-start", action="store_true", help="open the page without starting sampling")
    co.add_argument("--out-dir", type=Path, default=Path("."), help="runs/ and transcripts/ go here")
    co.set_defaults(func=lambda a: (console_main(a), 0)[1])
```

- [ ] **Step 6: Implement the tools** — in `src/obd_reader/tools.py`: set `LIVE_TOOLS = frozenset({"adapter_info", "scan", "read_pid", "live_data", "trim_summary", "mode06_tests", "open_console", "console_data"})`; import `ConsoleService`; inside `build_tools` create `svc: dict = {"real": None, "demo": None}` and add:

```python
    def _service(demo: bool) -> ConsoleService:
        key = "demo" if demo else "real"
        if svc[key] is None:
            svc[key] = ConsoleService(session, demo=demo)
        return svc[key]

    def open_console(demo: bool = False, start: bool = True) -> dict:
        """Start the live console web page (local, token-protected, read-only) and return its URL. demo=True uses a simulated car."""
        service = _service(bool(demo))
        server = service.ensure()
        if start:
            service.start_sampling()
        return {"url": server.url, "status": service.hub.state()["status"], "demo": bool(demo)}

    def console_data(seconds: float = 30) -> dict:
        """Latest values and exact statistics over the last N seconds from the console's sampler (what the page shows)."""
        if not (isinstance(seconds, (int, float)) and math.isfinite(seconds) and 0 < seconds <= 600):
            raise ValueError("seconds must be in (0, 600]")
        service = svc["real"] if svc["real"] is not None and svc["real"].hub is not None else svc["demo"]
        if service is None or service.hub is None:
            return {"status": "idle", "message": "the console is not open; call open_console first", "channels": {}}
        st = service.hub.state()
        return {"status": st["status"], "message": st["message"], "seq": st["seq"],
                "channels": service.hub.recent(seconds)}
```

(add `import math`), and append `open_console, console_data` to the tuple returned by `build_tools`. `console_data` is documented as not touching the adapter.

- [ ] **Step 7: Docs** — `README.md`: a "Live console" section (`shadetree-ai console --demo` to try it, `--port` for a real adapter, tablet access with `--host <lan-ip> --allow-lan`, the read-only and token notes) and change "15 read-only tools" to 17. `docs/design.md`: add `## 7b. Live console` (one paragraph on the hub/server/page split, the three layouts, the security rules from Global Constraints) and add `open_console` and `console_data` to the §7 table.

- [ ] **Step 8: Run to verify pass, then commit batch C**

Run: `timeout 240 .venv/bin/python -m pytest -q --tb=short -p no:cacheprovider 2>&1 | tail -4`
Expected: everything passes.

```bash
git add src/obd_reader/console.py src/obd_reader/__main__.py src/obd_reader/tools.py src/obd_reader/web/console.html tests/conftest.py tests/test_tools_live.py tests/test_mcp_server.py tests/test_console_page.py tests/test_console_tools.py docs/design.md README.md
git commit -m "feat: live console page (3 layouts), CLI, and MCP tools open_console/console_data (batch C)"
```

---

### Task 7: Visual and hardware verification

**Files:** none (fix bugs found, each with a test)

- [ ] **Step 1: Demo server smoke** — run `.venv/bin/python -m obd_reader console --demo --http-port 0 --seconds 120 > /tmp/claude-1000/.../console.out &`, read the printed URL from the file, and `curl -s "<url>"` for the page and `curl -s "<url minus path>/api/state?t=<token>"` for JSON. Expected: HTTP 200 and `"status": "running"`, `"demo": true`, growing `seq`.

- [ ] **Step 2: Screenshots of all three layouts** — with headless Chrome (`google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=1320,1150 --virtual-time-budget=12000 --screenshot=<file> "<url>#v1"`, then `#v2`, `#v3`), read each image and compare with `docs/mocks/console-mock.html`. Fix any layout bug (chart height, gauge clipping, axis labels) and add a page test where a test can catch it. Note: virtual time makes the polling advance in fast-forward; use `--virtual-time-budget=12000` so a few seconds of data exist.

- [ ] **Step 3: Ask Neil** for permission to run the console against the OBDLink EX on the bench with NO car attached (expected: status `stopped`, message about no data within about 3 sweeps, adapter chip shown, lock released, no crash). Do not run it without a yes.

- [ ] **Step 4: Ask Neil to run it on the Ridgeline** (ignition on, engine off, then engine running with the car parked): `shadetree-ai console --port <EX path>`. Check that layouts A, B and C update with real values, that "Save run" writes `runs/*.json`, and that `open_console`/`console_data` work from Claude Code through the MCP server.

---

## Self-Review (done)

- **Spec coverage:** all three approved layouts (A Cockpit, B Scope, C Guided test) are in Task 5 from the reviewed mock; the shared sampler (Task 3), server and security rules (Task 4), simulator for demo and tests (Task 2), CLI and MCP bridge (Task 6), verification (Task 7). Not covered by design (later): PID picker, MCP Apps wrapper, playbooks driving layout C from the reference store, saving a run into `Snapshot.live_sample`.
- **Placeholders:** none. Task 4 uses a placeholder page on purpose and Task 5 replaces it.
- **Type consistency:** `LiveHub.state()` keys, `read_pid_value`, `DEFAULT_PIDS`, `ConsoleServer`, `ConsoleService`, `REVIEWED_TOOLS` names are used identically across tasks. Front-end channel ids (`rpm, ect, stft1, ltft1, stft2, ltft2, maf, volts`) map to PIDs `0C 05 06 07 08 09 10 42` in one table.
- **Known limits:** about 2–5 sweeps per second on a 115200-baud adapter with 8 PIDs; the guided test playbook is hard-coded (draft, unreviewed) until the reference store exists; `--allow-lan` exposes live data to anyone with the link.
