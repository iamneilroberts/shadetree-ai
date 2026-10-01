# Console stage 2: Dashboard and scenarios Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Overview with a Dashboard (default view): up to 8 gauges on top for the chosen scenario, the full PID table below; five built-in scenarios, in-page editing saved per scenario, and optional shared defaults from `shadetree-ai console --scenarios FILE`.

**Architecture:** The Dashboard is built only from the stage 1 shared parts (`panel`, `gauges`, `pidRows`, `pidTableEl`). Scenario logic (built-ins, merge with server defaults, saved edits, edit operations) is pure functions on `{pid, form}` arrays, exposed through the existing `window.__shadetreeParts` test hook and tested in node. The server only validates a JSON file and serves it at `GET /api/scenarios`; the page fetches it once. The Dashboard keeps section id `v0`, so the Overview's `o_tiles`/`o_attn`/`o_note` strip and its `#v0` CSS carry over as the General strip.

**Tech Stack:** One-file `src/obd_reader/web/console.html` (vanilla JS, hash-pinned CSP), Python 3.11 stdlib HTTP server, pytest, `node tests/js/page_logic_test.js`.

**Spec:** `docs/superpowers/specs/2026-10-01-console-coherence-design.md` (Stage 2, lines 26-35, plus the retained-features list). Stage 1 plan for style: `docs/superpowers/plans/2026-10-01-console-stage1-skin-and-shared-parts.md`.

## Global Constraints

- Public repo, MIT: no VINs, real transcripts, `runs/`, `profiles/`, `shadetree-share*` in any file or test. Synthetic fixtures only.
- Read-only: no new data capture, no new write path, no Mode 22. The only new server route is `GET /api/scenarios`.
- One file: `console.html` keeps exactly one `<script>` and one `<style>`, no external URLs, no framework; the CSP hash is computed from the first `<script>` (`console.py:39-45`), so scenarios reach the page by `fetch`, never templated into the HTML.
- Every colour in the page is a CSS variable (`test_colours_live_only_in_the_token_blocks`).
- Text from a scenarios file or localStorage is set with `textContent` only, never `innerHTML`.
- At most 8 gauges per scenario; PIDs are exactly two hex digits (stored uppercase); gauge forms are `dial | bar | seven`.
- A gauge for a PID not in the run is dimmed with "not in this run"; never a fake zero.
- Retained features (spec line 17) stay reachable; `RETAINED` in `tests/test_console_page.py` must stay green at every commit.
- Commands (run from the worktree root; `PYTHONPATH=src` makes the worktree package shadow the editable install):
  - node: `node tests/js/page_logic_test.js src/obd_reader/web/console.html` (prints `page logic OK`)
  - page tests: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py`
  - full suite: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q` (661 passed before stage 2)
- Commit per task, stage files by name, no attribution lines. Do not push or merge; Neil says "merge and push".

## Review Focus

Failure modes the spec implies that no task's feature tests would otherwise hit; each has a test in the task that owns the code.

1. `--scenarios` file with `Infinity`/`NaN`, a ninth gauge, a duplicate id, a PID like `constructor` or `7`, a 100 KB file, a name with control characters, or an unknown key: server refuses with a clear message, nothing partial is served (Task 1).
2. localStorage holds corrupt JSON, an unknown PID, a ninth gauge, or storage throws: the scenario falls back to its defaults and the page still renders (Task 2).
3. A scenario PID not in the run, and a run with no channels at all: dimmed gauge with a note, no needle, no `0` (Task 3).
4. Editing at the 8-gauge cap, removing the last gauge, adding a PID already shown: add refused at the cap, empty panel says so and offers Reset, no duplicates (Task 4).
5. A server scenario named `<img onerror=...>` or reusing the id `general`: shown as text, and it replaces the built-in General rather than duplicating it (Tasks 2-3).

---

## File Structure

| File | Change |
|---|---|
| `src/obd_reader/scenarios.py` (new) | `parse_scenarios(text)`, `load_scenarios(path)`: validation only |
| `src/obd_reader/console.py` | `scenarios` kwarg on `ConsoleServer`/`ConsoleService`; `GET /api/scenarios` |
| `src/obd_reader/__main__.py` | `--scenarios FILE` on `console`; load and validate before start |
| `src/obd_reader/web/console.html` | scenario logic, Dashboard view, edit mode; remove `#vp` preview |
| `tests/test_scenarios.py` (new) | validation and route tests |
| `tests/test_console_page.py` | size budget, `RETAINED` entries, contrast pairs, colour-regex widening |
| `tests/js/page_logic_test.js` | scenario logic, Dashboard, edit mode; `/api/scenarios` stub; drop `#vp` test |
| `docs/design.md` §7b, `README.md` | document Dashboard, scenarios, `--scenarios` |

---

### Task 1: `--scenarios FILE` validation and `/api/scenarios`

**Files:**
- Create: `src/obd_reader/scenarios.py`, `tests/test_scenarios.py`
- Modify: `src/obd_reader/console.py` (`ConsoleServer.__init__` ~line 55-61, route tuples ~190 and ~214, route handler ~198-210, `ConsoleService.__init__` ~279-301), `src/obd_reader/__main__.py` (`console_main` 43-75, `console` subparser 119-137)

**Interfaces:**
- Produces: `scenarios.parse_scenarios(text: str) -> list[dict]` returning `[{"id": str, "name": str, "gauges": [{"pid": "0C", "form": "dial"}, ...]}]`, raising `ValueError(message)`; `scenarios.load_scenarios(path: Path) -> list[dict]` (size check, then parse; `OSError` propagates); `ConsoleServer(..., scenarios: list[dict] | None = None)`; `ConsoleService(..., scenarios=None)`; `GET /api/scenarios` -> `{"scenarios": [...]}` (empty list when no file).
- File format: `{"scenarios": [{"id": "towing", "name": "Towing", "gauges": [{"pid": "05", "form": "dial"}]}]}`. `form` optional, default `dial`. Limits: file at most 32,768 bytes; at most 12 scenarios; ids `^[a-z][a-z0-9-]{0,23}$` and unique; name 1-24 printable characters; 1-8 gauges; PID two hex digits (normalised to uppercase); no other keys.

- [ ] **Step 1: Write the failing validation tests** in `tests/test_scenarios.py`

```python
import json

import pytest

from obd_reader.scenarios import MAX_BYTES, load_scenarios, parse_scenarios


def doc(*scen):
    return json.dumps({"scenarios": list(scen)})


def sc(id="towing", name="Towing", gauges=None):
    return {"id": id, "name": name, "gauges": gauges if gauges is not None else [{"pid": "05"}]}


def test_valid_file_is_normalised():
    out = parse_scenarios(doc(sc(gauges=[{"pid": "0c", "form": "bar"}, {"pid": "05"}])))
    assert out == [{"id": "towing", "name": "Towing",
                    "gauges": [{"pid": "0C", "form": "bar"}, {"pid": "05", "form": "dial"}]}]


@pytest.mark.parametrize("text", [
    "not json",
    '{"scenarios": [{"id": "a", "name": "A", "gauges": [{"pid": "05", "lo": Infinity}]}]}',
    '{"scenarios": NaN}',
    "[]",
    '{"scenarios": [], "extra": 1}',
    doc(sc(gauges=[])),
    doc(sc(gauges=[{"pid": "05"}] * 9)),
    doc(sc(gauges=[{"pid": "constructor"}])),
    doc(sc(gauges=[{"pid": "7"}])),
    doc(sc(gauges=[{"pid": "05", "form": "pie"}])),
    doc(sc(gauges=[{"pid": "05", "lo": 0}])),
    doc(sc(id="Bad Id")),
    doc(sc(id="x" * 25)),
    doc(sc(name="")),
    doc(sc(name="x" * 25)),
    doc(sc(name="a\x00b")),
    doc(sc(), sc()),
    doc(*[sc(id="s%d" % i) for i in range(13)]),
])
def test_bad_files_are_refused_with_a_message(text):
    with pytest.raises(ValueError) as e:
        parse_scenarios(text)
    assert str(e.value)


def test_oversized_file_is_refused_before_parsing(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(" " * (MAX_BYTES + 1))
    with pytest.raises(ValueError, match="too large"):
        load_scenarios(p)


def test_load_reads_a_good_file(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(doc(sc()))
    assert load_scenarios(p)[0]["id"] == "towing"
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_scenarios.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'obd_reader.scenarios'`.

- [ ] **Step 3: Write `src/obd_reader/scenarios.py`**

```python
"""Shared console scenarios: validate a --scenarios FILE (hex PIDs, at most 8 gauges, short names)."""
import json
import re
from pathlib import Path

MAX_BYTES = 32_768
MAX_SCENARIOS = 12
MAX_GAUGES = 8
FORMS = ("dial", "bar", "seven")
_ID = re.compile(r"[a-z][a-z0-9-]{0,23}\Z")
_PID = re.compile(r"[0-9A-Fa-f]{2}\Z")


def _reject_constant(name: str):
    raise ValueError(f"{name} is not allowed in a scenarios file")


def _gauge(g, where: str) -> dict:
    if not isinstance(g, dict) or not set(g) <= {"pid", "form"}:
        raise ValueError(f'{where}: a gauge is {{"pid": "0C", "form": "dial"}} and nothing else')
    pid = g.get("pid")
    if not isinstance(pid, str) or not _PID.match(pid):
        raise ValueError(f"{where}: pid must be two hex digits, got {pid!r}")
    form = g.get("form", "dial")
    if form not in FORMS:
        raise ValueError(f"{where}: form must be one of {', '.join(FORMS)}")
    return {"pid": pid.upper(), "form": form}


def parse_scenarios(text: str) -> list[dict]:
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from None
    if not isinstance(data, dict) or set(data) != {"scenarios"} or not isinstance(data["scenarios"], list):
        raise ValueError('expected {"scenarios": [...]}')
    if len(data["scenarios"]) > MAX_SCENARIOS:
        raise ValueError(f"at most {MAX_SCENARIOS} scenarios")
    out, ids = [], set()
    for i, s in enumerate(data["scenarios"]):
        where = f"scenario {i + 1}"
        if not isinstance(s, dict) or set(s) != {"id", "name", "gauges"}:
            raise ValueError(f"{where}: needs exactly id, name, gauges")
        if not isinstance(s["id"], str) or not _ID.match(s["id"]):
            raise ValueError(f"{where}: id must be lowercase letters, digits, dashes (max 24)")
        if s["id"] in ids:
            raise ValueError(f"{where}: duplicate id {s['id']!r}")
        ids.add(s["id"])
        name = s["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 24 or not name.isprintable():
            raise ValueError(f"{where}: name must be 1-24 printable characters")
        if not isinstance(s["gauges"], list) or not 1 <= len(s["gauges"]) <= MAX_GAUGES:
            raise ValueError(f"{where}: 1 to {MAX_GAUGES} gauges")
        out.append({"id": s["id"], "name": name, "gauges": [_gauge(g, where) for g in s["gauges"]]})
    return out


def load_scenarios(path: Path) -> list[dict]:
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"scenarios file too large (over {MAX_BYTES} bytes)")
    return parse_scenarios(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_scenarios.py`
Expected: all pass.

- [ ] **Step 5: Write the failing route test** (append to `tests/test_scenarios.py`)

Copy the `srv` fixture and `call` helper idiom from `tests/test_console_review_fixes.py` / `tests/test_console.py` (they build `ConsoleServer(hub, token=...)` and call routes with the token). Add two tests: a server built with `scenarios=[{"id": "towing", "name": "Towing", "gauges": [{"pid": "05", "form": "dial"}]}]` answers `GET /api/scenarios` with status 200 and `{"scenarios": [that list]}`; a server built without answers `{"scenarios": []}`; and the request without the token is refused exactly as `/api/help` is (same `_guard` call). Also assert `POST /api/scenarios` gets the same 405 as `POST /api/help`.

- [ ] **Step 6: Run to verify it fails**, then implement in `console.py`

Run the new tests: expect 404 on `/api/scenarios`. Implement: add `scenarios=None` to `ConsoleServer.__init__` (store `self.scenarios = list(scenarios or [])`); add `"/api/scenarios"` to both GET route tuples (~190 and ~214); add a handler branch beside `/api/help` that runs `_guard(post=False)` and returns `{"scenarios": outer.scenarios}` as JSON with `_CSP_JSON`; add `scenarios=None` to `ConsoleService.__init__` and pass it into the `ConsoleServer(...)` call at ~301 as `scenarios=self._scenarios`.

- [ ] **Step 7: Wire the CLI** in `__main__.py`

Add beside `--examples-dir` (line 131): `co.add_argument("--scenarios", type=Path, default=None, metavar="FILE", help="shared gauge scenarios (JSON); see docs/design.md 7b")`. In `console_main`, before building `ConsoleService`, `scen = None` and, if `args.scenarios`, `try: scen = load_scenarios(args.scenarios) except (OSError, ValueError) as exc:` print `f"--scenarios {args.scenarios}: {exc}"` to stderr and return the same non-zero code the function already uses for argument errors (read the function first; match it). Pass `scenarios=scen` into `ConsoleService(...)` (lines 49-51). Add one test in `tests/test_scenarios.py` that calls `console_main` (or the parser plus loader, whichever the existing `tests/test_console_tools.py` idiom allows) with a bad file and asserts a non-zero result and the message on stderr.

- [ ] **Step 8: Run the full suite, commit**

Run: full suite. Expected: 661 + new tests pass.

```bash
git add src/obd_reader/scenarios.py src/obd_reader/console.py src/obd_reader/__main__.py tests/test_scenarios.py
git commit -m "feat: --scenarios FILE (validated: hex PIDs, at most 8 gauges, short names, 32 KB) and GET /api/scenarios"
```

---

### Task 2: Scenario logic in the page (pure functions, no UI yet)

**Files:**
- Modify: `src/obd_reader/web/console.html` (insert after `pidTableEl`, before `PREVIEW` ~line 1009; hook at ~1361), `tests/js/page_logic_test.js` (fetch stub in `makeEnv`; new section before `console.log('page logic OK')`), `tests/test_console_page.py:99` (size budget)

**Interfaces:**
- Produces (all inside the page IIFE, exposed via the hook): `BUILTIN` (array of `{id, name, gauges: [{pid, form}]}`), `cleanSpecs(arr) -> [{pid, form}]` (drops non-objects, PIDs not matching `/^[0-9A-F]{2}$/`, bad forms to `dial`, duplicate pid+form, beyond 8), `scenarioList(server) -> [{id, name, gauges}]` (built-ins in order, a server entry with a built-in's id replaces it in place, new ids appended, each cleaned), `loadSaved(id) -> [{pid,form}] | null`, `saveSaved(id, specs, defaults)` (removes the key when `specs` equals `defaults`), `specsFor(sc) -> [{pid, form}]` (saved if valid and non-empty-or-explicitly-empty, else `sc.gauges`), `editAdd(specs, pid)`, `editRemove(specs, i)`, `editMove(specs, i, d)`, `editForm(specs, i)` (each returns a new array; `editAdd` refuses a ninth gauge or a PID already shown and returns the input unchanged; `editForm` cycles `dial -> bar -> seven -> dial` but keeps `seven` for a PID with no `GAUGE` range). localStorage keys `shadetree.scen.<id>` (JSON array) and `shadetree.scenario` (last chosen id).
- Test hook gains: `gaugeModel, segDigits, BUILTIN, cleanSpecs, scenarioList, loadSaved, saveSaved, specsFor, editAdd, editRemove, editMove, editForm`.

Built-in sets (PIDs from the spec; forms chosen so each set shows a mix):

```js
var BUILTIN = [
  { id: 'general', name: 'General', gauges: [['0C','dial'],['0D','dial'],['05','dial'],['04','bar'],['11','bar'],['0B','bar'],['42','seven'],['06','seven']] },
  { id: 'fuel', name: 'Fuel trims', gauges: [['06','bar'],['07','bar'],['08','bar'],['09','bar'],['44','dial'],['0B','dial'],['0C','dial'],['04','seven']] },
  { id: 'cooling', name: 'Cooling', gauges: [['05','dial'],['0F','dial'],['04','bar'],['0C','dial'],['0D','seven'],['42','seven']] },
  { id: 'idle', name: 'Idle / misfire', gauges: [['0C','dial'],['04','bar'],['0B','bar'],['06','seven'],['0E','dial'],['11','bar'],['42','seven']] },
  { id: 'charging', name: 'Charging / electrical', gauges: [['42','dial'],['0C','dial'],['04','bar'],['11','bar']] }
].map(function (s) { return { id: s.id, name: s.name, gauges: s.gauges.map(function (g) { return { pid: g[0], form: g[1] }; }) }; });
```

- [ ] **Step 1: Raise the size budget on purpose.** In `tests/test_console_page.py:99` change `112_000` to `130_000` and update the test's comment to say stage 2 adds the Dashboard and scenarios (about 10 KB) and removes the `#vp` preview. Run the page tests; expect pass.

- [ ] **Step 2: Add the `/api/scenarios` stub to `makeEnv`.** Read `tests/js/page_logic_test.js:24-66` first. In the sandbox `fetch`, before the state-sequence fallback, answer a URL ending `/api/scenarios` with `{ scenarios: page.scenarios || [] }` (or a non-ok response when `page.scenariosFail` is set). Run node; expect `page logic OK` still.

- [ ] **Step 3: Write the failing node tests** (insert before `console.log('page logic OK')`)

```js
// 8) Scenario logic
{
  const e = makeEnv(statesFor(5, base), 'v0', OVF); await e.tick();
  const P = e.parts();
  const ids = Array.from(P.BUILTIN).map(s => s.id);
  assert.deepStrictEqual(ids, ['general', 'fuel', 'cooling', 'idle', 'charging']);
  P.BUILTIN.forEach(s => { assert.ok(s.gauges.length >= 1 && s.gauges.length <= 8); });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(P.cleanSpecs([
    { pid: '0c', form: 'bar' }, { pid: '0C', form: 'bar' }, { pid: 'constructor' }, { pid: '7' }, 5, null, { pid: '05', form: 'pie' },
    ...Array.from({ length: 10 }, (_, i) => ({ pid: '1' + i })) ]))).slice(0, 2),
    [{ pid: '05', form: 'dial' }, { pid: '10', form: 'dial' }]);   // lower-case and dup pid+form dropped, bad form -> dial, capped at 8
  const l = P.scenarioList([{ id: 'general', name: 'Mine', gauges: [{ pid: '05', form: 'seven' }] }, { id: 'towing', name: '<img onerror=x>', gauges: [{ pid: '0C' }] }]);
  assert.deepStrictEqual(Array.from(l).map(s => s.id), ['general', 'fuel', 'cooling', 'idle', 'charging', 'towing']);
  assert.strictEqual(l[0].name, 'Mine');
  assert.strictEqual(l[5].name, '<img onerror=x>');   // kept as data; the UI sets it with textContent
  const s3 = [{ pid: '0C', form: 'dial' }, { pid: '05', form: 'dial' }];
  assert.deepStrictEqual(JSON.parse(JSON.stringify(P.editAdd(s3, '04'))).map(g => g.pid), ['0C', '05', '04']);
  assert.strictEqual(P.editAdd(s3, '0C').length, 2);                       // already shown
  const eight = Array.from({ length: 8 }, (_, i) => ({ pid: '0' + i, form: 'dial' }));
  assert.strictEqual(P.editAdd(eight, '0F'), eight);                       // cap: unchanged, same array
  assert.deepStrictEqual(JSON.parse(JSON.stringify(P.editRemove(s3, 0))), [{ pid: '05', form: 'dial' }]);
  assert.strictEqual(P.editRemove([s3[0]], 0).length, 0);                  // the last gauge can go
  assert.deepStrictEqual(P.editMove(s3, 0, 1).map(g => g.pid), ['05', '0C']);
  assert.deepStrictEqual(P.editMove(s3, 0, -1).map(g => g.pid), ['0C', '05']);   // off the end: unchanged
  assert.deepStrictEqual(['dial', 'bar', 'seven', 'dial'], [0, 1, 2, 3].reduce((a) => a.concat(P.editForm([{ pid: '0C', form: a[a.length - 1] }], 0)[0].form), ['dial']).slice(0, 4));
  assert.strictEqual(P.editForm([{ pid: '99', form: 'seven' }], 0)[0].form, 'seven');   // no range: stays seven
}
// 9) Saved scenarios survive corrupt storage
{
  const store = { 'shadetree.scen.general': '{not json', 'shadetree.scen.fuel': JSON.stringify([{ pid: '0C', form: 'bar' }]),
                  'shadetree.scen.idle': JSON.stringify([{ pid: 'zz' }]) };
  const e = makeEnv(statesFor(5, base), 'v0', OVF, [], store); await e.tick();
  const P = e.parts(), L = P.scenarioList([]);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(P.specsFor(L[0]))), JSON.parse(JSON.stringify(L[0].gauges)));   // corrupt -> defaults
  assert.deepStrictEqual(JSON.parse(JSON.stringify(P.specsFor(L[1]))), [{ pid: '0C', form: 'bar' }]);              // valid -> used
  assert.deepStrictEqual(JSON.parse(JSON.stringify(P.specsFor(L[3]))), JSON.parse(JSON.stringify(L[3].gauges)));   // all-invalid -> defaults
  P.saveSaved('cooling', [{ pid: '05', form: 'bar' }], L[2].gauges);
  assert.ok(store['shadetree.scen.cooling']);
  P.saveSaved('cooling', L[2].gauges, L[2].gauges);
  assert.strictEqual(store['shadetree.scen.cooling'], undefined);    // equal to defaults: key removed
  const t = makeEnv(statesFor(5, base), 'v0', OVF, [], {}, { storageThrows: true }); await t.tick();
  assert.doesNotThrow(() => t.parts().specsFor(t.parts().scenarioList([])[0]));   // blocked storage: defaults, no throw
}
```

Adjust the harness idioms (`store` semantics for removed keys, `makeEnv` argument order) to what `makeEnv` actually does; the assertions are the contract.

- [ ] **Step 4: Run node to verify it fails** (`P.BUILTIN` undefined).

- [ ] **Step 5: Implement in `console.html`** (after `pidTableEl`): `BUILTIN` as above, then

```js
  var SCEN_MAX = 8, HEXPID = /^[0-9A-F]{2}$/;
  function cleanSpecs(a) {   // any JSON -> [{pid, form}]: two-hex-digit PIDs (upper-cased), a known form, no repeated pid+form, at most 8
    var out = [], seen = Object.create(null);
    (Array.isArray(a) ? a : []).forEach(function (g) {
      if (!g || typeof g !== 'object' || typeof g.pid !== 'string') return;
      var pid = g.pid.toUpperCase(), form = FORMS.indexOf(g.form) >= 0 ? g.form : 'dial', k = pid + ':' + form;
      if (!HEXPID.test(pid) || seen[k] || out.length >= SCEN_MAX) return;
      seen[k] = true; out.push({ pid: pid, form: form });
    });
    return out;
  }
  function scenarioList(server) {   // the built-ins in order; a server scenario with a built-in's id replaces it, others are appended
    var list = BUILTIN.map(function (s) { return { id: s.id, name: s.name, gauges: s.gauges.slice() }; });
    (Array.isArray(server) ? server : []).forEach(function (s) {
      if (!s || typeof s.id !== 'string' || typeof s.name !== 'string') return;
      var g = cleanSpecs(s.gauges), at = -1;
      if (!g.length) return;
      list.forEach(function (x, i) { if (x.id === s.id) at = i; });
      var item = { id: s.id, name: s.name, gauges: g };
      if (at >= 0) list[at] = item; else list.push(item);
    });
    return list;
  }
  function loadSaved(id) {
    try { var s = cleanSpecs(JSON.parse(localStorage.getItem('shadetree.scen.' + id))); return s.length ? s : null; } catch (x) { return null; }
  }
  function saveSaved(id, specs, defaults) {   // an edit equal to the defaults is not stored
    try {
      if (JSON.stringify(specs) === JSON.stringify(defaults)) localStorage.removeItem('shadetree.scen.' + id);
      else localStorage.setItem('shadetree.scen.' + id, JSON.stringify(specs));
    } catch (x) {}
  }
  function specsFor(sc) { return loadSaved(sc.id) || sc.gauges; }
  function editAdd(specs, pid) {
    if (specs.length >= SCEN_MAX || specs.some(function (g) { return g.pid === pid; })) return specs;
    return specs.concat([{ pid: pid, form: GAUGE[pid] ? 'dial' : 'seven' }]);
  }
  function editRemove(specs, i) { return specs.filter(function (g, j) { return j !== i; }); }
  function editMove(specs, i, d) {
    var j = i + d; if (j < 0 || j >= specs.length) return specs;
    var out = specs.slice(); out[i] = specs[j]; out[j] = specs[i]; return out;
  }
  function editForm(specs, i) {
    return specs.map(function (g, j) { return j !== i || !GAUGE[g.pid] ? g : { pid: g.pid, form: FORMS[(FORMS.indexOf(g.form) + 1) % FORMS.length] }; });
  }
```

Hook (line ~1361): add `gaugeModel: gaugeModel, segDigits: segDigits, BUILTIN: BUILTIN, cleanSpecs: cleanSpecs, scenarioList: scenarioList, loadSaved: loadSaved, saveSaved: saveSaved, specsFor: specsFor, editAdd: editAdd, editRemove: editRemove, editMove: editMove, editForm: editForm`.

- [ ] **Step 6: Run node and page tests; expect pass. Commit.**

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js tests/test_console_page.py
git commit -m "feat: console scenario logic (five built-in sets, server defaults merged by id, per-scenario saved edits that survive corrupt or blocked storage, pure add/remove/move/form operations); size budget raised to 130,000 for stage 2"
```

---

### Task 3: Dashboard view replaces Overview and `#vp`

**Files:**
- Modify: `src/obd_reader/web/console.html` (nav 322, section `v0` 380-387, `.view` CSS, `render()` 1152-1174, remove `PREVIEW`/`preview`/`renderParts` 1010-1020 and the `vp` section 498-499 and `vp` branch 1164, init 1343), `tests/js/page_logic_test.js` (section 8's neighbours; delete the `#vp` test at 723-731; Overview tests 6 and 7 keep working because ids `o_tiles/o_attn/o_note` stay), `tests/test_console_page.py` (`RETAINED`)

**Interfaces:**
- Consumes: Task 2's `scenarioList`, `specsFor`, `cleanSpecs`; stage 1's `panel`, `gauges`, `pidRows`, `pidTableEl`, `renderOverview`.
- Produces: section `#v0` (tab label **Dashboard**, still `data-view="v0"`, still default) containing `#d_tabs` (scenario tab buttons `.stab[data-scen]`, desktop), `#d_sel` (`<select>`, phone), `#d_edit` (pencil, wired in Task 4), `#d_panel` (a `panel()` whose body holds the gauges), `#d_strip` (the Overview tiles, attention list and note, visible only in the General scenario), `#d_table` (a `pidTableEl()` of every PID in the run, scenario PIDs get class `scen`), `#o_more` link. Functions `renderDashboard()`, `curScenario()`, `setScenario(id)`. State `SC = { list, id }` (`list` from `scenarioList`, replaced when `/api/scenarios` arrives; `id` from `localStorage['shadetree.scenario']` if it names a scenario, else `general`).
- Sections unchanged: v3 Guided test, v4 Analyzer, v5 Handheld, v6 All readings (the "On-board tests"/Mode 06 section and Capture all live there and stay).

- [ ] **Step 1: Write the failing node tests** (insert after section 9)

```js
// 10) Dashboard
{
  const e = makeEnv(statesFor(30, base), 'v0', OVF); for (let k = 0; k < 32; k++) await e.tick();
  const tabs = Array.from(e.el('d_tabs').children);
  assert.deepStrictEqual(tabs.map(t => t.textContent), ['General', 'Fuel trims', 'Cooling', 'Idle / misfire', 'Charging / electrical']);
  assert.strictEqual(Array.from(e.el('d_sel').children).length, 5);
  const gk = () => Array.from(e.el('d_panel').querySelectorAll ? e.el('d_panel').querySelectorAll('[data-key]') : flat(e.el('d_panel')).filter(n => n.getAttribute && n.getAttribute('data-key')));
  assert.strictEqual(gk().length, 8);                                        // General: 8 gauges
  assert.ok(Array.from(e.el('d_table').querySelectorAll ? e.el('d_table').querySelectorAll('tr') : []).length >= 0);
  assert.strictEqual(e.el('d_strip').hidden, false);                         // General shows the health strip
  tabs[1].click ? tabs[1].click() : e.handlers.click && 0;                   // adapt to the harness's click idiom
  // after choosing Fuel trims: strip hidden, 8 gauges, storage remembers the choice
}
// 11) Dashboard honesty: a PID not in the run is dimmed, never a zero; a run with no channels says so
{
  const e = makeEnv(statesFor(30, base), 'v0', OVF); for (let k = 0; k < 32; k++) await e.tick();
  // base() has no 0D, so General's speed gauge is dim with 'not in this run' and no value
  const dim = flat(e.el('d_panel')).filter(n => /\bdim\b/.test(n.className || ''));
  assert.ok(dim.length >= 1);
  assert.ok(dim.some(n => flat(n).some(c => c.textContent === 'not in this run')));
  const idle = makeEnv([{ status: 'idle', channels: {}, stats: {}, extras: {}, seq: 1 }], 'v0', OVF); await idle.tick();
  assert.ok(flat(idle.el('d_panel')).some(n => n.textContent === 'not sampling'));
}
// 12) The #vp preview is gone and Guided test still updates
{
  const e = makeEnv(statesFor(5, base), 'v3', OVF); await e.tick();
  assert.ok(/target|in range/.test(e.el('v3band').textContent));
}
```

Before writing, read `makeEnv`, `walk`, `flat`, `findQ` (`tests/js/page_logic_test.js:6-66`) and the existing section 6 (line 278) and rewrite the placeholder click/query lines in test 10 with the harness's real idioms (how `Panel`/`gauge` tests at 643-720 find nodes and click buttons). The assertions (tab names and order, 5 options, 8 gauges, strip visible only in General, dim gauge with "not in this run", "not sampling" with no channels, `v3band` still written) are the contract. Add: after clicking the Fuel trims tab, `d_strip` is hidden and `localStorage['shadetree.scenario']` is `fuel`; with `store['shadetree.scenario'] = 'nope'` the page opens on General; with `page.scenarios` containing a scenario named `<img onerror=x>` its tab's `textContent` is that literal text and the tab has no child elements.

- [ ] **Step 2: Run node; expect FAIL** (`d_tabs` missing).

- [ ] **Step 3: Replace the markup.** In the nav (322) change the label to `Dashboard`. Replace the `v0` section (380-387) with:

```html
  <section class="view is-active" id="v0" role="tabpanel">
    <div class="scenbar">
      <div class="stabs" id="d_tabs" role="tablist" aria-label="Scenarios"></div>
      <select class="ssel" id="d_sel" aria-label="Scenario"></select>
      <button class="qbtn" id="d_edit" type="button" aria-pressed="false" title="Edit this scenario's gauges">&#9998;</button>
    </div>
    <div id="d_panel"></div>
    <div id="d_strip">
      <h3 class="sec">Health</h3>
      <div class="tiles" id="o_tiles"></div>
      <h3 class="sec">Needs attention</h3>
      <div class="attn" id="o_attn"></div>
      <p class="note" id="o_note"></p>
    </div>
    <div id="d_table"></div>
    <a class="more" href="#v6" id="o_more">Mode 06 results, capture options and the full readings view &rarr;</a>
  </section>
```

Delete the `vp` section (498-499 and its comment). CSS (add near the `.panel` rules ~293-298, colours only via existing tokens): `.scenbar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }`, `.stabs { display: flex; gap: 6px; flex-wrap: wrap; flex: 1; }`, `.stab` styled like `.vbtn` (reuse its token colours; `.stab.is-active` like `.vbtn.is-active`), `.ssel { display: none; flex: 1; }`, and `@media (max-width: 600px) { .stabs { display: none; } .ssel { display: block; } }`, `#d_table tr.scen td:first-child { box-shadow: inset 3px 0 0 var(--cyan); }` (use whichever accent token the Plain and Retro sets already define for emphasis; add no new colour literal), `.gauges { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }` (was 130; fixes the "ENGINE SPE…" ellipsis).

- [ ] **Step 4: Implement the logic** (replace the `PREVIEW`/`preview`/`renderParts` block at 1010-1020)

```js
  var SC = { list: scenarioList([]), id: 'general' }, DB = null;
  try { var lastId = localStorage.getItem('shadetree.scenario'); if (lastId && SC.list.some(function (s) { return s.id === lastId; })) SC.id = lastId; } catch (x) {}
  function curScenario() { return SC.list.filter(function (s) { return s.id === SC.id; })[0] || SC.list[0]; }
  function setScenario(id) {
    SC.id = id;
    try { localStorage.setItem('shadetree.scenario', id); } catch (x) {}
    drawTabs(); render();
  }
  function drawTabs() {   // scenario names come from a file or the page: textContent only
    var tabs = $('d_tabs'), sel = $('d_sel');
    tabs.textContent = ''; sel.textContent = '';
    SC.list.forEach(function (s) {
      var b = el('button', 'stab' + (s.id === SC.id ? ' is-active' : ''), s.name), o = el('option', '', s.name);
      b.setAttribute('type', 'button'); b.setAttribute('data-scen', s.id); b.setAttribute('role', 'tab');
      b.addEventListener('click', function () { setScenario(s.id); });
      o.value = s.id; if (s.id === SC.id) o.selected = true;
      tabs.appendChild(b); sel.appendChild(o);
    });
    sel.value = SC.id;
  }
  $('d_sel').addEventListener('change', function () { setScenario($('d_sel').value); });
  function renderDashboard() {
    if (!DB) {
      var p = panel(''), t = pidTableEl(), g = el('div', 'gauges');
      p.body.appendChild(g); $('d_panel').appendChild(p.root); $('d_table').appendChild(t.root);
      DB = { p: p, g: g, rows: t.body };
      drawTabs();
    }
    var sc = curScenario(), specs = specsFor(sc), chs = (state && state.channels) || {}, ids = Object.keys(chs).sort(), mine = {};
    DB.p.name.textContent = sc.name;
    gauges(DB.g, specs);
    specs.forEach(function (s) { mine[s.pid] = true; });
    pidRows(DB.rows, ids);
    Array.prototype.forEach.call(DB.rows.children, function (r) { r.classList.toggle('scen', mine[r.getAttribute('data-key')] === true); });
    $('d_strip').hidden = sc.id !== 'general';
    if (sc.id === 'general') renderOverview();
  }
```

`mine` is a plain object keyed by validated two-hex PIDs, which is safe because `cleanSpecs` already rejected anything else. In `render()` change the branches: `v0` -> `renderDashboard()`; delete the `vp` branch; change the final `else` to `else if (view === 'v3')`. Remove `renderParts` use at the hook. Keep the hook's other entries. Load the server scenarios once, after `loadHelp();` at the end of the script, copying `loadHelp`'s fetch idiom (token and error handling): on success `SC.list = scenarioList(j.scenarios); if (!SC.list.some(function (s) { return s.id === SC.id; })) SC.id = 'general'; if (DB) drawTabs(); render();`; on failure leave the built-ins and do nothing. Update the Overview note wording only if a test requires it.

- [ ] **Step 5: Update `RETAINED`** in `tests/test_console_page.py`: add `"Dashboard": ['data-view="v0"', 'id="d_tabs"', 'id="d_table"', 'id="d_edit"']`; keep "Mode 06 section" etc. pointing at v6; if an entry listed `o_tiles` etc. it still holds. Run the page tests; fix only what the Dashboard legitimately renamed.

- [ ] **Step 6: Run node, page tests, full suite; expect pass.** Check `#v0 .tiles/.attn` CSS still applies (the section kept id `v0`). Run the CSP test (`tests/test_console_review_fixes.py:54`).

- [ ] **Step 7: Commit**

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js tests/test_console_page.py
git commit -m "feat: console Dashboard replaces Overview as the default view: scenario tabs (dropdown on a phone), up to 8 gauges, the full PID table below with the scenario's PIDs marked, the health strip inside General; the temporary #vp preview is removed"
```

---

### Task 4: Edit mode (pencil)

**Files:**
- Modify: `src/obd_reader/web/console.html` (`renderDashboard`, new `drawEditor`, CSS), `tests/js/page_logic_test.js`

**Interfaces:**
- Consumes: Task 2's `editAdd/editRemove/editMove/editForm/saveSaved/specsFor`; Task 3's `DB`, `curScenario`, `#d_edit`.
- Produces: `ED = { on: false, draft: [] }`; an editor block `#d_editor` inside the gauge panel body (above the gauges) with, per gauge, a row: name, buttons Up, Down, Form, Remove; below the rows a `<select id="d_add">` of PIDs in the run not already shown, an Add button, `Reset` and `Done`. Every action updates `ED.draft`, calls `saveSaved(sc.id, ED.draft, sc.gauges)` and redraws; `Reset` removes the saved key and reloads the defaults. While editing, `renderDashboard` draws `ED.draft`. Switching scenario ends edit mode.

- [ ] **Step 1: Write the failing node tests**

```js
// 13) Edit mode
{
  const store = {};
  const e = makeEnv(statesFor(30, base), 'v0', OVF, [], store); for (let k = 0; k < 32; k++) await e.tick();
  // press the pencil: editor appears, aria-pressed true, one row per gauge (8 in General), Add offers only PIDs in the run and not shown
  // press Remove on row 1: 7 gauges, store['shadetree.scen.general'] holds 7 specs
  // press Form on row 1: its form changed in the stored specs
  // press Up on row 2: order changed in the stored specs
  // choose a PID in d_add and press Add: 8 gauges again; with 8 gauges the Add button is disabled and d_add empty
  // press Reset: store key removed, 8 default gauges
  // remove all gauges: the panel body says 'No gauges. Add one or Reset.' and Add and Reset still work
  // press Done: editor gone, aria-pressed false; reload (new makeEnv with the same store) shows the saved set
  // switch scenario while editing: editor closes
}
```

Fill in each comment with real assertions using the harness idioms found in Task 3; each comment is one assertion group and all are required.

- [ ] **Step 2: Run node; expect FAIL.**

- [ ] **Step 3: Implement.** Keep the editor rebuild off the 400 ms poll path: `drawEditor()` runs on each edit action, on pencil toggle, and when the signature `Object.keys(chs).sort().join()` changes (store the last signature in `ED.sig`; compare in `renderDashboard`). Rows use `textContent` and `pidName(pid)`. Skeleton:

```js
  var ED = { on: false, draft: [], sig: '' };
  function edit(next) { var sc = curScenario(); ED.draft = next; saveSaved(sc.id, next, sc.gauges); drawEditor(); render(); }
  function drawEditor() {
    var box = $('d_editor') || (function () { var d = el('div', 'edbox'); d.id = 'd_editor'; DB.p.body.insertBefore(d, DB.g); return d; })(), sc = curScenario();
    box.textContent = ''; box.hidden = !ED.on; if (!ED.on) return;
    if (!ED.draft.length) box.appendChild(el('p', 'note', 'No gauges. Add one or Reset.'));
    ED.draft.forEach(function (g, i) {
      var row = el('div', 'edrow'), nm = el('span', '', pidName(g.pid) + ' (' + g.pid + ', ' + g.form + ')');
      row.appendChild(nm);
      [['Up', function () { edit(editMove(ED.draft, i, -1)); }], ['Down', function () { edit(editMove(ED.draft, i, 1)); }],
       ['Form', function () { edit(editForm(ED.draft, i)); }], ['Remove', function () { edit(editRemove(ED.draft, i)); }]]
        .forEach(function (b) { var x = el('button', 'qbtn', b[0]); x.setAttribute('type', 'button'); x.addEventListener('click', b[1]); row.appendChild(x); });
      box.appendChild(row);
    });
    var chs = (state && state.channels) || {}, shown = {};
    ED.draft.forEach(function (g) { shown[g.pid] = true; });
    var sel = el('select'), add = el('button', 'qbtn', 'Add'), full = ED.draft.length >= 8;
    sel.id = 'd_add'; add.id = 'd_addbtn'; add.setAttribute('type', 'button');
    Object.keys(chs).sort().filter(function (p) { return !shown[p] && HEXPID.test(p); }).forEach(function (p) { var o = el('option', '', pidName(p) + ' (' + p + ')'); o.value = p; sel.appendChild(o); });
    add.disabled = full || !sel.children.length;
    add.addEventListener('click', function () { if (sel.value) edit(editAdd(ED.draft, sel.value)); });
    var reset = el('button', 'qbtn', 'Reset'), done = el('button', 'qbtn', 'Done');
    reset.addEventListener('click', function () { edit(sc.gauges.slice()); });
    done.addEventListener('click', function () { ED.on = false; $('d_edit').setAttribute('aria-pressed', 'false'); drawEditor(); render(); });
    [sel, add, reset, done].forEach(function (c) { box.appendChild(c); });
  }
  $('d_edit').addEventListener('click', function () {
    ED.on = !ED.on; ED.draft = specsFor(curScenario()).slice(); ED.sig = '';
    $('d_edit').setAttribute('aria-pressed', ED.on ? 'true' : 'false');
    if (DB) drawEditor(); render();
  });
```

In `renderDashboard` use `var specs = ED.on ? ED.draft : specsFor(sc)`, call `drawEditor()` when `ED.on` and the channel signature changed, and in `setScenario` set `ED.on = false` and reset `aria-pressed` before drawing. When the draft is empty `gauges(DB.g, [])` must leave the panel empty (verify `keyed` handles `[]`; the test covers it). CSS: `.edbox { margin-bottom: 10px; }`, `.edrow { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }`, `.edrow span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }`; tokens only. `edit()` saves on every action, so there is no unsaved state to lose.

- [ ] **Step 4: Run node, page tests, full suite; expect pass. Commit.**

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js
git commit -m "feat: console Dashboard edit mode (pencil: add from the PIDs in the run, remove, reorder, change form, Reset), saved per scenario in the browser"
```

---

### Task 5: Reviewer carry-overs from stage 1 (contrast, ranges, test hardening)

**Files:**
- Modify: `src/obd_reader/web/console.html` (`GAUGE['0B']` line 941, `ledStrip` 953-960, Retro light `--amber`), `tests/test_console_page.py` (`TEXT_PAIRS`, colour regex in `test_colours_live_only_in_the_token_blocks`), `tests/js/page_logic_test.js`

- [ ] **Step 1: Failing tests first.**
  - `TEXT_PAIRS`: add the gauge text pairs (amber and bad on `--panel2`; `--g-ink` on `--g-face`) at 4.5:1 for every skin and theme. Run: expect Retro light amber on panel2 (4.47) to fail.
  - Widen the colour-literal regex to 3-8 digit hex and `rgb(`/`rgba(`/`hsl(`; expect any stray literal to fail, then tokenise it.
  - Node: `gaugeModel({pid: '0B', form: 'dial'})` for a reading of 180 kPa returns `hi >= 250` and a needle value of 180 (no clamp); `ledStrip` for a temperature in US units (`05` at 200 F, range -4..266 F) lights from the low end (the first lit cell is cell 0).
  - Node: the hook no-op branch (no `__shadetreeParts` defined) leaves the page running; `pidRows` with the same PID list twice keeps the row nodes (identity) across two renders.

- [ ] **Step 2: Fix.** `GAUGE['0B']`: `hi: 250`. `ledStrip` today lights from 0 (or the nearer end), which is wrong for temperatures in US units (zero F is not a meaningful origin). Rule: centre on 0 only for the trim PIDs `06-09` and `0E`; every other PID lights from `lo`. Implement as a `CENTRED = { '06': 1, '07': 1, '08': 1, '09': 1, '0E': 1 }` lookup passed through `gaugeModel` as `it.centre`, and `ledStrip(v, lo, hi, zones, n, centre)` using `base = centre ? 0 : lo`. Nudge Retro light `--amber` darker (try `#805300`) until the contrast test passes, and check the Retro light look in a screenshot (Neil's pass).

- [ ] **Step 3: Run node, page tests, full suite; expect pass. Commit.**

```bash
git add src/obd_reader/web/console.html tests/test_console_page.py tests/js/page_logic_test.js
git commit -m "fix: console gauge text contrast pairs tested (Retro light amber darkened), colour-literal check widened to 3-8 digit hex and rgb(), MAP gauge range to 250 kPa, LED bars light from the low end except the trims"
```

---

### Task 6: Docs

**Files:**
- Modify: `docs/design.md` §7b, `README.md` ("What works today" console row, CLI options), `CLAUDE.md` status line only if test counts are quoted

- [ ] **Step 1: Write the docs.** §7b: Dashboard (default view, scenarios, edit mode, saved per scenario in the browser), the `--scenarios FILE` format (copy the format and limits from Task 1 verbatim, with one example file), `GET /api/scenarios`, and that Overview became the General strip. README: one row for the Dashboard and one line for `--scenarios`. Update the test count in `CLAUDE.md` only if it quotes one that is now wrong (run the full suite for the number).
- [ ] **Step 2: Run the full suite one last time and the three CHECK commands; paste results into the commit notes for Neil.**
- [ ] **Step 3: Commit.**

```bash
git add docs/design.md README.md docs/superpowers/specs/2026-10-01-console-coherence-design.md docs/superpowers/plans/2026-10-01-console-stage2-dashboard-and-scenarios.md
git commit -m "docs: console Dashboard, scenarios and --scenarios FILE (design 7b, README); stage 2 plan; spec drops 'readiness' (the console has no readiness view)"
```

---

## Neil's screenshot pass (before "merge and push")

Agents cannot see a browser. After Task 6 the controller starts a loopback console (`--demo --http-port 8799`), takes desktop and 390 px phone screenshots of: Dashboard General in Plain and Retro (dark and light), Fuel trims, Cooling, edit mode open, a scenario with a PID not in the run, and the table with highlighted rows. Neil checks gauge title ellipsis, the phone dropdown, and the table's horizontal scroll inside its card.

## Deferred to stage 3 (not in this plan)

Hiding the Std and Samples columns on phones; the Retro cabinet (Analyzer) with the full PID table; Handheld Live default; the phone default view. Page-level `#vp`-style structural tests are replaced by the Dashboard tests above.

## Self-review

- **Spec coverage:** Dashboard default view with up to 8 gauges and the full table (Task 3); five built-in scenarios with the spec's PID sets (Task 2); tabs on desktop, dropdown on phone (Task 3); scenario PIDs highlighted in a full table (Task 3); pencil edit mode with add/remove/reorder/form/Reset saved per scenario (Task 4); `--scenarios FILE` server-validated with hex PIDs, 8 gauges, short names, bounded size, layered under in-page edits (Tasks 1-2); not-in-run dimming (Task 3 test 11); Overview strip into General, Guided test unchanged (Task 3); the stage 1 reviewer's notes: size budget (Task 2), hook additions (Task 2), `Object.create(null)`/strict hex PIDs (Tasks 1-2), non-finite rejection via `parse_constant` (Task 1), `ledStrip` low end (Task 5), `render()` else-branch to `v3` and own Dashboard branch (Task 3), contrast pairs and amber nudge (Task 5), `#vp` removal (Task 3), gauge tile width (Task 3), colour regex, `0B` range, hook no-op and row-identity tests (Task 5). The phone-column item is deferred to stage 3 and listed above.
- **Spec deviation to confirm with Neil:** the spec says "lo/hi" are not in scenario files, so the file format omits them (gauges use the built-in display ranges); a PID with no range shows as seven-segment.
- **Type consistency:** `{pid, form}` specs, `scenarioList`, `specsFor`, `saveSaved(id, specs, defaults)`, `editAdd/Remove/Move/Form` are named identically in Tasks 2-4; `SC`, `DB`, `ED`, `curScenario`, `setScenario`, `renderDashboard`, `drawTabs`, `drawEditor` are each defined once.
- **Known soft spots:** DOM test snippets in Tasks 3-4 name the contract but defer the click/query idiom to the harness (`makeEnv`, `flat`, stage 1's gauge tests); the implementer reads those first. Task 1 steps 5 and 7 likewise defer fixture and error-code idiom to the existing tests.
