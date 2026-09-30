# Vehicle Profiles, Step 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the console samples a car, identify it from the VIN as a partial key (never the serial), load what a past run learned about that class of car, and save what this run learned for next time.

**Architecture:** `vehicle.py` turns a VIN into a key (`WMI + VDS-year`, positions 1-8 and 10). `profiles.py` stores one small JSON file per key under `<home>/profiles/` (gitignored, local). The hub reads the VIN once per run (Mode 09 02, CAN only, right after the first good sweep, next to the code read), loads the profile for that key, treats its "unsupported" PIDs as suspects (dropped after 1 miss instead of 3, and kept if they answer), and writes the profile when the run ends. The console page shows the key and whether the car was seen before.

**Tech Stack:** Python 3.11, stdlib `json`/`pathlib`, existing `hub.py`, `session.py`, `simulator.py`; Node fake-DOM test for the page chip.

**Spec:** the design discussion of 2026-09-30 (layers generic -> make -> model/year -> this car; data profiles, not code plugins; a cached profile is a hint, not truth). This plan is **step 1 only**. Not in this plan: curated make/model profile files, profile export/import, pinning the protocol before connecting (the VIN needs a protocol first), Mode 22 modules, a manual "pick the car" fallback for cars with no readable VIN.

## Global Constraints

- Read-only is unchanged: a profile never adds a command, PID outside `PIDS`, or anything to the allowlist (`allowlist.py` is not touched).
- Public repo: the VIN, its serial (positions 12-17) and check digit (position 9) are never written to a profile, to `state()`, to the page, or to a log line. Only the key is. Tests build VINs in code with `obd_reader.vin.with_check_digit` so the VIN guard does not flag them.
- `profiles/` is gitignored (local only). Curated committed profiles are a later step.
- CAN only, like codes and Mode 06: on other protocols the vehicle is `None` with a note; nothing is decoded wrongly.
- A profile is a hint: a corrupt or unreadable file behaves like no profile; a write failure never stops or crashes a run.
- Match the surrounding style: no new dependencies, no comments beyond the file's density.

## Review Focus

- The VIN string never appears in the saved profile file or in `hub.state()` (test scans both for the full 17 characters and for the serial).
- A corrupt, truncated or wrong-schema profile file loads as "no profile" and the next good run overwrites it.
- Two cars with the same key (same model, year and engine) share one profile; a PID dropped in a past run but answering now is kept and is not written as unsupported again.
- A run stopped before the VIN was read, or one that never got a value, writes no profile.
- An unwritable `profiles/` directory (OSError) leaves the run, its data and its status untouched and adds a message.

## File Structure

- Create `src/obd_reader/vehicle.py`: `vehicle_key(vin)`.
- Create `src/obd_reader/profiles.py`: `ProfileStore` (load, atomic save, validation).
- Modify `src/obd_reader/hub.py`: identity read, profile apply, profile save, `vehicle` in `state()`.
- Modify `src/obd_reader/simulator.py`: answer `0902` with a synthetic VIN built in code.
- Modify `src/obd_reader/web/console.html`: a "car" chip.
- Modify `.gitignore`, `README.md`.
- Tests: `tests/test_vehicle.py`, `tests/test_profiles.py`, additions to `tests/test_simulator.py`, `tests/test_hub.py`, `tests/js/page_logic_test.js`, `tests/test_console_page.py`.

---

### Task 1: Vehicle key

**Files:**
- Create: `src/obd_reader/vehicle.py`
- Test: `tests/test_vehicle.py`

**Interfaces:**
- Produces: `vehicle_key(vin: str) -> str | None`. Returns `f"{vin[:8]}-{vin[9]}"` for a well-formed VIN, else `None`. Example shape: `ABCDEFGH-P`.

- [ ] **Step 1: Write the failing test**

```python
from obd_reader.vin import with_check_digit
from obd_reader.vehicle import vehicle_key

A = with_check_digit("9SXSMUL1?T0000001")
SAME_CLASS_OTHER_SERIAL = with_check_digit("9SXSMUL1?T0999999")
OTHER_YEAR = with_check_digit("9SXSMUL1?V0000001")


def test_key_is_positions_1_to_8_and_10():
    assert vehicle_key(A) == "9SXSMUL1-T"


def test_key_ignores_the_serial_and_the_check_digit():
    assert vehicle_key(A) == vehicle_key(SAME_CLASS_OTHER_SERIAL)
    assert len(vehicle_key(A)) == 10 and A[-6:] not in vehicle_key(A)


def test_model_year_changes_the_key():
    assert vehicle_key(A) != vehicle_key(OTHER_YEAR)


def test_malformed_vin_has_no_key():
    for bad in ("", "short", "9SXSMUL1?T0000001", "9sxsmul10t0000001", None, 123, "I" * 17):
        assert vehicle_key(bad) is None
```

- [ ] **Step 2: Run it, expect FAIL** (`ModuleNotFoundError: obd_reader.vehicle`)

Run: `PYTHONPATH=src pytest tests/test_vehicle.py -v`

- [ ] **Step 3: Implement**

```python
"""A partial VIN that names a class of car (make, model, engine, year) and nothing about one physical car."""
from obd_reader.snapshot import VIN_RE


def vehicle_key(vin: str) -> str | None:
    """Positions 1-8 (WMI + VDS) and 10 (model year), e.g. 'ABCDEFGH-P'. Never the check digit or serial."""
    if not isinstance(vin, str) or not VIN_RE.fullmatch(vin):
        return None
    return f"{vin[:8]}-{vin[9]}"
```

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/obd_reader/vehicle.py tests/test_vehicle.py
git commit -m "feat: vehicle_key, a partial VIN that names a class of car and not a physical one"
```

---

### Task 2: Profile store

**Files:**
- Create: `src/obd_reader/profiles.py`
- Modify: `.gitignore` (add `profiles/`)
- Test: `tests/test_profiles.py`

**Interfaces:**
- Consumes: `vehicle_key` format (validated by `KEY_RE`).
- Produces: `KEY_RE`, `ProfileStore(home: Path)`, `.load(key: str) -> dict | None`, `.save(key: str, profile: dict) -> None`. A profile dict has exactly: `schema: 1`, `key: str`, `updated: str`, `runs: int`, `protocol: str | None`, `supported_pids`, `unsupported`, `extras` (each a sorted-or-ordered list of 2-hex-digit uppercase strings).

- [ ] **Step 1: Write the failing tests**

```python
import json

from obd_reader.profiles import ProfileStore

KEY = "9SXSMUL1-T"
GOOD = {"schema": 1, "key": KEY, "updated": "2026-09-30T18:00:00+00:00", "runs": 2, "protocol": "ISO 15765-4 (CAN 29/500)",
        "supported_pids": ["04", "0C"], "unsupported": ["10"], "extras": ["04"]}


def test_save_then_load_round_trips(tmp_path):
    s = ProfileStore(tmp_path)
    s.save(KEY, GOOD)
    assert s.load(KEY) == GOOD
    assert (tmp_path / "profiles" / f"{KEY}.json").exists()


def test_missing_corrupt_and_wrong_schema_files_load_as_none(tmp_path):
    s = ProfileStore(tmp_path)
    assert s.load(KEY) is None
    (tmp_path / "profiles").mkdir()
    p = tmp_path / "profiles" / f"{KEY}.json"
    p.write_text("{not json")
    assert s.load(KEY) is None
    p.write_text(json.dumps({**GOOD, "schema": 99}))
    assert s.load(KEY) is None
    p.write_text(json.dumps({**GOOD, "unsupported": "10"}))
    assert s.load(KEY) is None


def test_bad_pid_entries_are_dropped_not_trusted(tmp_path):
    s = ProfileStore(tmp_path)
    s.save(KEY, {**GOOD, "unsupported": ["10", "ZZ", "1", 5, "0b"]})
    assert s.load(KEY)["unsupported"] == ["10"]


def test_keys_that_are_not_keys_are_refused_so_no_path_can_escape(tmp_path):
    s = ProfileStore(tmp_path)
    for bad in ("../x", "a/b", "", "9SXSMUL1T", "9sxsmul1-t", "9SXSMUL1-T.json"):
        assert s.load(bad) is None
        try:
            s.save(bad, GOOD)
        except ValueError:
            continue
        raise AssertionError(f"saved {bad!r}")


def test_save_replaces_atomically_and_leaves_no_temp_files(tmp_path):
    s = ProfileStore(tmp_path)
    s.save(KEY, GOOD)
    s.save(KEY, {**GOOD, "runs": 3})
    assert s.load(KEY)["runs"] == 3
    assert [p.name for p in (tmp_path / "profiles").iterdir()] == [f"{KEY}.json"]
```

- [ ] **Step 2: Run, expect FAIL** (`ModuleNotFoundError: obd_reader.profiles`)

- [ ] **Step 3: Implement**

```python
"""Local, per-class-of-car memory of what past runs learned. A hint, never a source of truth:
anything unreadable or malformed loads as 'no profile'."""
import json
import os
import re
from pathlib import Path

KEY_RE = re.compile(r"[A-HJ-NPR-Z0-9]{8}-[A-HJ-NPR-Z0-9]")
_PID_RE = re.compile(r"[0-9A-F]{2}")
_LISTS = ("supported_pids", "unsupported", "extras")


def _pids(v) -> list[str] | None:
    if not isinstance(v, list):
        return None
    return [p for p in v if isinstance(p, str) and _PID_RE.fullmatch(p)]


class ProfileStore:
    def __init__(self, home: Path):
        self._dir = Path(home) / "profiles"

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            raise ValueError("not a vehicle key")
        return self._dir / f"{key}.json"

    def load(self, key: str) -> dict | None:
        try:
            d = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        if not isinstance(d, dict) or d.get("schema") != 1 or d.get("key") != key or not isinstance(d.get("runs"), int):
            return None
        lists = {k: _pids(d.get(k)) for k in _LISTS}
        if any(v is None for v in lists.values()):
            return None
        return {"schema": 1, "key": key, "updated": str(d.get("updated", "")), "runs": d["runs"],
                "protocol": d.get("protocol") if isinstance(d.get("protocol"), str) else None, **lists}

    def save(self, key: str, profile: dict) -> None:
        path = self._path(key)
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        os.replace(tmp, path)
```

- [ ] **Step 4: Add `profiles/` to `.gitignore`; run `PYTHONPATH=src pytest tests/test_profiles.py -v`, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add .gitignore src/obd_reader/profiles.py tests/test_profiles.py
git commit -m "feat: ProfileStore keeps what past runs learned about a class of car, local and gitignored"
```

---

### Task 3: Simulator answers the VIN request

**Files:**
- Modify: `src/obd_reader/simulator.py` (constant `SIM_VIN`, branch in `write`)
- Test: `tests/test_simulator.py`

**Interfaces:**
- Consumes: `with_check_digit` from `obd_reader.vin`.
- Produces: `SIM_VIN: str` (built in code), and `0902` replies in the CAN multi-frame layout the scanner already parses: `["014", "0: 49 02 01 xx xx xx", "1: ...", "2: ..."]`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_simulator.py`)

```python
def test_sim_answers_the_vin_request_in_multi_frame_layout_and_it_parses():
    from obd_reader.elm import parse_all
    from obd_reader.simulator import SIM_VIN
    from obd_reader.snapshot import VIN_RE
    lines = Transport(SimPort()).send("0902")
    assert lines[0] == "014" and lines[1].startswith("0: 49 02 01")
    payload = parse_all(lines, 0x49)[0]
    assert payload[3:20].decode("ascii") == SIM_VIN and VIN_RE.fullmatch(SIM_VIN)
```

- [ ] **Step 2: Run, expect FAIL** (`ImportError: SIM_VIN`)

- [ ] **Step 3: Implement.** Add near the top of `simulator.py`:

```python
from obd_reader.vin import with_check_digit

SIM_VIN = with_check_digit("9SXSMUL1?T0000001")  # made up, built in code so the repo's VIN guard never sees a literal
```

and, in `SimPort.write`, before the `ATI` branch:

```python
        elif cmd == "0902":
            b = [0x49, 0x02, 0x01] + list(SIM_VIN.encode("ascii"))
            fr = lambda chunk: " ".join(f"{x:02X}" for x in chunk)
            self._pending = "\r".join(["014", "0: " + fr(b[:6]), "1: " + fr(b[6:13]), "2: " + fr(b[13:20])]) + "\r"
```

- [ ] **Step 4: Run `PYTHONPATH=src pytest tests/test_simulator.py -v`, expect PASS. If `parse_all` rejects the layout, compare with the real two-line transcripts in `tests/fixtures` and fix the sim lines, not the parser.**

- [ ] **Step 5: Commit**

```bash
git add src/obd_reader/simulator.py tests/test_simulator.py
git commit -m "feat: simulator answers the Mode 09 VIN request with a synthetic VIN"
```

---

### Task 4: Hub identifies the car, applies and saves the profile

**Files:**
- Modify: `src/obd_reader/hub.py`
- Test: `tests/test_hub.py`

**Interfaces:**
- Consumes: `vehicle_key`, `ProfileStore`, `SIM_VIN`; `Session.config.home`.
- Produces: `hub.state()["vehicle"]` = `None` or `{"key": str, "known": bool, "runs": int, "note": str | None}` where `runs` counts saved runs before this one. A profile file `<home>/profiles/<key>.json` after a run that read the VIN and got at least one value.

Design notes for the implementer:
- `_reset` adds `self._vehicle = None`, `self._key = None`, `self._supported: set[str] = set()`, `self._prior: dict | None = None`.
- `_discover_extras` stores the discovered set in `self._supported` (assign before it returns; it already builds `supported`).
- New `_read_identity(self, t) -> dict | None`, called in `_run` right after `self._read_codes(t)` and before `_read_mode06`, guarded by `if not self._stop.is_set()`. Same gate as codes: `if self._sim is None and "15765" not in proto:` set `self._vehicle = {"key": None, "known": False, "runs": 0, "note": "vehicle id not supported yet on <proto> protocol"}` and return None. Otherwise `parse_all(t.send("0902"), 0x49)`, candidates `p[3:20].decode("ascii", errors="replace")`, first that matches `VIN_RE` (same rule as `scanner.py:135`), `key = vehicle_key(vin)`; if none: vehicle `{"key": None, "known": False, "runs": 0, "note": "the car did not report a VIN"}`. Else `prior = self._profiles.load(key)`, set `self._key = key`, `self._prior = prior`, `self._vehicle = {"key": key, "known": prior is not None, "runs": prior["runs"] if prior else 0, "note": None}`, return prior. The VIN local variable is never stored on `self` and never logged.
- In `_run`: `prior = self._read_identity(t)` then, if `prior`, for each `p in prior["unsupported"]` that is in `active`: `misses[p] = _UNSUPPORTED_SWEEPS - 1` (one more miss drops it; an answer resets it and keeps it).
- New `_save_profile(self)` called in `_run`'s `finally` before the status line, only if `self._key and self.seq > 0`. Profile = `{"schema": 1, "key": key, "updated": <UTC ISO, seconds>, "runs": (prior["runs"] if prior else 0) + 1, "protocol": self._adapter["protocol"], "supported_pids": sorted(self._supported), "unsupported": sorted(set(self._unsupported)), "extras": list(self._extras)}`. Wrap the save in `try/except OSError as e: self.message = self.message or f"could not save the car profile: {e}"`.
- `LiveHub.__init__` adds `self._profiles = ProfileStore(session.config.home)`.
- `state()` adds `"vehicle": vehicle` (copied under `_data_lock`, like `codes`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_hub.py`; `make`, `wait_for`, `DEFAULT_PIDS`, `SimPort` already imported there)

```python
import json as _json

from obd_reader.simulator import SIM_VIN
from obd_reader.vehicle import vehicle_key

CORE = ["0C", "05", "0F"]  # 0F is a PID the simulator does not answer


def _run_once(tmp_path, pids=CORE, hz=10):
    hub, s, sim = make(tmp_path)
    hub.start(pids, hz=hz, seconds=30)
    assert wait_for(lambda: hub.state()["vehicle"] is not None)
    assert wait_for(lambda: hub.state()["seq"] >= 8)
    hub.stop()
    return hub


def test_vehicle_is_identified_by_key_only_and_first_run_is_a_new_car(tmp_path):
    hub = _run_once(tmp_path)
    v = hub.state()["vehicle"]
    assert v == {"key": vehicle_key(SIM_VIN), "known": False, "runs": 0, "note": None}
    assert SIM_VIN not in _json.dumps(hub.state()) and SIM_VIN[-6:] not in _json.dumps(hub.state())


def test_profile_is_saved_with_no_vin_in_it_and_second_run_knows_the_car(tmp_path):
    _run_once(tmp_path)
    f = tmp_path / "profiles" / f"{vehicle_key(SIM_VIN)}.json"
    text = f.read_text()
    assert SIM_VIN not in text and SIM_VIN[-6:] not in text
    saved = _json.loads(text)
    assert saved["runs"] == 1 and "0F" in saved["unsupported"] and "0C" in saved["supported_pids"]
    hub2 = _run_once(tmp_path)
    assert hub2.state()["vehicle"]["known"] is True and hub2.state()["vehicle"]["runs"] == 1
    assert _json.loads(f.read_text())["runs"] == 2


def test_known_unsupported_pid_is_dropped_after_one_miss_and_a_pid_that_answers_is_kept(tmp_path):
    from obd_reader.profiles import ProfileStore
    ProfileStore(tmp_path).save(vehicle_key(SIM_VIN), {"schema": 1, "key": vehicle_key(SIM_VIN), "updated": "", "runs": 4,
                                                        "protocol": None, "supported_pids": [], "unsupported": ["0F", "0C"], "extras": []})
    hub = _run_once(tmp_path)
    st = hub.state()
    assert "0F" in st["unsupported"] and "0C" not in st["unsupported"]  # 0C answers, so the old hint is overruled
    assert _json.loads((tmp_path / "profiles" / f"{vehicle_key(SIM_VIN)}.json").read_text())["unsupported"] == ["0F"]


def test_corrupt_profile_is_ignored_and_overwritten(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    (d / f"{vehicle_key(SIM_VIN)}.json").write_text("{oops")
    hub = _run_once(tmp_path)
    assert hub.state()["vehicle"]["known"] is False
    assert _json.loads((d / f"{vehicle_key(SIM_VIN)}.json").read_text())["runs"] == 1


def test_unwritable_profile_dir_does_not_break_the_run(tmp_path):
    (tmp_path / "profiles").write_text("a file where the folder should be")
    hub = _run_once(tmp_path)
    st = hub.state()
    assert st["seq"] >= 8 and st["status"] == "stopped" and "could not save the car profile" in (st["message"] or "")


def test_run_stopped_before_any_value_writes_no_profile(tmp_path):
    hub, _, _ = make(tmp_path)
    hub.start(["0F"], hz=10, seconds=30)  # nothing answers, so no value is ever stored
    assert wait_for(lambda: hub.state()["status"] != "running", 5)
    assert not (tmp_path / "profiles").exists()
```

- [ ] **Step 2: Run, expect FAIL** (`KeyError: 'vehicle'`)

Run: `PYTHONPATH=src pytest tests/test_hub.py -v -k "vehicle or profile or known_unsupported"`

- [ ] **Step 3: Implement per the design notes above.**

- [ ] **Step 4: Run the new tests, then the whole suite** (`PYTHONPATH=src pytest -q`), expect all PASS. Existing hub tests that compare the whole `state()` dict must be updated to include `"vehicle"` if any fail.

- [ ] **Step 5: Commit**

```bash
git add src/obd_reader/hub.py tests/test_hub.py
git commit -m "feat: hub identifies the car by partial VIN, loads and saves what past runs learned"
```

---

### Task 5: Page chip and docs

**Files:**
- Modify: `src/obd_reader/web/console.html` (a chip `id="chipCar"` in the status bar, set in `chips()`)
- Modify: `README.md` (one sentence plus a verified-table row marked "not yet run on a real car")
- Test: `tests/js/page_logic_test.js`, `tests/test_console_page.py`

**Interfaces:**
- Consumes: `state.vehicle` (`null` or `{key, known, runs, note}`).
- Produces: `#chipCar` text: `car ABCDEFGH-P · seen 3 times`, `car ABCDEFGH-P · new`, the `note` when the key is `null`, or `car ?` when `vehicle` is `null`. Always via `textContent`.

- [ ] **Step 1: Write the failing tests.** In `page_logic_test.js` (same harness as the code tests), states from `statesFor(3, idle)` with `vehicle` added: `{key: 'ABCDEFGH-P', known: true, runs: 3, note: null}` expects `/ABCDEFGH-P/` and `/seen 3 times/` in `env.el('chipCar').textContent`; `known: false` expects `/new/`; `{key: null, note: 'the car did not report a VIN'}` expects the note; no `vehicle` field expects `car ?`. A hostile `note` of `<img src=x onerror=1>` must appear unmodified in `textContent` (no markup). In `test_console_page.py`: `assert 'id="chipCar"' in HTML`.

- [ ] **Step 2: Run, expect FAIL** (`node tests/js/page_logic_test.js src/obd_reader/web/console.html`)

- [ ] **Step 3: Implement** the chip next to `chipConn` and its update in `chips()`:

```js
    var v = st.vehicle;
    $('chipCar').textContent = !v ? 'car ?' : v.key ? 'car ' + v.key + ' · ' + (v.known ? 'seen ' + v.runs + (v.runs === 1 ? ' time' : ' times') : 'new') : (v.note || 'car ?');
```

- [ ] **Step 4: Run `PYTHONPATH=src pytest -q`, expect all PASS.** Update `README.md`: under the console section, one sentence ("the console shows a partial-VIN car key and remembers, per key, which PIDs the car never answers; profiles are local in `profiles/`"); add a table row "Car identification and learned profile | done in demo | not yet run against a real car".

- [ ] **Step 5: Commit**

```bash
git add src/obd_reader/web/console.html README.md tests/js/page_logic_test.js tests/test_console_page.py
git commit -m "feat: console shows the car key and whether the car was seen before"
```

---

## Self-Review

- **Spec coverage:** key from partial VIN (Task 1); local learned store (Task 2); identity at connect, apply and save (Task 4); visible in the console (Task 5). Deliberately deferred and listed in the header: curated profiles, export/import, protocol pinning, manual fallback, Mode 22.
- **Placeholders:** none.
- **Type consistency:** `vehicle_key` (Task 1) feeds `KEY_RE` (Task 2) and `hub` (Task 4); `SIM_VIN` (Task 3) is what Task 4 tests key on; the profile dict fields match between `ProfileStore.load` (Task 2) and `_save_profile` (Task 4); `state.vehicle` fields match the page (Task 5).
- **Known limit, stated:** identification happens after the first good sweep (the VIN needs the bus search to have finished), so a profile cannot speed up connecting or change the first sweep. Its step-1 value is fewer wasted sweeps on PIDs the car never answers, a visible "seen before", and the start of the library. Protocol pinning comes with the curated profiles step.
