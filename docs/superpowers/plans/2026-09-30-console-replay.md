# Console Replay Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay a saved run in the console UI with play, pause, speed, scrubber and restart, loading runs from `runs/` or an in-memory upload, and make Save run store codes, Mode 06 and the partial car key so future replays show them.

**Architecture:** `replay_run.py` validates an untrusted run file into a `Run` (sweeps grouped by timestamp). `LiveHub` gains a replay mode: a player thread publishes sweeps into the same buffers the sampler uses, so state, page, tools and tiles work unchanged. Three server routes list, load and control replays; the page gets a Replay panel, a transport bar and a banner.

**Tech Stack:** Python 3.11 stdlib, pytest, the one-file page `web/console.html`, the Node fake-DOM test `tests/js/page_logic_test.js`.

**Spec:** `docs/superpowers/specs/2026-09-30-console-replay-design.md`

## Global Constraints

- Replay never opens the Session, the transport or the adapter; `allowlist.py` and `transport.py` are not touched. No route accepts a command string.
- A replay writes nothing to disk (no autosave, no Save run). An uploaded run lives in memory only.
- Uploads are untrusted: at most 64 readings, 600,000 samples, 86,400 s, 8 MB, reading ids `[0-9A-F]{2}`, finite numbers, names and units at most 80 characters. Only whitelisted optional fields survive.
- Run names used as paths must match `[A-Za-z0-9T:_.-]{1,100}\.json`, be regular files (no symlink) that resolve inside `runs/`.
- The page keeps exactly one `<script>` block; every run, file and adapter string reaches the DOM through `textContent` only.
- Public repo: no VIN, real snapshot or transcript in any test or fixture; the partial key (10 characters) is the only car identifier a run file may hold. Tests build any VIN with `obd_reader.vin.with_check_digit`.
- Stage files by name; commit per task; do not merge or push until Neil says so. Match surrounding style, no new dependencies.

## Review Focus

- Seeking backward must reset the page cleanly (new run id, seq restarts) and never leave stale samples. Pinned in Task 2.
- A run uploaded or listed with a hostile name or a traversal name must never read outside `runs/` or inject markup. Pinned in Tasks 1, 3 and 4.
- A file with NaN, huge or malformed samples must fail with a plain 400, never hang or crash the server. Pinned in Tasks 1 and 3.
- Loading a replay during live sampling, or starting live sampling during a replay, must be refused and must not disturb the running source. Pinned in Task 2.
- `console_data` must say its numbers are a replay so Claude cannot mistake them for the car. Pinned in Task 3.

## File Structure

- Create `src/obd_reader/replay_run.py`: `Run`, `load_run`, `read_run_file`, `list_runs`, limits.
- Modify `src/obd_reader/hub.py` (replay mode, `runs_dir`, richer saved runs), `src/obd_reader/console.py` (routes, per-route body cap), `src/obd_reader/tools.py` (`console_data` source), `src/obd_reader/web/console.html`, `README.md`, `docs/design.md`.
- Tests: create `tests/test_replay_run.py`; add to `tests/test_hub.py`, `tests/test_console.py`, `tests/test_console_tools.py`, `tests/test_console_page.py`, `tests/js/page_logic_test.js`.

Run tests from the repo (or worktree) root: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q`; Node test: `node tests/js/page_logic_test.js src/obd_reader/web/console.html`.

---

### Task 1: Run loader (`replay_run.py`)

**Files:**
- Create: `src/obd_reader/replay_run.py`, `tests/test_replay_run.py`

**Interfaces:**
- Produces: `Run` (frozen dataclass): `duration: float`, `rate_hz: float`, `protocol: str | None`, `names: dict[str, tuple[str, str | None]]`, `sweeps: list[tuple[float, dict[str, float]]]` sorted by time, `codes: dict | None`, `mode06: dict | None`, `vehicle: dict | None`, `times: list[float]`; methods `index_after(pos) -> int` (first sweep index with time > pos) and `first_in_window(pos, span) -> int` (first sweep index with time >= pos - span).
- Produces: `load_run(obj) -> Run` (raises `ValueError` with a plain message); `read_run_file(runs_dir, name) -> dict` (raises `ValueError` for a bad name or file, `FileNotFoundError` when missing); `list_runs(runs_dir) -> list[{"name", "size", "duration"}]` newest first, at most 50; constants `MAX_FILE_BYTES = 8 * 1024 * 1024`, `MAX_LISTED = 50`.
- Optional-field shapes produced (same as `LiveHub.state()`): `codes = {"read": bool, "note": str | None, "stored": [...], "pending": [...], "permanent": [...], "mil": bool}` with items `{"code", "desc", "hint", "known"}`; `mode06 = {"read": True, "note": None, "mids": [...], "results": [...]}`; `vehicle = {"key": str, "known": False, "runs": 0, "note": None}`.

- [ ] **Step 1: Write the failing tests** (`tests/test_replay_run.py`)

```python
import copy
import json
import os

import pytest

from obd_reader import replay_run as rr


def run_obj():
    return {"kind": "live_run", "demo": False, "adapter": {"protocol": "ISO 15765-4 (CAN 29/500)"},
            "live_sample": {"duration_s": 1.2, "rate_hz": 2.5, "series": {
                "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[0.4, 700], [0.8, 720], [1.2, 710]]},
                "05": {"name": "coolant_temp", "unit": "C", "samples": [[0.4, 80], [0.8, 81], [1.2, 82]]}}}}


def test_a_good_run_loads_and_groups_samples_into_sweeps():
    r = rr.load_run(run_obj())
    assert r.duration == 1.2 and r.rate_hz == 2.5 and r.protocol == "ISO 15765-4 (CAN 29/500)"
    assert r.sweeps[0] == (0.4, {"0C": 700.0, "05": 80.0}) and len(r.sweeps) == 3
    assert r.names["0C"] == ("engine_rpm", "rpm")
    assert r.codes is None and r.mode06 is None and r.vehicle is None


def test_readings_sampled_at_different_times_still_group_by_timestamp():
    o = run_obj()
    o["live_sample"]["series"]["05"]["samples"] = [[0.4, 80], [1.2, 82]]
    r = rr.load_run(o)
    assert r.sweeps[1] == (0.8, {"0C": 720.0}) and r.sweeps[2][1] == {"0C": 710.0, "05": 82.0}


def test_window_and_index_helpers():
    r = rr.load_run(run_obj())
    assert r.index_after(0.0) == 0 and r.index_after(0.8) == 2 and r.index_after(5.0) == 3
    assert r.first_in_window(1.2, 0.5) == 1 and r.first_in_window(1.2, 60) == 0


def _bad(mutate):
    o = run_obj()
    mutate(o)
    return o


BAD = {
    "wrong kind": _bad(lambda o: o.update(kind="snapshot")),
    "not a dict": [],
    "no series": _bad(lambda o: o["live_sample"].update(series={})),
    "bad reading id": _bad(lambda o: o["live_sample"]["series"].update({"zz": {"name": "x", "unit": None, "samples": [[1, 1]]}})),
    "lowercase id": _bad(lambda o: o["live_sample"]["series"].update({"0c": {"name": "x", "unit": None, "samples": [[1, 1]]}})),
    "nan value": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([2.0, float("nan")])),
    "inf time": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([float("inf"), 1])),
    "bool value": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([2.0, True])),
    "negative time": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([-1, 1])),
    "time too large": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([86401, 1])),
    "bad pair": _bad(lambda o: o["live_sample"]["series"]["0C"]["samples"].append([1, 2, 3])),
    "long name": _bad(lambda o: o["live_sample"]["series"]["0C"].update(name="x" * 81)),
    "no samples": _bad(lambda o: [s.update(samples=[]) for s in o["live_sample"]["series"].values()]),
    "too many readings": _bad(lambda o: o["live_sample"].update(series={f"{i:02X}": {"name": "x", "unit": None, "samples": [[1, 1]]} for i in range(65)})),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_malformed_runs_are_rejected_with_a_message(name):
    with pytest.raises(ValueError):
        rr.load_run(copy.deepcopy(BAD[name]))


def test_too_many_samples_are_rejected(monkeypatch):
    monkeypatch.setattr(rr, "MAX_SAMPLES", 5)
    with pytest.raises(ValueError, match="too many"):
        rr.load_run(run_obj())


def test_optional_fields_are_whitelisted_and_bad_ones_dropped():
    o = run_obj()
    o["codes"] = {"read": True, "note": None, "mil": True, "extra": "x",
                  "stored": [{"code": "P0117", "desc": "d", "hint": "h", "known": True, "junk": 1}], "pending": [], "permanent": []}
    o["mode06"] = {"read": True, "mids": ["3A"], "results": [{"mid": "3A", "tid": "01", "uasid": "10", "value": 1, "minimum": 0, "maximum": 5, "within_limits": True}]}
    o["vehicle"] = {"key": "9SXSMUL1-T", "vin": "SHOULD-NOT-SURVIVE"}
    r = rr.load_run(o)
    assert r.codes == {"read": True, "note": None, "stored": [{"code": "P0117", "desc": "d", "hint": "h", "known": True}],
                       "pending": [], "permanent": [], "mil": True}
    assert r.mode06["results"][0] == {"mid": "3A", "tid": "01", "uasid": "10", "value": 1, "minimum": 0, "maximum": 5, "within_limits": True}
    assert r.vehicle == {"key": "9SXSMUL1-T", "known": False, "runs": 0, "note": None}
    o["codes"]["stored"][0]["code"] = "not a code"
    o["mode06"]["results"][0]["value"] = "x"
    o["vehicle"]["key"] = "lowercase-key"
    r = rr.load_run(o)
    assert r.codes is None and r.mode06 is None and r.vehicle is None


def _put(d, name, obj, mtime=None):
    p = d / name
    p.write_text(json.dumps(obj))
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def test_read_run_file_accepts_only_plain_names_inside_the_folder(tmp_path):
    _put(tmp_path, "a-run.json", run_obj())
    assert rr.read_run_file(tmp_path, "a-run.json")["kind"] == "live_run"
    for bad in ("../a-run.json", "a/b.json", "", "a-run.txt", "x" * 101 + ".json", None, 5):
        with pytest.raises(ValueError):
            rr.read_run_file(tmp_path, bad)
    with pytest.raises(FileNotFoundError):
        rr.read_run_file(tmp_path, "missing.json")


def test_symlinks_and_oversize_files_are_refused(tmp_path, monkeypatch):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(run_obj()))
    d = tmp_path / "runs"
    d.mkdir()
    (d / "link.json").symlink_to(outside)
    with pytest.raises(FileNotFoundError):
        rr.read_run_file(d, "link.json")
    _put(d, "big.json", run_obj())
    monkeypatch.setattr(rr, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="too large"):
        rr.read_run_file(d, "big.json")


def test_list_runs_is_newest_first_skips_invalid_files_and_caps_at_fifty(tmp_path):
    _put(tmp_path, "old.json", run_obj(), 1000)
    _put(tmp_path, "new.json", run_obj(), 2000)
    _put(tmp_path, "snap.json", {"kind": "snapshot"}, 3000)
    (tmp_path / "broken.json").write_text("{nope")
    (tmp_path / "notes.txt").write_text("x")
    out = rr.list_runs(tmp_path)
    assert [r["name"] for r in out] == ["new.json", "old.json"]
    assert out[0]["duration"] == 1.2 and out[0]["size"] > 0
    for i in range(60):
        _put(tmp_path, f"r{i:02d}.json", run_obj(), 5000 + i)
    assert len(rr.list_runs(tmp_path)) == 50
    assert rr.list_runs(tmp_path / "nope") == []
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_replay_run.py -q`
Expected: collection error `ModuleNotFoundError: obd_reader.replay_run`.

- [ ] **Step 3: Write `src/obd_reader/replay_run.py`**

```python
"""Load a saved run for replay. A run file is untrusted input (it may be uploaded): every field is checked,
bounded and copied; nothing from it is executed or used as a path."""
import bisect
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from obd_reader.profiles import KEY_RE

MAX_SERIES, MAX_SAMPLES, MAX_DURATION, MAX_TEXT = 64, 600_000, 86_400.0, 80
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_LISTED = 50
_HEX2 = re.compile(r"[0-9A-F]{2}")
_NAME = re.compile(r"[A-Za-z0-9T:_.-]{1,100}\.json")
_CODE = re.compile(r"[PCBU][0-9A-F]{4}")


@dataclass(frozen=True)
class Run:
    duration: float
    rate_hz: float
    protocol: str | None
    names: dict
    sweeps: list
    codes: dict | None = None
    mode06: dict | None = None
    vehicle: dict | None = None
    times: list = field(default_factory=list)

    def index_after(self, pos: float) -> int:
        return bisect.bisect_right(self.times, pos)

    def first_in_window(self, pos: float, span: float) -> int:
        return bisect.bisect_left(self.times, pos - span)


def _num(x) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError("samples must be finite numbers")
    return float(x)


def _text(x, allow_none: bool = False):
    if x is None and allow_none:
        return None
    if not isinstance(x, str) or len(x) > MAX_TEXT:
        raise ValueError("a name or unit is missing or longer than 80 characters")
    return x


def _short(x) -> str:
    return x if isinstance(x, str) and len(x) <= 200 else ""


def _codes(c) -> dict | None:
    if not isinstance(c, dict):
        return None
    if c.get("read") is not True:
        n = c.get("note")
        return {"read": False, "note": n if isinstance(n, str) and len(n) <= 200 else None}
    out = {"read": True, "note": None}
    for k in ("stored", "pending", "permanent"):
        items = c.get(k)
        if not isinstance(items, list) or len(items) > 64:
            return None
        clean = []
        for it in items:
            if not (isinstance(it, dict) and isinstance(it.get("code"), str) and _CODE.fullmatch(it["code"])):
                return None
            clean.append({"code": it["code"], "desc": _short(it.get("desc")), "hint": _short(it.get("hint")), "known": it.get("known") is True})
        out[k] = clean
    out["mil"] = c.get("mil") is True
    return out


def _mode06(m) -> dict | None:
    if not isinstance(m, dict) or m.get("read") is not True:
        return None
    mids, res = m.get("mids"), m.get("results")
    if not (isinstance(mids, list) and isinstance(res, list)) or len(mids) > 64 or len(res) > 400:
        return None
    out = []
    for r in res:
        if not isinstance(r, dict):
            return None
        ids = [r.get(k) for k in ("mid", "tid", "uasid")]
        nums = [r.get(k) for k in ("value", "minimum", "maximum")]
        if not all(isinstance(x, str) and _HEX2.fullmatch(x) for x in ids) or not all(type(x) is int for x in nums):
            return None
        wl = r.get("within_limits")
        out.append({"mid": ids[0], "tid": ids[1], "uasid": ids[2], "value": nums[0], "minimum": nums[1], "maximum": nums[2],
                    "within_limits": wl if isinstance(wl, bool) else None})
    return {"read": True, "note": None, "mids": [x for x in mids if isinstance(x, str) and _HEX2.fullmatch(x)], "results": out}


def _vehicle(v) -> dict | None:
    key = v.get("key") if isinstance(v, dict) else None
    if isinstance(key, str) and KEY_RE.fullmatch(key):
        return {"key": key, "known": False, "runs": 0, "note": None}
    return None


def load_run(obj) -> Run:
    if not isinstance(obj, dict) or obj.get("kind") != "live_run":
        raise ValueError("not a saved run (kind must be live_run)")
    ls = obj.get("live_sample")
    series = ls.get("series") if isinstance(ls, dict) else None
    if not isinstance(series, dict) or not 1 <= len(series) <= MAX_SERIES:
        raise ValueError(f"a run needs 1 to {MAX_SERIES} readings")
    names, by_t, total = {}, {}, 0
    for pid, s in series.items():
        if not (isinstance(pid, str) and _HEX2.fullmatch(pid)):
            raise ValueError("reading ids must be two hex digits")
        if not isinstance(s, dict) or not isinstance(s.get("samples"), list):
            raise ValueError("a reading has no samples list")
        names[pid] = (_text(s.get("name")), _text(s.get("unit"), allow_none=True))
        total += len(s["samples"])
        if total > MAX_SAMPLES:
            raise ValueError("too many samples")
        for pair in s["samples"]:
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                raise ValueError("a sample must be [time, value]")
            t, v = _num(pair[0]), _num(pair[1])
            if not 0 <= t <= MAX_DURATION:
                raise ValueError("a sample time is out of range")
            by_t.setdefault(t, {})[pid] = v
    if not by_t:
        raise ValueError("the run has no samples")
    sweeps = sorted(by_t.items())
    ad = obj.get("adapter")
    proto = ad.get("protocol") if isinstance(ad, dict) else None
    rate = ls.get("rate_hz")
    return Run(duration=max(sweeps[-1][0], 0.1),
               rate_hz=float(rate) if isinstance(rate, (int, float)) and not isinstance(rate, bool) and math.isfinite(rate) and rate > 0 else 0.0,
               protocol=proto if isinstance(proto, str) and len(proto) <= MAX_TEXT else None,
               names=names, sweeps=sweeps, codes=_codes(obj.get("codes")), mode06=_mode06(obj.get("mode06")),
               vehicle=_vehicle(obj.get("vehicle")), times=[t for t, _ in sweeps])


def read_run_file(runs_dir, name) -> dict:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("not a run file name")
    d = Path(runs_dir)
    p = d / name
    if p.is_symlink() or not p.is_file():
        raise FileNotFoundError(name)
    if p.resolve().parent != d.resolve():
        raise ValueError("not a run file name")
    if p.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("file too large")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError("file is not valid JSON") from e


def list_runs(runs_dir) -> list[dict]:
    d = Path(runs_dir)
    try:
        files = [p for p in d.iterdir() if _NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
        files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    except OSError:
        return []
    out = []
    for p in files:
        if len(out) >= MAX_LISTED:
            break
        try:
            size = p.stat().st_size
            if size > MAX_FILE_BYTES:
                continue
            obj = json.loads(p.read_text(encoding="utf-8"))
            if obj.get("kind") != "live_run":
                continue
            dur = float(obj["live_sample"]["duration_s"])
            if not math.isfinite(dur) or dur < 0:
                continue
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        out.append({"name": p.name, "size": size, "duration": dur})
    return out
```

- [ ] **Step 4: Run, expect PASS**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_replay_run.py -q`
Expected: all pass. (If `test_a_good_run_loads...` fails on `r.codes is None`, check `_codes(None)` returns `None` for a non-dict.)

- [ ] **Step 5: Commit**

```bash
git add src/obd_reader/replay_run.py tests/test_replay_run.py
git commit -m "feat: validated loader for saved runs (untrusted input, bounded, sweeps grouped by time)"
```

---

### Task 2: Hub replay mode

**Files:**
- Modify: `src/obd_reader/hub.py`
- Test: `tests/test_hub.py`

**Interfaces:**
- Consumes: `Run` from Task 1.
- Produces on `LiveHub`: `start_replay(run: Run, name: str, playing: bool = True) -> None` (raises `HubBusy`), `replay_control(action: str, pos: float | None = None, speed: float | None = None) -> None` (actions `play|pause|restart|seek|speed`; raises `ValueError`), `exit_replay() -> None`, property `runs_dir -> Path`, internal `_replay_advance(dt: float) -> None` (advances the position by `dt * speed` and publishes sweeps, used by the player thread and by tests).
- `state()` gains `"replay": None | {"name", "duration", "pos", "speed", "playing", "ended"}`. During a replay: `status == "running"`, `demo is False`, `now == pos`, `adapter == {"chip": None, "ati": "replay", "protocol": run.protocol}`, `codes`/`mode06`/`vehicle` from the run (else `{"read": False, "note": "not stored in this run"}`-style defaults), `channels` for every reading in the run (readings the page's PID table does not know use the run's own name and unit).

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_hub.py` (it already defines `make`, `wait_for`, imports `json`, `time`, `pytest`, `HubBusy`, `LiveHub`, `Config`, `Session`, `SimPort`):

```python
from obd_reader.replay_run import load_run


def _run_obj(n=10, codes=None):
    ts = [round(0.4 * k, 3) for k in range(1, n + 1)]
    o = {"kind": "live_run", "demo": False, "adapter": {"protocol": "ISO 15765-4 (CAN 29/500)"},
         "live_sample": {"duration_s": ts[-1], "rate_hz": 2.5, "series": {
             "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[t, 700 + 10 * i] for i, t in enumerate(ts)]},
             "AB": {"name": "made_up", "unit": None, "samples": [[t, i] for i, t in enumerate(ts)]}}}}
    if codes:
        o["codes"] = codes
    return o


def _replay_hub(tmp_path, playing=False, **kw):
    hub, _, _ = make(tmp_path)
    hub.start_replay(load_run(_run_obj(**kw)), "drive.json", playing=playing)
    return hub


def test_replay_state_and_stepping_publish_sweeps(tmp_path):
    hub = _replay_hub(tmp_path)
    st = hub.state()
    assert st["status"] == "running" and st["demo"] is False and st["seq"] == 0
    assert st["replay"] == {"name": "drive.json", "duration": 4.0, "pos": 0.0, "speed": 1.0, "playing": False, "ended": False}
    assert st["adapter"] == {"chip": None, "ati": "replay", "protocol": "ISO 15765-4 (CAN 29/500)"}
    assert st["codes"] == {"read": False, "note": "not stored in this run"} and st["mode06"]["read"] is False
    hub._replay_advance(1.0)
    st = hub.state()
    assert st["seq"] == 2 and st["now"] == 1.0 and st["replay"]["pos"] == 1.0
    assert [s[2] for s in st["channels"]["0C"]["samples"]] == [700.0, 710.0]
    assert st["channels"]["AB"]["name"] == "made_up" and st["channels"]["0C"]["name"] == "engine_rpm"
    hub.exit_replay()


def test_speed_scales_the_advance_and_bad_values_are_refused(tmp_path):
    hub = _replay_hub(tmp_path)
    hub.replay_control("speed", speed=4)
    hub._replay_advance(0.5)
    assert hub.state()["replay"]["pos"] == 2.0 and hub.state()["replay"]["speed"] == 4.0
    for bad in (3, 0, -1, True, "fast", None):
        with pytest.raises(ValueError):
            hub.replay_control("speed", speed=bad)
    with pytest.raises(ValueError):
        hub.replay_control("explode")
    with pytest.raises(ValueError):
        hub.replay_control("seek", pos=float("nan"))
    hub.exit_replay()


def test_backward_seek_resets_the_page_and_refills_the_last_minute(tmp_path):
    hub = _replay_hub(tmp_path)
    hub._replay_advance(3.0)
    before = hub.state()
    hub.replay_control("seek", pos=1.0)
    st = hub.state()
    assert st["run"] != before["run"], "a new run id makes viewers drop their buffers"
    assert st["seq"] == 2 and st["now"] == 1.0 and [s[2] for s in st["channels"]["0C"]["samples"]] == [700.0, 710.0]
    assert st["replay"]["ended"] is False
    hub.exit_replay()


def test_play_pause_end_and_restart(tmp_path):
    hub = _replay_hub(tmp_path)
    hub.replay_control("play")
    assert hub.state()["replay"]["playing"] is True
    hub.replay_control("pause")
    hub._replay_advance(10.0)  # past the end
    r = hub.state()["replay"]
    assert r["pos"] == 4.0 and r["ended"] is True and r["playing"] is False and hub.state()["seq"] == 10
    hub.replay_control("play")  # from the end: starts over
    r = hub.state()["replay"]
    assert r["pos"] < 0.5 and r["ended"] is False and r["playing"] is True  # the player thread is running now, so not exactly 0
    hub.replay_control("restart")
    assert hub.state()["replay"]["pos"] < 0.5
    hub.exit_replay()


def test_the_player_thread_advances_while_playing_and_holds_when_paused(tmp_path):
    hub = _replay_hub(tmp_path, playing=True)
    hub.replay_control("speed", speed=8)
    assert wait_for(lambda: hub.state()["replay"]["ended"], 5)
    assert hub.state()["seq"] == 10
    hub.replay_control("restart")
    hub.replay_control("pause")
    seq = hub.state()["seq"]
    time.sleep(0.3)
    assert hub.state()["seq"] == seq
    hub.exit_replay()


def test_exit_returns_to_idle_and_stop_means_exit(tmp_path):
    hub = _replay_hub(tmp_path)
    hub._replay_advance(1.0)
    hub.stop()
    st = hub.state()
    assert st["status"] == "idle" and st["replay"] is None and st["seq"] == 0 and st["channels"] == {}
    assert not hub.running


def test_live_sampling_and_replay_exclude_each_other(tmp_path):
    hub = _replay_hub(tmp_path)
    with pytest.raises(HubBusy, match="replay"):
        hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    hub.exit_replay()
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["seq"] >= 2)
    with pytest.raises(HubBusy):
        hub.start_replay(load_run(_run_obj()), "x.json")
    assert hub.state()["status"] == "running" and hub.state()["replay"] is None
    hub.stop()


def test_loading_another_run_replaces_the_first(tmp_path):
    hub = _replay_hub(tmp_path)
    hub._replay_advance(1.0)
    hub.start_replay(load_run(_run_obj(n=5)), "second.json", playing=False)
    st = hub.state()
    assert st["replay"]["name"] == "second.json" and st["replay"]["duration"] == 2.0 and st["seq"] == 0
    hub.exit_replay()


def test_a_replay_never_writes_a_file_and_cannot_be_saved(tmp_path):
    sim = SimPort("rich")
    s = Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim)
    hub = LiveHub(s, sim=sim, autosave=True)
    hub.start_replay(load_run(_run_obj()), "drive.json", playing=False)
    hub._replay_advance(10.0)
    with pytest.raises(ValueError, match="replay"):
        hub.save_run("x")
    hub.exit_replay()
    assert not (tmp_path / "runs").exists()


def test_unsaved_live_run_is_not_silently_replaced_by_a_replay(tmp_path):
    hub, _, _ = make(tmp_path)
    hub._unsaved = True
    with pytest.raises(HubBusy, match="could not be saved"):
        hub.start_replay(load_run(_run_obj()), "x.json")
    hub.start_replay(load_run(_run_obj()), "x.json", playing=False)  # asking again discards it
    hub.exit_replay()


def test_codes_and_key_in_the_run_reach_the_state(tmp_path):
    codes = {"read": True, "note": None, "mil": True, "stored": [{"code": "P0117", "desc": "d", "hint": "h", "known": True}], "pending": [], "permanent": []}
    obj = _run_obj(codes=codes)
    obj["vehicle"] = {"key": "9SXSMUL1-T"}
    hub, _, _ = make(tmp_path)
    hub.start_replay(load_run(obj), "x.json", playing=False)
    st = hub.state()
    assert st["codes"]["stored"][0]["code"] == "P0117" and st["codes"]["mil"] is True
    assert st["vehicle"]["key"] == "9SXSMUL1-T"
    hub.exit_replay()
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_hub.py -q -k "replay or exclude or exit"`
Expected: FAIL (`AttributeError: 'LiveHub' object has no attribute 'start_replay'`).

- [ ] **Step 3: Implement in `src/obd_reader/hub.py`.**

(a) Add to the imports `from obd_reader.replay_run import Run` (place after the `from obd_reader.profiles import ProfileStore` line), and add near the other module constants:

```python
_SPEEDS = (0.5, 1.0, 2.0, 4.0, 8.0)
_REPLAY_TICK = 0.05
_REPLAY_WINDOW_S = 60.0
```

(b) In `_reset`, add as the last line of the method (indent 8): `self._replay: dict | None = None     # while a saved run is loaded: name, run, pos, speed, playing, ended, i`.

(c) Add after the `running` property:

```python
    @property
    def runs_dir(self) -> Path:
        return Path(self._s.config.home) / "runs"

    def _meta(self, p: str):
        d = PIDS.get(p)
        if d is not None:
            return d.name, d.unit, None if d.labels is None else {str(k): v for k, v in d.labels.items()}
        name, unit = (self._replay["run"].names.get(p) if self._replay else None) or (p, None)
        return name, unit, None
```

(d) In `start`, inside `with self._lock:` insert before `if self.running:`:

```python
            if self._replay is not None:
                raise HubBusy("a replay is loaded: exit it to sample live")
```

(e) At the top of `stop` insert:

```python
        if self._replay is not None:
            return self.exit_replay()
```

(f) Add these methods after `stop`:

```python
    def start_replay(self, run: Run, name: str, playing: bool = True) -> None:
        with self._lock:
            if self._replay is None and self.running:
                raise HubBusy("the console is already sampling; stop it first")
            if self._unsaved:
                self._unsaved = False
                raise HubBusy("the last run could not be saved and loading a replay clears it: press Save run, "
                              "or load again to discard it")
            if self._replay is not None:
                self._join_player()
            with self._data_lock:
                self._reset()
                self._run_id += 1
                self.status, self.hz = "running", (run.rate_hz or None)
                self._adapter = {"chip": None, "ati": "replay", "protocol": run.protocol}
                self._codes = run.codes or {"read": False, "note": "not stored in this run"}
                self._m06 = run.mode06 or {"read": False, "note": "not stored in this run", "mids": [], "results": []}
                self._vehicle = run.vehicle
                self._ch = {p: deque(maxlen=self._max) for p in run.names}
                self._replay = {"name": name, "run": run, "pos": 0.0, "speed": 1.0, "playing": bool(playing), "ended": False, "i": 0}
            self._stop.clear()
            self._thread = threading.Thread(target=self._replay_loop, daemon=True)
            self._thread.start()

    def _join_player(self) -> None:
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(5.0)

    def exit_replay(self) -> None:
        with self._lock:
            if self._replay is None:
                return
            self._join_player()
            with self._data_lock:
                self._reset()
                self._run_id += 1
            self._stop.clear()

    def _replay_loop(self) -> None:
        last = self._clock()
        while not self._stop.is_set():
            now = self._clock()
            dt, last = now - last, now
            with self._data_lock:
                rp = self._replay
                playing = rp is not None and rp["playing"]
            if playing:
                self._replay_advance(dt)
            self._stop.wait(_REPLAY_TICK)

    def _replay_advance(self, dt: float) -> None:
        with self._data_lock:
            rp = self._replay
            if rp is None:
                return
            run = rp["run"]
            rp["pos"] = min(run.duration, rp["pos"] + dt * rp["speed"])
            self._publish_until(rp)
            if rp["pos"] >= run.duration:
                rp["playing"], rp["ended"] = False, True

    def _publish_until(self, rp: dict) -> None:
        """Publish every sweep up to the replay position (the caller holds the data lock)."""
        run, i = rp["run"], rp["i"]
        while i < len(run.sweeps) and run.sweeps[i][0] <= rp["pos"]:
            t, vals = run.sweeps[i]
            i += 1
            self.seq += 1
            for p, v in vals.items():
                self._ch[p].append((self.seq, t, v))
            self._sweep_t.append(t)
            self._last_at = self._clock()
        rp["i"] = i

    def _seek_locked(self, rp: dict, pos: float) -> None:
        run = rp["run"]
        self._ch = {p: deque(maxlen=self._max) for p in run.names}
        self._sweep_t.clear()
        self.seq = 0
        self._run_id += 1
        rp["pos"], rp["ended"] = pos, False
        rp["i"] = run.first_in_window(pos, _REPLAY_WINDOW_S)
        self._publish_until(rp)
        if pos >= run.duration:
            rp["playing"], rp["ended"] = False, True

    def replay_control(self, action: str, pos: float | None = None, speed: float | None = None) -> None:
        with self._data_lock:
            rp = self._replay
            if rp is None:
                raise ValueError("no replay is loaded")
            run = rp["run"]
            if action == "pause":
                rp["playing"] = False
            elif action == "play":
                if rp["ended"]:
                    self._seek_locked(rp, 0.0)
                rp["playing"] = True
            elif action == "restart":
                self._seek_locked(rp, 0.0)
                rp["playing"] = True
            elif action == "seek":
                if isinstance(pos, bool) or not isinstance(pos, (int, float)) or not math.isfinite(pos):
                    raise ValueError("pos must be a number")
                self._seek_locked(rp, min(max(float(pos), 0.0), run.duration))
            elif action == "speed":
                if isinstance(speed, bool) or not isinstance(speed, (int, float)) or float(speed) not in _SPEEDS:
                    raise ValueError("speed must be one of 0.5, 1, 2, 4, 8")
                rp["speed"] = float(speed)
            else:
                raise ValueError("unknown replay action")
```

(g) In `state()`: replace the channels comprehension header so names come from `_meta`, and add the replay fields. Specifically change

```python
            channels = {
                p: {"name": PIDS[p].name, "unit": PIDS[p].unit,
                    "labels": None if PIDS[p].labels is None else {str(k): v for k, v in PIDS[p].labels.items()},
                    "samples": [[s, tt, v] for s, tt, v in d if after < s <= seq]}
                for p, d in self._ch.items()
            }
        now = (self._clock() - t0) if t0 is not None else 0.0
```

to

```python
            channels = {
                p: {"name": self._meta(p)[0], "unit": self._meta(p)[1], "labels": self._meta(p)[2],
                    "samples": [[s, tt, v] for s, tt, v in d if after < s <= seq]}
                for p, d in self._ch.items()
            }
            rp = self._replay
            replay = None if rp is None else {"name": rp["name"], "duration": rp["run"].duration, "pos": round(rp["pos"], 3),
                                              "speed": rp["speed"], "playing": rp["playing"], "ended": rp["ended"]}
        now = replay["pos"] if replay else (self._clock() - t0) if t0 is not None else 0.0
```

and in the returned dict change `"demo": self._sim is not None,` to `"demo": self._sim is not None and replay is None,` and add `"replay": replay,` after `"extras": extras, "mode06": m06, "vehicle": vehicle,`.

(h) In `recent()` replace the `PIDS[p].name` / `PIDS[p].unit` uses with `_meta`: change the body of the loop to

```python
        for p, rows in snap.items():
            name, unit, _ = self._meta(p)
            if not rows:
                out[p] = {"name": name, "unit": unit, "stats": {"n": 0}, "latest": None}
                continue
            cut = rows[-1][1] - seconds
            win = [(tt, v) for _, tt, v in rows if tt >= cut]
            out[p] = {"name": name, "unit": unit,
                      "stats": summarize(Series(name=name, unit=unit, samples=win)),
                      "latest": rows[-1][2]}
```

(i) In `save_run`, first line of the body (before the label check): 

```python
        if self._replay is not None:
            raise ValueError("a replay cannot be saved")
```

- [ ] **Step 4: Run, expect PASS, then the whole suite**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_hub.py -q` then `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q`
Expected: all pass. If an existing test compares the whole `state()` dict, add `"replay": None` to its expectation.

- [ ] **Step 5: Commit**

```bash
git add src/obd_reader/hub.py tests/test_hub.py
git commit -m "feat: hub replay mode (player thread, seek, speed, exclusion with live sampling, no disk writes)"
```

---

### Task 3: Server routes and `console_data` source

**Files:**
- Modify: `src/obd_reader/console.py`, `src/obd_reader/tools.py`
- Test: `tests/test_console.py`, `tests/test_console_tools.py`

**Interfaces:**
- Consumes: `list_runs`, `read_run_file`, `load_run`, `MAX_FILE_BYTES` (Task 1); `hub.start_replay`, `hub.replay_control`, `hub.exit_replay`, `hub.runs_dir` (Task 2).
- Produces: `GET /api/runs` -> `{"runs": [...]}`; `POST /api/replay` body `{"name": "x.json"}` or `{"run": {...}, "name": "label"}` -> `{"ok": true}`; `POST /api/replay/control` body `{"action": "play|pause|restart|seek|speed|exit", "pos"?, "speed"?}` -> `{"ok": true}`. Errors: 400 (bad name, bad file, bad action), 404 (unknown run name), 409 (busy), 413 (over the route's body cap). `console.MAX_UPLOAD = 8 * 1024 * 1024` for `/api/replay` only; every other route keeps `MAX_BODY`. `console_data` gains `"source": "live" | "replay"` and `"replay": <name>` when a replay.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_console.py`:

```python
def _run_obj(n=10):
    ts = [round(0.4 * k, 3) for k in range(1, n + 1)]
    return {"kind": "live_run", "demo": False, "adapter": {"protocol": "ISO 15765-4 (CAN 29/500)"},
            "live_sample": {"duration_s": ts[-1], "rate_hz": 2.5, "series": {
                "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[t, 700 + i] for i, t in enumerate(ts)]}}}}


def test_runs_are_listed_and_loaded_by_name_and_controlled(srv):
    server, hub, _ = srv
    hub.runs_dir.mkdir()
    (hub.runs_dir / "a-run.json").write_text(json.dumps(_run_obj()))
    status, body = call(server, "GET", "/api/runs")
    assert status == 200 and [r["name"] for r in body["runs"]] == ["a-run.json"] and body["runs"][0]["duration"] == 4.0
    assert call(server, "POST", "/api/replay", {"name": "a-run.json"}) == (200, {"ok": True})
    st = call(server, "GET", "/api/state")[1]
    assert st["replay"]["name"] == "a-run.json" and st["status"] == "running"
    assert call(server, "POST", "/api/replay/control", {"action": "pause"})[0] == 200
    assert call(server, "POST", "/api/replay/control", {"action": "seek", "pos": 2})[0] == 200
    assert call(server, "GET", "/api/state")[1]["replay"]["pos"] == 2.0
    assert call(server, "POST", "/api/replay/control", {"action": "speed", "speed": 3})[0] == 400
    assert call(server, "POST", "/api/replay/control", {"action": "exit"})[0] == 200
    assert call(server, "GET", "/api/state")[1]["replay"] is None
    assert call(server, "POST", "/api/replay/control", {"action": "pause"})[0] == 400


def test_replay_names_and_files_are_validated(srv):
    server, hub, _ = srv
    hub.runs_dir.mkdir()
    (hub.runs_dir / "bad.json").write_text(json.dumps({"kind": "snapshot"}))
    (hub.runs_dir / "nan.json").write_text('{"kind": "live_run", "live_sample": {"series": {"0C": {"name": "x", "unit": null, "samples": [[1, NaN]]}}}}')
    for name in ("../x.json", "a/b.json", "x.txt", "", "bad.json", "nan.json"):
        assert call(server, "POST", "/api/replay", {"name": name})[0] == 400, name
    assert call(server, "POST", "/api/replay", {"name": "missing.json"})[0] == 404
    assert call(server, "GET", "/api/state")[1]["replay"] is None


def test_an_uploaded_run_is_replayed_from_memory_and_writes_nothing(srv):
    server, hub, _ = srv
    status, body = call(server, "POST", "/api/replay", {"run": _run_obj(), "name": "my<b>file.json"})
    assert (status, body) == (200, {"ok": True})
    st = call(server, "GET", "/api/state")[1]
    assert st["replay"]["name"] == "my_b_file.json", "the label is reduced to safe characters"
    assert not hub.runs_dir.exists()
    assert call(server, "POST", "/api/replay", {"run": {"kind": "live_run"}})[0] == 400
    assert call(server, "POST", "/api/replay", {"run": [1, 2]})[0] == 400


def test_the_upload_route_alone_accepts_a_large_body(srv, monkeypatch):
    server, _, _ = srv
    big = {"run": _run_obj(), "pad": "x" * 6000}
    assert call(server, "POST", "/api/replay", big)[0] == 200, "6 KB is over the 4 KB default and fine here"
    assert call(server, "POST", "/api/stop", {"pad": "x" * 6000})[0] == 413, "every other route keeps the small cap"
    monkeypatch.setattr("obd_reader.console.MAX_UPLOAD", 1000)
    assert call(server, "POST", "/api/replay", {"run": _run_obj(), "pad": "x" * 2000})[0] == 413


def test_replay_routes_need_the_token_and_the_origin_and_are_not_gettable(srv):
    server, hub, _ = srv
    hub.runs_dir.mkdir()
    (hub.runs_dir / "a-run.json").write_text(json.dumps(_run_obj()))
    assert call(server, "GET", "/api/runs", token=None)[0] == 401
    assert call(server, "POST", "/api/replay", {"name": "a-run.json"}, token=None)[0] == 401
    assert call(server, "POST", "/api/replay", {"name": "a-run.json"}, headers={"Origin": "http://evil.example"})[0] == 403
    assert call(server, "GET", "/api/replay")[0] == 405 and call(server, "GET", "/api/replay/control")[0] == 405
    assert call(server, "POST", "/api/runs", {})[0] == 405


def test_replay_and_live_sampling_refuse_each_other_over_http(srv):
    server, hub, _ = srv
    assert call(server, "POST", "/api/replay", {"run": _run_obj()})[0] == 200
    assert call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10})[0] == 409
    assert call(server, "POST", "/api/save", {"label": "x"})[0] == 400
    assert call(server, "POST", "/api/replay/control", {"action": "exit"})[0] == 200
    assert call(server, "POST", "/api/start", {"pids": DEFAULT_PIDS, "hz": 10})[0] == 200
    assert wait_seq(server, 2)
    assert call(server, "POST", "/api/replay", {"run": _run_obj()})[0] == 409
```

Append to `tests/test_console_tools.py`:

```python
def post_json(url, path, body):
    host_port = url.split("//")[1].split("/")[0]
    token = url.split("t=")[1]
    c = http.client.HTTPConnection(host_port, timeout=5)
    c.request("POST", f"{path}?t={token}", body=json.dumps(body), headers={"Host": host_port, "Content-Type": "application/json"})
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


def test_console_data_names_its_source(tmp_path):  # Review Focus 5
    tl = build_tools(demo_session(tmp_path))
    out = tl["open_console"](demo=True)
    try:
        assert wait_seq(out["url"], 3)
        assert tl["console_data"](seconds=30)["source"] == "live"
        assert post_json(out["url"], "/api/stop", {}) == 200
        run = {"kind": "live_run", "live_sample": {"duration_s": 1.2, "rate_hz": 2.5, "series": {
            "0C": {"name": "engine_rpm", "unit": "rpm", "samples": [[0.4, 700], [0.8, 710], [1.2, 720]]}}}}
        assert post_json(out["url"], "/api/replay", {"run": run, "name": "drive.json"}) == 200
        assert post_json(out["url"], "/api/replay/control", {"action": "seek", "pos": 1.2}) == 200
        data = tl["console_data"](seconds=30)
        assert data["source"] == "replay" and data["replay"] == "drive.json" and data["channels"]["0C"]["latest"] == 720.0
    finally:
        ConsoleService.shutdown_all()
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_console.py tests/test_console_tools.py -q -k "replay or runs or source or upload"`
Expected: FAIL (404 / `KeyError: 'source'`).

- [ ] **Step 3: Implement.**

In `src/obd_reader/console.py`:

1. After `from obd_reader.profiles`-style imports add `from obd_reader.replay_run import MAX_FILE_BYTES, list_runs, load_run, read_run_file`.
2. Replace the line `MAX_BODY = 4096` with `MAX_BODY = 4096\nMAX_UPLOAD = MAX_FILE_BYTES  # the replay upload route only` and replace `_POST_ROUTES = ("/api/start", "/api/stop", "/api/save", "/api/sim")` with `_POST_ROUTES = ("/api/start", "/api/stop", "/api/save", "/api/sim", "/api/replay", "/api/replay/control")`.
3. Change `def _body(self) -> dict | None:` to `def _body(self, limit: int = MAX_BODY) -> dict | None:` and `if n < 0 or n > MAX_BODY:` to `if n < 0 or n > limit:`.
4. In `do_GET`: change `if path not in ("/", "/api/state", "/api/help"):` to `if path not in ("/", "/api/state", "/api/help", "/api/runs"):` and insert, directly after the `/api/help` branch:

```python
                if path == "/api/runs":
                    return self._json(200, {"runs": list_runs(outer.hub.runs_dir)})
```

5. In `do_POST`: change `if path in ("/", "/api/state", "/api/help"):` to `if path in ("/", "/api/state", "/api/help", "/api/runs"):` and change `body = self._body()` to `body = self._body(MAX_UPLOAD if path == "/api/replay" else MAX_BODY)`.
6. Inside the `try:` of `do_POST`, before the final `outer.hub.set_sim(...)` line insert:

```python
                    if path == "/api/replay":
                        if "run" in body:
                            label = body.get("name")
                            name = re.sub(r"[^A-Za-z0-9._ -]", "_", label)[:80] if isinstance(label, str) and label else "upload"
                            run = load_run(body["run"])
                        else:
                            name = str(body.get("name", ""))
                            run = load_run(read_run_file(outer.hub.runs_dir, name))
                        outer.hub.start_replay(run, name)
                        return self._json(200, {"ok": True})
                    if path == "/api/replay/control":
                        if body.get("action") == "exit":
                            outer.hub.exit_replay()
                        else:
                            outer.hub.replay_control(body.get("action"), pos=body.get("pos"), speed=body.get("speed"))
                        return self._json(200, {"ok": True})
```

7. Add `except FileNotFoundError: return self._json(404, {"error": "no such saved run"})` as the first `except` clause of that `try` (before `except (HubBusy, AdapterBusy)`).

In `src/obd_reader/tools.py`, change the `console_data` return to:

```python
        st = service.hub.state()
        rp = st.get("replay")
        return {"status": st["status"], "message": st["message"], "seq": st["seq"],
                "source": "replay" if rp else "live", **({"replay": rp["name"]} if rp else {}),
                "channels": service.hub.recent(seconds)}
```

and extend its docstring's second sentence with: ` The "source" field says whether the numbers are live from the car or a replay of a saved run; check it before drawing conclusions about the car.`

- [ ] **Step 4: Run, expect PASS, then the whole suite**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_console.py tests/test_console_tools.py -q` then the full suite.
Expected: all pass. (`do_POST`'s existing 405 for `GET` on POST routes comes from `do_GET`'s `_POST_ROUTES` check, so `GET /api/replay` is already 405.)

- [ ] **Step 5: Commit**

```bash
git add src/obd_reader/console.py src/obd_reader/tools.py tests/test_console.py tests/test_console_tools.py
git commit -m "feat: replay routes (list, load by name or upload, control), per-route upload cap, console_data source"
```

---

### Task 4: Page — Replay panel, transport bar, banner

**Files:**
- Modify: `src/obd_reader/web/console.html`, `tests/js/page_logic_test.js`, `tests/test_console_page.py`

**Interfaces:**
- Consumes: `state.replay` (`{name, duration, pos, speed, playing, ended}` or `null`), `GET /api/runs`, `POST /api/replay`, `POST /api/replay/control` (Task 3).
- Produces element ids: `replayBtn`, `replayPanel`, `rp_runs`, `rp_load`, `rp_file`, `rp_err`, `replayBanner`, `rbar`, `rb_restart`, `rb_play`, `rb_speed`, `rb_seek`, `rb_time`, `rb_exit`. Harness: `makeEnv(states, viewId, help, runs)` (fourth parameter: the list returned by `/api/runs`).

- [ ] **Step 1: Extend the harness.** In `tests/js/page_logic_test.js` change `function makeEnv(states, viewId = 'v0', help = null) {` to `function makeEnv(states, viewId = 'v0', help = null, runs = []) {` and add this line in the fake `fetch`, directly after the `/api/help` line:

```js
      if (/\/api\/runs/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve({ runs }) });
```

Run `node tests/js/page_logic_test.js src/obd_reader/web/console.html` and expect `page logic OK` (nothing else changed).

- [ ] **Step 2: Write the failing tests.** Insert before `console.log('page logic OK');`:

```js
  // 8) replay UI: banner, transport bar, controls, picker, upload
  const REPLAY = (over) => Object.assign({ name: 'drive.json', duration: 370, pos: 151, speed: 1, playing: true, ended: false }, over);
  const rstates = (r) => statesFor(3, idle).map(st => Object.assign(st, { replay: r, vehicle: { key: 'ABCDEFGH-P', known: false, runs: 0, note: null } }));
  const RUNS = [{ name: 'a.json', size: 2048, duration: 370 }, { name: '<b>.json', size: 10, duration: 5 }];
  const rp1 = makeEnv(rstates(REPLAY()), 'v0', null, RUNS);
  for (let k = 0; k < 4; k++) await rp1.tick();
  assert.strictEqual(rp1.el('rbar').hidden, false); assert.strictEqual(rp1.el('replayBanner').hidden, false);
  assert(/Replay: drive\.json/.test(rp1.el('replayBanner').textContent), 'banner names the run');
  assert.strictEqual(rp1.el('rb_time').textContent, '2:31 / 6:10'); assert.strictEqual(rp1.el('rb_play').textContent, 'Pause');
  assert.strictEqual(rp1.el('rb_speed').value, '1'); assert.strictEqual(rp1.el('rb_seek').max, 370); assert.strictEqual(rp1.el('rb_seek').value, 151);
  assert.strictEqual(rp1.el('pause').disabled, true); assert.strictEqual(rp1.el('save').disabled, true);
  assert(/replay/.test(rp1.el('chipCar').textContent) && !/new/.test(rp1.el('chipCar').textContent), 'the car chip says replay, not new');
  const lastPost = () => rp1.posts[rp1.posts.length - 1];
  rp1.handlers['rb_play:click'](); assert(/\/api\/replay\/control/.test(lastPost().url) && lastPost().body.action === 'pause');
  rp1.handlers['rb_restart:click'](); assert.strictEqual(lastPost().body.action, 'restart');
  rp1.el('rb_speed').value = '4'; rp1.handlers['rb_speed:change'](); assert.deepStrictEqual(lastPost().body, { action: 'speed', speed: 4 });
  rp1.el('rb_seek').value = '60';
  const beforeDrag = rp1.posts.length; rp1.handlers['rb_seek:input']();
  assert.strictEqual(rp1.posts.length, beforeDrag, 'dragging alone sends nothing');
  assert.strictEqual(rp1.el('rb_time').textContent, '1:00 / 6:10', 'the label follows the drag');
  rp1.handlers['rb_seek:change'](); assert.deepStrictEqual(lastPost().body, { action: 'seek', pos: 60 });
  rp1.handlers['rb_exit:click'](); assert.strictEqual(lastPost().body.action, 'exit');
  const ended = makeEnv(rstates(REPLAY({ playing: false, ended: true, pos: 370 })), 'v0');
  for (let k = 0; k < 4; k++) await ended.tick();
  assert.strictEqual(ended.el('rb_play').textContent, 'Replay'); assert.strictEqual(ended.el('rb_time').textContent, '6:10 / 6:10');
  const evilName = makeEnv(rstates(REPLAY({ name: '<img src=x onerror=1>' })), 'v0');
  for (let k = 0; k < 4; k++) await evilName.tick();
  assert(evilName.el('replayBanner').textContent.includes('<img src=x onerror=1>') && evilName.el('replayBanner').innerHTML === '', 'run name is shown as text');
  const live = makeEnv(statesFor(3, idle), 'v0');
  for (let k = 0; k < 4; k++) await live.tick();
  assert.strictEqual(live.el('rbar').hidden, true); assert.strictEqual(live.el('replayBanner').hidden, true); assert.strictEqual(live.el('pause').disabled, false);

  // picker and upload
  const pk = makeEnv(statesFor(3, idle), 'v0', null, RUNS);
  for (let k = 0; k < 3; k++) await pk.tick();
  pk.el('replayPanel').hidden = true;   // the page's markup starts it hidden; the fake DOM does not
  pk.handlers['replayBtn:click'](); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));
  assert.strictEqual(pk.el('replayPanel').hidden, false);
  assert.strictEqual(pk.el('rp_runs').children.length, 2);
  assert(/a · 6:10 · 2 KB/.test(pk.el('rp_runs').children[0].textContent), 'option label: ' + pk.el('rp_runs').children[0].textContent);
  assert(pk.el('rp_runs').children[1].textContent.includes('<b>') && pk.el('rp_runs').children[1].innerHTML === '', 'run names are shown as text');
  pk.el('rp_runs').value = 'a.json'; pk.handlers['rp_load:click'](); await new Promise(r => setImmediate(r));
  assert.deepStrictEqual(pk.posts[pk.posts.length - 1].body, { name: 'a.json' }); assert.strictEqual(pk.el('replayPanel').hidden, true);
  const upload = async (file) => { pk.handlers['rp_file:change']({ target: { files: [file], value: 'x' } }); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r)); };
  await upload({ name: 'x.json', size: 100, text: () => Promise.resolve(JSON.stringify({ kind: 'live_run' })) });
  assert.deepStrictEqual(pk.posts[pk.posts.length - 1].body, { run: { kind: 'live_run' }, name: 'x.json' });
  const sent = pk.posts.length;
  await upload({ name: 'big.json', size: 9 * 1024 * 1024, text: () => Promise.resolve('{}') });
  assert.strictEqual(pk.posts.length, sent); assert(/too large/.test(pk.el('rp_err').textContent), 'oversize file refused before sending');
  await upload({ name: 'bad.json', size: 10, text: () => Promise.resolve('nope') });
  assert.strictEqual(pk.posts.length, sent); assert(/not a JSON file/.test(pk.el('rp_err').textContent));
  pk.el('replayPanel').hidden = false;
  pk.sandbox.fetch = () => Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'not a saved run' }) });
  pk.el('rp_runs').value = 'a.json'; pk.handlers['rp_load:click'](); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r));
  assert.strictEqual(pk.el('rp_err').textContent, 'not a saved run'); assert.strictEqual(pk.el('replayPanel').hidden, false, 'the panel stays open on an error');

```

In `tests/test_console_page.py` add `"replayBtn", "replayPanel", "rp_runs", "rp_load", "rp_file", "rp_err", "replayBanner", "rbar", "rb_restart", "rb_play", "rb_speed", "rb_seek", "rb_time", "rb_exit"` to the element-id tuple in `test_required_controls_exist_and_no_simulator_is_baked_in`.

- [ ] **Step 3: Run, expect FAIL**

Run: `node tests/js/page_logic_test.js src/obd_reader/web/console.html` -> expected `FAIL` (the elements are never set; first failure is on `rb_time` or the banner).
Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_console_page.py -q` -> expected FAIL on missing ids.

- [ ] **Step 4: Implement in `src/obd_reader/web/console.html`.**

(a) CSS, add before `</style>`:

```css
  .rbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; padding: 8px 16px; background: var(--panel2); border-bottom: 1px solid var(--line); font-size: 12.5px; }
  .rbar input[type=range] { flex: 1 1 260px; min-width: 160px; accent-color: var(--cyan); }
  .rbar .tm { font: 600 13px var(--cond); font-variant-numeric: tabular-nums; min-width: 92px; text-align: right; }
  #replayPanel { position: relative; padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--line); font-size: 12.5px; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }
  #replayPanel[hidden], .rbar[hidden] { display: none; }
  #replayPanel select { max-width: 100%; }
  #rp_err { color: var(--bad); flex: 1 1 100%; margin: 0; }
  #rp_err:empty { display: none; }
```

(b) HTML. Directly after the existing `<div class="banner" id="demoBanner" hidden>...</div>` line add `<div class="banner" id="replayBanner" hidden></div>`. In the status bar, add `<button class="b" id="replayBtn">Replay&hellip;</button>` immediately before `<button class="b" id="pause">`. Directly after `<div class="msgbar" id="msg" hidden></div>` add:

```html
<div id="replayPanel" hidden>
  <label>Saved run <select class="b" id="rp_runs"></select></label>
  <button class="b primary" id="rp_load">Load</button>
  <label>or a file <input type="file" id="rp_file" accept=".json,application/json"></label>
  <p id="rp_err"></p>
</div>
<div class="rbar" id="rbar" hidden>
  <button class="b" id="rb_restart" title="Restart">&#9198;</button>
  <button class="b primary" id="rb_play">Pause</button>
  <select class="b" id="rb_speed"><option value="0.5">0.5&times;</option><option value="1" selected>1&times;</option><option value="2">2&times;</option><option value="4">4&times;</option><option value="8">8&times;</option></select>
  <input type="range" id="rb_seek" min="0" max="0" step="0.1" value="0" aria-label="Replay position">
  <span class="tm" id="rb_time">0:00 / 0:00</span>
  <button class="b" id="rb_exit">Exit replay</button>
</div>
```

(c) JS. In `chips()`, change the car-chip line's `(v.known ? 'seen ' + v.runs + (v.runs === 1 ? ' time' : ' times') : 'new')` to `(st.replay ? 'replay' : v.known ? 'seen ' + v.runs + (v.runs === 1 ? ' time' : ' times') : 'new')`, and add as the last line of `chips()` (after the `simctl`/`demoBanner` line, before the message handling): `renderReplay();`.

Add before `function chips() {` (it uses `$` and `el`, both defined earlier):

```js
  /* ---------- replay ---------- */
  var seeking = false;
  function mmss(s) { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
  function renderReplay() {
    var r = state && state.replay;
    $('replayBanner').hidden = !r; $('rbar').hidden = !r;
    if (!r) { $('pause').disabled = false; $('save').disabled = false; return; }
    $('replayBanner').textContent = 'Replay: ' + r.name + ' · not a live car';
    $('pause').disabled = true; $('save').disabled = true; $('pause').textContent = 'Live sampling off';
    $('simctl').hidden = true;
    $('rb_play').textContent = r.playing ? 'Pause' : r.ended ? 'Replay' : 'Play';
    $('rb_speed').value = String(r.speed);
    if (!seeking) { $('rb_seek').max = r.duration; $('rb_seek').value = r.pos; $('rb_time').textContent = mmss(r.pos) + ' / ' + mmss(r.duration); }
  }
  function replayCtl(body) { return post('/api/replay/control', body).then(function () { poll(); }); }
  function replayErr(msg) { $('rp_err').textContent = msg || ''; }
  function loadReplay(body) {
    replayErr('');
    return post('/api/replay', body).then(function (r) {
      if (!r.ok) { replayErr((r.j && r.j.error) || 'could not load the run'); return; }
      $('replayPanel').hidden = true; poll();
    });
  }
  function fillRuns(list) {
    var sel = $('rp_runs'); sel.textContent = '';
    list.forEach(function (r) { var o = el('option', '', r.name.replace(/\.json$/, '') + ' · ' + mmss(r.duration) + ' · ' + Math.round(r.size / 1024) + ' KB'); o.value = r.name; sel.appendChild(o); });
    if (!list.length) sel.appendChild(el('option', '', 'no saved runs yet'));
  }
  $('replayBtn').addEventListener('click', function () {
    var p = $('replayPanel'); p.hidden = !p.hidden;
    if (p.hidden) return;
    replayErr('');
    fetch(api('/api/runs')).then(function (r) { return r.json(); }).then(function (j) { fillRuns((j && j.runs) || []); }).catch(function () { fillRuns([]); });
  });
  $('rp_load').addEventListener('click', function () { var v = $('rp_runs').value; if (v) loadReplay({ name: v }); });
  $('rp_file').addEventListener('change', function (e) {
    var f = e.target.files && e.target.files[0]; if (!f) return;
    if (f.size > 8 * 1024 * 1024) { replayErr('file too large (8 MB at most)'); e.target.value = ''; return; }
    f.text().then(function (txt) {
      var run; try { run = JSON.parse(txt); } catch (x) { replayErr('not a JSON file'); return; }
      return loadReplay({ run: run, name: f.name });
    });
    e.target.value = '';
  });
  $('rb_play').addEventListener('click', function () { replayCtl({ action: state && state.replay && state.replay.playing ? 'pause' : 'play' }); });
  $('rb_restart').addEventListener('click', function () { replayCtl({ action: 'restart' }); });
  $('rb_speed').addEventListener('change', function () { replayCtl({ action: 'speed', speed: Number($('rb_speed').value) }); });
  $('rb_seek').addEventListener('input', function () { seeking = true; var d = state && state.replay ? state.replay.duration : 0; $('rb_time').textContent = mmss(Number($('rb_seek').value)) + ' / ' + mmss(d); });
  $('rb_seek').addEventListener('change', function () { var pos = Number($('rb_seek').value); replayCtl({ action: 'seek', pos: pos }).then(function () { seeking = false; }); });
  $('rb_exit').addEventListener('click', function () { replayCtl({ action: 'exit' }); });
```

`post` and `poll` are function declarations later in the script, so hoisting makes them available. Keep this block above `chips()` but note `renderReplay` is called from `chips()` at runtime only.

- [ ] **Step 5: Run, expect PASS, then the whole suite**

Run: `node tests/js/page_logic_test.js src/obd_reader/web/console.html` -> `page logic OK`; then the full pytest suite -> all pass. If the Node test fails on the picker label, check `fillRuns` builds `a · 6:10 · 2 KB` (2048 bytes -> 2 KB).

- [ ] **Step 6: Look at it.** Create a run to replay: start `console --demo`, press Start sampling, wait about 20 s, press Stop sampling (autosave is off in demo; use Save run), then open Replay…, pick it, Load. Expected: amber banner, transport bar, tiles move, Pause holds them, speed 4x runs fast, dragging the scrubber jumps, Exit replay returns to idle.

- [ ] **Step 7: Commit**

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js tests/test_console_page.py
git commit -m "feat: replay panel, transport bar and banner on the console page"
```

---

### Task 5: Save run stores codes, Mode 06 and the car key

**Files:**
- Modify: `src/obd_reader/hub.py` (`_write_run`)
- Test: `tests/test_hub.py`

**Interfaces:**
- Consumes: `load_run` and the replay mode (Tasks 1 and 2).
- Produces: run files gain `"codes"` (the hub's `_codes` dict), `"mode06"` (the hub's `_m06` dict) and `"vehicle"` (`{"key": <partial key>}` when the car was identified, else `null`). Old files without these keys keep loading.

- [ ] **Step 1: Write the failing test.** Append to `tests/test_hub.py` (it already imports `json`, `SIM_VIN`, `vehicle_key`, `load_run`):

```python
def test_saved_run_carries_codes_mode06_and_the_partial_key_and_replays_them(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    assert wait_for(lambda: hub.state()["codes"]["read"] and hub.state()["mode06"]["read"] and hub.state()["vehicle"] is not None)
    assert wait_for(lambda: hub.state()["seq"] >= 6)
    hub.stop()
    path = hub.save_run("trip")
    text = path.read_text()
    data = json.loads(text)
    assert data["codes"]["read"] is True and data["mode06"]["read"] is True and data["vehicle"] == {"key": vehicle_key(SIM_VIN)}
    assert SIM_VIN not in text and SIM_VIN[-6:] not in text, "the serial and the VIN never reach the file"
    hub2, _, _ = make(tmp_path)
    hub2.start_replay(load_run(data), path.name, playing=False)
    st = hub2.state()
    assert st["codes"]["stored"] == data["codes"]["stored"] and st["codes"]["mil"] == data["codes"]["mil"]
    assert st["mode06"]["results"] == data["mode06"]["results"] and st["vehicle"]["key"] == vehicle_key(SIM_VIN)
    hub2.exit_replay()
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_hub.py -q -k "saved_run_carries"`
Expected: FAIL with `KeyError: 'codes'`.

- [ ] **Step 3: Implement in `_write_run`.** In `src/obd_reader/hub.py`, inside the first `with self._data_lock:` block of `_write_run` (the one that builds `series`), add after the `series = {...}` statement:

```python
            codes, m06, key = dict(self._codes), dict(self._m06), self._key
```

and replace the `json.dump({...}, fh, indent=2)` call so it reads:

```python
            json.dump({"kind": "live_run", "demo": self._sim is not None, "adapter": self._adapter,
                       "live_sample": ls.model_dump(mode="json"), "codes": codes, "mode06": m06,
                       "vehicle": {"key": key} if key else None}, fh, indent=2)
```

- [ ] **Step 4: Run, expect PASS, then the whole suite**

Run the new test, then `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q`. Expected: all pass. If an existing saved-run test compares the whole file, add the three new keys to its expectation.

- [ ] **Step 5: Commit**

```bash
git add src/obd_reader/hub.py tests/test_hub.py
git commit -m "feat: Save run stores codes, Mode 06 results and the partial car key so replays show them"
```

---

### Task 6: Docs

**Files:**
- Modify: `README.md`, `docs/design.md`

- [ ] **Step 1: README.** In the "What works today" table add a row after the Overview row: `| Replay a saved run in the console (play, pause, speed 0.5x-8x, scrubber, restart; pick from runs/ or upload a file) | done, demo tested | not yet used on a real saved run in a browser |`. In the "Live console" section add this paragraph after the "Help popups" paragraph:

`**Replay:** press **Replay…** in the status bar, pick a saved run from \`runs/\` (or choose a run file, such as a bundle copied from the laptop) and press Load. The page shows the run exactly as it was sampled: play, pause, speed (0.5x to 8x), drag the scrubber, restart, Exit replay. A replay never touches the adapter and writes nothing; live sampling and Save run are off while one is loaded, and Claude's \`console_data\` says its numbers are a replay. Runs saved from now on also store the trouble codes, Mode 06 results and the partial car key, so their replays show those too; older runs replay the readings only.`

- [ ] **Step 2: design.md.** In `docs/design.md` §7b: add `GET /api/runs`, `POST /api/replay` and `POST /api/replay/control` to the ConsoleServer route list; add a **Replay** paragraph after **Car memory** describing: replay as a second hub source fed from a validated `Run` (`replay_run.py`: untrusted input, 64 readings / 600,000 samples / 24 h / 8 MB, strict names, no symlinks, nothing written), the player thread and seek-resets-with-new-run-id behavior, exclusion with live sampling, `console_data.source`, and that saved runs now carry `codes`, `mode06` and `vehicle.key`. In the Rules sentence change "start/stop sampling and save a run file only" to "start/stop sampling, save a run file, and load or control a replay only" and the body cap sentence to "bodies capped at 4096 bytes (8 MB on the replay upload route only)".

- [ ] **Step 3: Run the whole suite, commit**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q` -> all pass.

```bash
git add README.md docs/design.md
git commit -m "docs: README and design for replay mode"
```

---

## Self-Review

- **Spec coverage:** loader and limits (Task 1); hub replay mode, seek, exclusion, no disk writes, state shape, source (Tasks 2-3); routes and per-route cap, `console_data.source` (Task 3); page panel, transport, banner, disabled controls, safe text, oversize refusal (Task 4); Save run extension and replay of codes/key (Task 5); docs (Task 6). Spec's Risks (60 s window on seek, memory-only upload) are covered by the seek test and the upload test.
- **Placeholder scan:** none; every code step has full code.
- **Type consistency:** `Run` fields (`names`, `sweeps`, `times`, `codes`, `mode06`, `vehicle`) match between Tasks 1, 2 and 5; hub methods `start_replay`, `replay_control`, `exit_replay`, `runs_dir`, `_replay_advance` match Tasks 3, 4 and 5; state key `replay` has the same six fields in Tasks 2, 3 and 4; control action names `play|pause|restart|seek|speed|exit` are identical in hub, server and page.
- **Known limit:** the page's Guided test capture state resets when a seek bumps the run id (documented in the spec).
