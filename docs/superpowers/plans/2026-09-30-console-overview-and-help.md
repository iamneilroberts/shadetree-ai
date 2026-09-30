# Console Overview and Help Popups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new Overview home tab (status strip, five health tiles, "Needs attention" list) plus a "?" help popup on every statistic, backed by one shared help catalog; retire the Cockpit and Scope tabs and drop the extraneous "read-only" page text.

**Architecture:** `stat_help.py` holds plain-language entries keyed by PID and Mode 06 group, served read-only at `GET /api/help`. The page fetches it once, renders popups with `textContent` only, and computes tile state in the page from each entry's `watch` ranges on a 10 s median. Tiles and reading cards are updated in place (keyed) so a "?" button is never replaced between mouse-down and mouse-up.

**Tech Stack:** Python 3.11 stdlib HTTP server (`console.py`), one-file page `web/console.html`, pytest, Node fake-DOM test `tests/js/page_logic_test.js`.

**Spec:** `docs/superpowers/specs/2026-09-30-console-overview-and-help-design.md` (mock: `docs/mocks/overview.html`).

## Global Constraints

- The console adds no command, no POST route and no PID; `allowlist.py`, `transport.py`, `hub.py` are not touched. `/api/help` is GET only, behind the existing token, Host and Origin checks.
- The page keeps exactly one `<script>` block (the CSP pins its hash at serve time). No external URLs, no `<link>`, no `<script src>`.
- All catalog and adapter-derived text reaches the page through `textContent`, never `innerHTML`. The only `innerHTML` added is the sparkline SVG built from numbers.
- Help wording is tagged `["model_drafted", "unreviewed"]`; the popup shows "Wording drafted by the model, not yet reviewed." No model-specific limits are invented: `watch` holds general rules of thumb only.
- Public repo: no VIN, real snapshot or transcript in any test or fixture. Stage files by name; commit per task; do not merge or push until Neil says so.
- Match surrounding style: no new dependencies, comment density like the file being edited.

### Deviations from the spec (decided while planning)

- **Catalog coverage:** entries for the 8 default PIDs plus the first 16 of `EXTRA_PIDS` (24 entries, matching "about 25"). The console caps a run at 16 PIDs (`MAX_PIDS`), so later extras are rarely reached; any PID without an entry gets the generic popup.
- **Engine-off battery range:** the spec fixes `ok` 12.2-12.9 V; this plan sets its `out` range to 11.5-13.5 V.
- **Lamp and codes chips** join the shared status bar (above all tabs) rather than a strip only on Overview.
- **Keyed in-place updates** for Overview tiles, attention rows and reading cards (not in the spec): the page re-renders every 400 ms, and rebuilding a "?" button between mouse-down and mouse-up would drop the click.

## Review Focus

- A malformed `/api/help` reply (missing `pids`, `null` sections) must fall back to the generic popup, never throw. Pinned in Task 2.
- A reading the car does not report shows "not reported", never a normal color; a stopped run shows "not sampling". Pinned in Task 3.
- Engine off (rpm 0) with 12.4 V is normal; the same 12.4 V while running is "watch". Pinned in Task 3.
- A new run (new `run` id) must reset tile data even when its sequence numbers overtake the old run's. Pinned in Task 4 (replaces the old Scope test).
- The help panel must stay inside a 500 px wide viewport when its "?" is at the right edge. Pinned in Task 2.

## File Structure

- Create `src/obd_reader/stat_help.py`: `HELP` (PID -> entry) and `MODE06` (group -> entry).
- Modify `src/obd_reader/console.py`: import, one GET route, one 405 line.
- Modify `src/obd_reader/web/console.html`: popup, keyed helper, Overview tab, chips, then retire v1/v2 and trim text.
- Modify `tests/js/page_logic_test.js` (harness gains DOM methods, new tests, two old tests retargeted), `tests/test_console_page.py`, `tests/test_console.py`; create `tests/test_stat_help.py`.
- Modify `README.md`.

Run tests from the repo (or worktree) root with `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q`; Node test: `node tests/js/page_logic_test.js src/obd_reader/web/console.html`.

---

### Task 1: Help catalog and `/api/help`

**Files:**
- Create: `src/obd_reader/stat_help.py`, `tests/test_stat_help.py`
- Modify: `src/obd_reader/console.py` (import; `do_GET` near line 167; `do_POST` near line 183), `tests/test_console.py`

**Interfaces:**
- Produces: `HELP: dict[str, dict]` keyed by two-hex-digit PID; `MODE06: dict[str, dict]` keyed by `o2_sensor|o2_heater|catalyst|egr_vvt|evap|misfire|fuel_system|other`. Entry fields: `title: str`, `measures: str`, `use: list[str]` (2-3), `typical: str`, `status: ["model_drafted","unreviewed"]`, optional `watch` and `watch_engine_off` = `{"ok": [lo, hi], "out": [lo, hi]}` where `null` means unbounded. Inside `ok` is normal; outside `ok` but inside `out` is watch; outside `out` is out of range.
- Produces: `GET /api/help` -> `200 {"pids": HELP, "mode06": MODE06}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_stat_help.py`:

```python
from obd_reader.hub import DEFAULT_PIDS, EXTRA_PIDS
from obd_reader.pids import PIDS
from obd_reader.stat_help import HELP, MODE06

FIELDS = {"title", "measures", "use", "typical", "status"}
GROUPS = {"o2_sensor", "o2_heater", "catalyst", "egr_vvt", "evap", "misfire", "fuel_system", "other"}


def _complete(key, e):
    assert FIELDS <= set(e), key
    assert isinstance(e["use"], list) and 2 <= len(e["use"]) <= 3, key
    assert all(isinstance(x, str) and x for x in [e["title"], e["measures"], e["typical"], *e["use"]]), key
    assert e["status"] == ["model_drafted", "unreviewed"], key


def test_default_and_leading_extra_pids_have_complete_entries():
    for pid in DEFAULT_PIDS + EXTRA_PIDS[:16]:
        _complete(pid, HELP[pid])


def test_every_catalog_key_is_a_decodable_pid():
    assert set(HELP) <= set(PIDS)


def test_mode06_groups_are_complete():
    assert set(MODE06) == GROUPS
    for g, e in MODE06.items():
        _complete(g, e)


def test_watch_ranges_are_well_formed_and_nested():
    seen = 0
    for pid, e in HELP.items():
        for key in ("watch", "watch_engine_off"):
            w = e.get(key)
            if w is None:
                continue
            seen += 1
            ok, out = w["ok"], w["out"]
            assert len(ok) == len(out) == 2, (pid, key)
            for r in (ok, out):
                assert r[0] is None or r[1] is None or r[0] <= r[1], (pid, key)
            assert out[0] is None or (ok[0] is not None and out[0] <= ok[0]), (pid, key)
            assert out[1] is None or (ok[1] is not None and ok[1] <= out[1]), (pid, key)
    assert seen >= 7  # four trims, coolant, battery (running and engine off)
    assert "watch_engine_off" in HELP["42"] and all("watch" in HELP[p] for p in ("05", "06", "07", "08", "09", "42"))
    assert "watch" not in HELP["04"] and "watch" not in HELP["0B"]
```

Append to `tests/test_console.py`:

```python
def test_help_needs_the_token_and_is_get_only(srv):
    server, _, _ = srv
    assert call(server, "GET", "/api/help", token=None)[0] == 401
    assert call(server, "GET", "/api/help", host="evil.example")[0] == 403
    status, body = call(server, "GET", "/api/help")
    assert status == 200 and "06" in body["pids"] and "evap" in body["mode06"]
    assert call(server, "POST", "/api/help", {})[0] == 405


def test_help_carries_no_vin_shaped_text(srv):
    import re
    text = json.dumps(call(srv[0], "GET", "/api/help")[1])
    assert not re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", text)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_stat_help.py tests/test_console.py -q -k "help or stat"`
Expected: FAIL (`ModuleNotFoundError: obd_reader.stat_help`, and 404 from `/api/help`).

- [ ] **Step 3: Write `src/obd_reader/stat_help.py`**

```python
"""Plain-language help for each reading the console shows: what it measures, how to use it, typical values.
Wording is ours (model-drafted, unreviewed) and rules of thumb only; `watch` sets the tile color and never
claims a limit for one particular car. A `null` bound is open-ended."""

_STATUS = ["model_drafted", "unreviewed"]


def _e(title, measures, use, typical, watch=None, watch_engine_off=None):
    d = {"title": title, "measures": measures, "use": use, "typical": typical, "status": list(_STATUS)}
    if watch is not None:
        d["watch"] = watch
    if watch_engine_off is not None:
        d["watch_engine_off"] = watch_engine_off
    return d


_TRIM = {"ok": [-10, 10], "out": [-20, 20]}
_TRIM_TYPICAL = "Within about +/-10 %. Worry if steady beyond +/-10 %; beyond +/-20 % is out of range here."
_SHORT_USE = ["Near 0 on both banks means the mix is on target.",
              "Positive on both banks at idle: look for a vacuum leak, weak fuel pressure or a dirty airflow sensor.",
              "Numbers that differ between banks point at one side, such as an injector or an exhaust leak."]
_LONG_USE = ["Long-term trim is the better clue for a steady fault, because it remembers.",
             "A value that keeps climbing toward +15 % or more means the computer is running out of correction room.",
             "After a repair, expect it to drift back toward 0 over some driving."]


def _short(bank):
    return _e(f"Short-term fuel trim, bank {bank}",
              f"The fuel the computer adds (+) or removes (-) right now to hold the air-fuel mix on target, for engine bank {bank}. "
              "A V engine has two banks; an inline engine has only bank 1.",
              _SHORT_USE, _TRIM_TYPICAL, _TRIM)


def _long(bank):
    return _e(f"Long-term fuel trim, bank {bank}",
              f"The learned, slower fuel correction for bank {bank}; it absorbs what the short-term trim keeps asking for.",
              _LONG_USE, _TRIM_TYPICAL, _TRIM)


_O2_LAMBDA_USE = ["It should hover around 1.00 and swing slightly as the computer adjusts.",
                  "Stuck lean or rich while the trims try to correct it points to the sensor or a real mixture fault.",
                  "Compare it with the commanded equivalence ratio; they should track each other."]
_O2_DOWN_USE = ["A healthy converter keeps this fairly steady, roughly 0.4-0.8 V.",
                "If it swings as fast as the upstream sensor, the converter may be worn out.",
                "Stuck near 0 V or 1 V suggests a sensor or wiring fault."]

HELP = {
    "0C": _e("Engine speed", "How fast the crankshaft turns, in revolutions per minute.",
             ["A warm idle should sit steady, often 600-900 rpm.",
              "Hunting up and down at idle points to an air leak, a sticking idle valve or a fuel problem.",
              "A rough idle with normal trims is more likely ignition or mechanical."],
             "600-900 rpm at warm idle (varies by car)."),
    "05": _e("Coolant temperature", "Engine coolant temperature near the thermostat.",
             ["It should climb and then hold steady once the engine is warm.",
              "Stuck cold after ten minutes of driving suggests a stuck-open thermostat or a bad sensor.",
              "A sensor that reads colder than the engine really is makes the computer run rich."],
             "85-100 C once warm. Worry above 105 C; above 112 C is out of range here.",
             {"ok": [None, 105], "out": [None, 112]}),
    "06": _short(1), "07": _long(1), "08": _short(2), "09": _long(2),
    "0B": _e("Manifold pressure (MAP)",
             "Air pressure inside the intake manifold. Low means strong vacuum; near outside pressure means the throttle is wide open or the engine is off.",
             ["Warm idle shows a steady low value, often 25-40 kPa at sea level.",
              "Key on, engine off, it should read close to the barometric pressure reading.",
              "A high or unsteady reading at idle points to a vacuum leak or a valve problem."],
             "25-40 kPa at warm idle; near outside pressure (about 100 kPa) with the engine off."),
    "42": _e("Battery voltage", "Voltage at the engine computer, a stand-in for battery and charging-system health.",
             ["Engine off, about 12.4-12.7 V is a healthy battery.",
              "Engine running, 13.5-14.8 V means the alternator is charging.",
              "Running below about 13 V points to the alternator, its belt or a wiring drop."],
             "13.5-14.8 V running; 12.4-12.7 V engine off.",
             {"ok": [13.2, 14.8], "out": [11.5, 15.5]}, {"ok": [12.2, 12.9], "out": [11.5, 13.5]}),
    "04": _e("Engine load", "How hard the engine is working, as a percentage of the most air it could take in at that speed.",
             ["Idle is usually 15-30 % and rises with throttle.",
              "High load at idle hints at an air leak or a dragging accessory.",
              "Compare with throttle position: load should follow the pedal."],
             "15-30 % at warm idle."),
    "11": _e("Throttle position", "How far the throttle plate is open, from closed to wide open.",
             ["Idle often reads 10-20 % on drive-by-wire cars, not 0.",
              "It should rise smoothly as you press the pedal, with no jumps or dropouts."],
             "About 10-20 % at idle; wide open usually 70-100 %."),
    "0D": _e("Vehicle speed", "Road speed the computer is using, in km/h (multiply by 0.62 for mph).",
             ["Compare it with the speedometer; a big difference points to a wrong tire size or a speedometer error.",
              "It should read 0 when stopped."],
             "Matches the speedometer within a few percent."),
    "0E": _e("Timing advance", "How many degrees before top dead center the spark fires.",
             ["It rises with rpm and falls under load.",
              "A sudden drop while accelerating can mean the computer is pulling timing because of knock."],
             "Roughly 5-20 degrees at warm idle."),
    "43": _e("Absolute load", "Air per intake stroke compared with a fixed reference, so it reads the same at any altitude.",
             ["Idle is usually 10-30 %; wide open reaches 80 % or more on many engines.",
              "Use it with engine load to spot a sensor that disagrees."],
             "10-30 % at warm idle."),
    "44": _e("Commanded equivalence ratio",
             "The air-fuel mix the computer is asking for, as lambda: 1.00 is the chemically ideal mix, below 1 is rich, above 1 is lean.",
             ["About 1.00 when the engine is warm and running in closed loop.",
              "Below 1 when cold or under hard load is normal enrichment.",
              "Well above 1 while coasting is normal: fuel is cut off."],
             "About 1.00 at warm idle."),
    "0F": _e("Intake air temperature", "Temperature of the air going into the engine.",
             ["It should be near outside temperature when cold and somewhat above it when warm.",
              "A reading far above outside temperature on a cold engine points to a bad sensor.",
              "Hot intake air lowers power and can raise knock."],
             "Outside temperature up to about 20 C above it when warm."),
    "5C": _e("Oil temperature", "Engine oil temperature.",
             ["It lags coolant and keeps rising after coolant levels off.",
              "Sustained readings above about 130 C are hard on the oil."],
             "90-110 C when fully warm."),
    "46": _e("Ambient air temperature", "Outside air temperature as measured by the car.",
             ["Use it to sanity-check intake air temperature on a cold start.",
              "It can read high after the car sits in sun or in traffic."],
             "Matches the outside temperature."),
    "33": _e("Barometric pressure", "Outside air pressure as measured when the key goes on.",
             ["About 101 kPa at sea level, falling about 1 kPa per 100 m of altitude.",
              "With the engine off, manifold pressure should read about the same."],
             "About 101 kPa at sea level, lower at altitude."),
    "2F": _e("Fuel level", "Fuel tank level as a percentage.",
             ["Compare with the dash gauge; a large mismatch points to the sender or the gauge.",
              "It can jump around a little when the tank sloshes."],
             "Matches the dash gauge."),
    "24": _e("Upstream O2 sensor, bank 1 (lambda)",
             "What the wide-range oxygen sensor before the catalyst reads, as lambda: 1.00 is the ideal mix, below 1 rich, above 1 lean.",
             _O2_LAMBDA_USE, "Hovers near 1.00 at warm idle."),
    "28": _e("Upstream O2 sensor, bank 2 (lambda)",
             "What the wide-range oxygen sensor before the catalyst on bank 2 reads, as lambda: 1.00 is the ideal mix, below 1 rich, above 1 lean.",
             _O2_LAMBDA_USE, "Hovers near 1.00 at warm idle."),
    "15": _e("Downstream O2 sensor, bank 1 (voltage)", "Voltage of the oxygen sensor after the catalytic converter on bank 1.",
             _O2_DOWN_USE, "Steady, about 0.4-0.8 V when warm."),
    "19": _e("Downstream O2 sensor, bank 2 (voltage)", "Voltage of the oxygen sensor after the catalytic converter on bank 2.",
             _O2_DOWN_USE, "Steady, about 0.4-0.8 V when warm."),
    "3C": _e("Catalyst temperature, bank 1 sensor 1", "Temperature of the catalytic converter, as measured or estimated by the computer.",
             ["It should climb after a cold start and then hold, often 300-800 C.",
              "A converter that never warms up is not doing its job.",
              "Very high readings can mean a misfire is dumping fuel into the exhaust."],
             "300-800 C once warm."),
}

MODE06 = {
    "o2_sensor": _e("Oxygen sensor monitor", "Tests how quickly and how far the oxygen sensors switch.",
                    ["A result near its limit means the sensor is getting slow or weak.",
                     "Compare each result with its own minimum and maximum, not with other tests."],
                    "Within its limits."),
    "o2_heater": _e("Oxygen sensor heater monitor", "Checks the electrical heater that brings the sensor up to working temperature.",
                    ["An out-of-limit result usually means a failed heater or its wiring.",
                     "A slow warm-up shows up as a long delay before the engine enters closed loop."],
                    "Within its limits."),
    "catalyst": _e("Catalyst monitor", "Estimates how well the catalytic converter stores oxygen.",
                   ["A result close to its limit means the converter is wearing out.",
                    "Fix misfires and mixture faults first; they damage converters."],
                   "Within its limits."),
    "egr_vvt": _e("EGR and variable valve timing monitor", "Checks exhaust-gas recirculation flow and how well the cam phasers follow commands.",
                  ["A result near its limit points at a clogged EGR path or a sluggish phaser.",
                   "Oil level and condition matter for phasers: check them first."],
                  "Within its limits."),
    "evap": _e("EVAP system monitor", "Tests the fuel vapor system for leaks and for purge flow.",
               ["A loose or bad fuel cap is the most common cause of a failed leak test.",
                "These tests often run only after the car has sat overnight, so a missing result is normal."],
               "Within its limits."),
    "misfire": _e("Misfire monitor", "Counts misfires per cylinder over a longer window than the live misfire check.",
                  ["A count above zero on one cylinder points at that cylinder's spark, injector or compression.",
                   "Counts on every cylinder at once point to fuel or air supply."],
                  "Zero or near it, within its limit."),
    "fuel_system": _e("Fuel system monitor", "Checks that the fuel trims stay within the range the computer can correct.",
                      ["A result near its limit matches trims that are pinned high or low.",
                       "Read it together with long-term trim."],
                      "Within its limits."),
    "other": _e("On-board test", "A test the computer runs on itself; the monitor ID says which one.",
                ["Compare the value with its own minimum and maximum.",
                 "The car maker's service information says exactly what a manufacturer-specific test checks."],
                "Within its limits."),
}
```

- [ ] **Step 4: Wire the route in `src/obd_reader/console.py`**

Add after the `from obd_reader.simulator import SimPort` import line:

```python
from obd_reader.stat_help import HELP, MODE06
```

In `do_GET`, change `if path not in ("/", "/api/state"):` to `if path not in ("/", "/api/state", "/api/help"):` and insert, directly before the `try:` that parses `after`:

```python
                if path == "/api/help":
                    return self._json(200, {"pids": HELP, "mode06": MODE06})
```

In `do_POST`, change `if path in ("/", "/api/state"):` to `if path in ("/", "/api/state", "/api/help"):`.

- [ ] **Step 5: Run, expect PASS**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_stat_help.py tests/test_console.py -q`
Expected: all pass (including the existing console tests).

- [ ] **Step 6: Commit**

```bash
git add src/obd_reader/stat_help.py src/obd_reader/console.py tests/test_stat_help.py tests/test_console.py
git commit -m "feat: help catalog for each reading, served read-only at /api/help"
```

---

### Task 2: Popup component, keyed updates, help on Readings and Mode 06

**Files:**
- Modify: `tests/js/page_logic_test.js` (harness, new test block), `src/obd_reader/web/console.html` (CSS, `<div id="helpPanel">`, JS)

**Interfaces:**
- Consumes: `GET /api/help` (Task 1).
- Produces (page-internal, used by Task 3): `HELP`, `qbtn(key)`, `keyed(box, items, make, update)`, `chFor(pid)`, `latest(pid)`, `series(pid)`, `unitOf(pid)`, `winMedian(pid)`, `watchFor(pid)`, `judge(v, watch)` returning `'none'|'neutral'|'ok'|'watch'|'out'`. Help keys: a PID string such as `"06"`, or `"m06:<group>"`. Harness (used by Task 3/4 tests): `makeEnv(states, viewId, help)` returns `docHandlers`; helpers `walk`, `flat`, `findQ`.

- [ ] **Step 1: Upgrade the test harness.** In `tests/js/page_logic_test.js`, replace the whole `function makeEnv(states, viewId = 'v1') { ... }` (lines 6-37) with:

```js
function makeNode(id, handlers) {
  const n = {
    id, style: {}, className: '', innerHTML: '', hidden: false, dataset: {}, disabled: false, type: '',
    clientWidth: 0, clientHeight: 0, offsetWidth: 0, offsetHeight: 0, children: [], attrs: {}, _t: '',
    classList: { toggle() {} },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    appendChild(c) { this.children = this.children.filter(x => x !== c); this.children.push(c); return c; },
    removeChild(c) { this.children = this.children.filter(x => x !== c); return c; },
    contains(t) { return t === this || this.children.some(c => c.contains(t)); },
    closest(sel) { return sel[0] === '.' && this.className.split(' ').includes(sel.slice(1)) ? this : null; },
    getBoundingClientRect() { return { left: 0, top: 0, bottom: 0, right: 0 }; },
    addEventListener(t, fn) { handlers[id + ':' + t] = fn; }, querySelector() { return null; }
  };
  Object.defineProperty(n, 'textContent', { get() { return this._t; }, set(v) { this._t = v; this.children = []; } });
  return n;
}

function makeEnv(states, viewId = 'v1', help = null) {
  const els = {}, handlers = {}, docHandlers = {}, posts = [];
  function el(id) { return els[id] || (els[id] = makeNode(id, handlers)); }
  let timer = null, i = 0, now = 0;
  const sandbox = {
    console, URLSearchParams, Promise, Math, Object, Array, Number, String, JSON, Date, parseInt, isFinite,
    document: { getElementById: el, querySelectorAll: () => [], querySelector: () => ({ id: viewId }),
                createElement: () => makeNode('new', handlers), addEventListener(t, fn) { docHandlers[t] = fn; } },
    window: { addEventListener() {}, devicePixelRatio: 1, innerWidth: 500, innerHeight: 800 },
    location: { search: '?t=abc', hash: '' }, history: { replaceState() {} },
    performance: { now: () => now },
    setInterval: (fn) => { timer = fn; }, encodeURIComponent,
    fetch: (url, opts) => {
      if (opts && opts.method === 'POST') { posts.push({ url, body: JSON.parse(opts.body) }); return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, path: '/x/runs/a-run.json' }) }); }
      if (/\/api\/help/.test(url)) return Promise.resolve(help ? { ok: true, json: () => Promise.resolve(help) } : { ok: false, json: () => Promise.resolve({}) });
      const st = states[Math.min(i++, states.length - 1)];
      return Promise.resolve({ ok: true, json: () => Promise.resolve(st) });
    }
  };
  vm.runInNewContext(js, sandbox);
  return {
    el, handlers, docHandlers, posts, sandbox,
    timer() { timer(); },
    async tick() { timer(); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r)); }
  };
}

function walk(n, f) { f(n); (n.children || []).forEach(c => walk(c, f)); }
function flat(n) { let s = n.textContent || ''; (n.children || []).forEach(c => { s += ' ' + flat(c); }); return s; }
function findQ(root, key) { let r = null; walk(root, n => { if (n.className === 'q' && n.getAttribute('data-help') === key) r = n; }); return r; }
```

Before changing the page, confirm the harness change broke nothing: run `node tests/js/page_logic_test.js src/obd_reader/web/console.html`. Expected: `page logic OK`. (The old line 28 body, `const st = states[Math.min(i++, states.length - 1)]`, is preserved above.)

- [ ] **Step 2: Write the failing popup test.** In `tests/js/page_logic_test.js`, insert this block immediately before `console.log('page logic OK');`:

```js
  // 5) help popups: catalog text is shown as text, one panel at a time, closes on Escape/outside click, stays on screen
  const HELPFIX = { pids: { '04': { title: 'Engine load', measures: '<img src=x onerror=1>', use: ['first tip', 'second tip'],
                                     typical: 'about 15-30 % at idle', status: ['model_drafted', 'unreviewed'] } },
                    mode06: { evap: { title: 'EVAP leak test', measures: 'Checks the fuel vapor system.', use: ['a', 'b'], typical: 'pass',
                                      status: ['model_drafted', 'unreviewed'] } } };
  const m06 = { read: true, note: null, mids: ['3A'], results: [{ mid: '3A', tid: '01', uasid: '10', value: 1, minimum: 0, maximum: 5, within_limits: true }] };
  const extraStates = statesFor(4, () => Object.assign(idle(), { '04': 28, '99': 7 })).map(st => Object.assign(st, { mode06: m06 }));
  const hp = makeEnv(extraStates, 'v6', HELPFIX);
  for (let k = 0; k < 5; k++) await hp.tick();
  const panel = hp.el('helpPanel');
  const q04 = findQ(hp.el('x_grid'), '04');
  assert(q04, 'every extra reading card has a ? button');
  hp.docHandlers.click({ target: q04 });
  assert.strictEqual(panel.className, 'open');
  assert(flat(panel).includes('<img src=x onerror=1>') && panel.innerHTML === '', 'catalog text is shown as text');
  assert(/first tip/.test(flat(panel)) && /now 28/.test(flat(panel)) && /not yet reviewed/.test(flat(panel)), 'tips, live value, unreviewed tag');
  hp.docHandlers.click({ target: findQ(hp.el('x_grid'), '04') });
  assert.strictEqual(panel.className, '', 'the same ? again closes it');
  hp.docHandlers.click({ target: q04 }); hp.docHandlers.keydown({ key: 'Escape' });
  assert.strictEqual(panel.className, '', 'Escape closes');
  hp.docHandlers.click({ target: q04 }); hp.docHandlers.click({ target: {} });
  assert.strictEqual(panel.className, '', 'a click outside closes');
  hp.docHandlers.click({ target: findQ(hp.el('x_grid'), '99') });
  assert(/No bundled help/.test(flat(panel)), 'a reading with no entry gets the generic popup');
  hp.docHandlers.click({ target: findQ(hp.el('m6'), 'm06:evap') });
  assert(/EVAP leak test/.test(flat(panel)) && panel.className === 'open', 'Mode 06 lines have help, and opening another replaces the first');
  assert.strictEqual(hp.el('x_grid').children.filter(c => c.className === 'xt').length, 3, 'cards (0x04, 0x10, 0x99) are updated in place, not duplicated');
  hp.docHandlers.keydown({ key: 'Escape' });
  panel.offsetWidth = 360; q04.getBoundingClientRect = () => ({ left: 480, top: 100, bottom: 120, right: 500 });
  hp.docHandlers.click({ target: q04 });
  const left = parseFloat(panel.style.left);
  assert(left >= 12 && left <= 500 - 360 - 12, 'panel stays inside a 500 px viewport, got left=' + left);
  const bad = makeEnv(extraStates, 'v6', { pids: null, mode06: null });
  for (let k = 0; k < 5; k++) await bad.tick();
  bad.docHandlers.click({ target: findQ(bad.el('x_grid'), '04') });
  assert(/No bundled help/.test(flat(bad.el('helpPanel'))), 'a malformed help reply falls back to the generic popup, no crash');
```

- [ ] **Step 3: Run, expect FAIL**

Run: `node tests/js/page_logic_test.js src/obd_reader/web/console.html`
Expected: `FAIL every extra reading card has a ? button`.

- [ ] **Step 4: Implement in `src/obd_reader/web/console.html`.**

(a) CSS, add just before the closing `</style>` tag:

```css
  .q { width: 22px; height: 22px; border-radius: 50%; border: 1px solid var(--line); background: var(--panel2); color: var(--muted);
       font: 700 12px/1 var(--cond); cursor: pointer; padding: 0; }
  .q:hover, .q:focus-visible { color: var(--ink); border-color: var(--muted); }
  #v6 .xt { position: relative; }
  #v6 .xt .q { position: absolute; top: 6px; right: 6px; }
  #v6 .xt .n { padding-right: 26px; }
  #v6 .m6h .q { margin-left: 8px; vertical-align: middle; }
  #helpPanel { position: fixed; z-index: 50; width: min(360px, calc(100vw - 24px)); background: var(--panel2); border: 1px solid var(--muted);
               border-radius: 8px; padding: 12px 14px; box-shadow: 0 10px 30px rgba(0,0,0,.55); display: none; font-size: 12.5px; }
  #helpPanel.open { display: block; }
  #helpPanel h4 { margin: 0 0 6px; font: 700 14px var(--cond); letter-spacing: .06em; text-transform: uppercase; }
  #helpPanel h5 { margin: 10px 0 3px; font: 700 11px var(--cond); letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
  #helpPanel p { margin: 0; } #helpPanel ul { margin: 0; padding-left: 18px; }
  #helpPanel .live { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--line); }
  #helpPanel .draft { margin-top: 8px; color: var(--muted); font-size: 11px; }
```

(b) Add `<div id="helpPanel" role="dialog" aria-live="polite"></div>` on the line directly before `<script>`.

(c) Add a `midGroup` function directly after the existing `midName` function:

```js
  function midGroup(m) {
    var n = parseInt(m, 16);
    if (n >= 0x01 && n <= 0x08) return 'o2_sensor';
    if (n >= 0x41 && n <= 0x48) return 'o2_heater';
    if (n === 0x21 || n === 0x22) return 'catalyst';
    if (n === 0x31 || n === 0x35 || n === 0x36) return 'egr_vvt';
    if (n >= 0x39 && n <= 0x3D) return 'evap';
    if (n === 0x81 || n === 0x82) return 'fuel_system';
    if (n >= 0xA1 && n <= 0xAD) return 'misfire';
    return 'other';
  }
```

(d) Add this block directly after the `el` helper (`function el(tag, cls, text) {...}`):

```js
  /* ---------- reading lookups, tile state and help popups ---------- */
  var HELP = { pids: {}, mode06: {} }, helpKey = null;
  function chFor(pid) { for (var i = 0; i < CH.length; i++) if (CH[i].pid === pid) return CH[i]; return null; }
  function latest(pid) { var c = chFor(pid); if (c) return last[c.id]; return xs[pid] ? xs[pid].v : null; }
  function series(pid) { var c = chFor(pid); return c ? buf[c.id] : (xs[pid] && xs[pid].hist) || []; }
  function unitOf(pid) { var c = chFor(pid), u = c ? c.unit : xs[pid] && xs[pid].unit; return u === 'C' ? '°C' : (u || ''); }
  function pidName(pid) { var c = chFor(pid); return c ? c.name : xs[pid] ? xs[pid].name.replace(/_/g, ' ') : pid; }
  function fmtAny(v) { return Math.abs(v) >= 100 || v % 1 === 0 ? String(Math.round(v * 10) / 10) : v.toFixed(1); }
  function winMedian(pid) {   // median of the last 10 s, so a brief spike does not flip a tile
    var s = series(pid).filter(function (p) { return p.t >= tNow - 10; });
    if (!s.length) return null;
    var v = s.map(function (p) { return p.v; }).sort(function (a, b) { return a - b; }), m = v.length >> 1;
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  }
  function watchFor(pid) {
    var e = HELP.pids[pid]; if (!e || typeof e !== 'object') return null;
    var rpm = winMedian('0C');
    return pid === '42' && rpm !== null && rpm < 300 && e.watch_engine_off ? e.watch_engine_off : (e.watch || null);
  }
  function judge(v, w) {
    if (v === null || v === undefined) return 'none';
    if (!w) return 'neutral';
    function inside(r) { return (r[0] === null || v >= r[0]) && (r[1] === null || v <= r[1]); }
    return inside(w.ok) ? 'ok' : inside(w.out) ? 'watch' : 'out';
  }
  // update the nodes in box by key instead of rebuilding them: a ? button replaced between mouse-down and mouse-up loses the click
  function keyed(box, items, make, update) {
    var nodes = box._nodes = box._nodes || {}, order = items.map(function (i) { return i.key; }), sig = order.join('|');
    Object.keys(nodes).forEach(function (k) { if (order.indexOf(k) < 0) { box.removeChild(nodes[k].root); delete nodes[k]; box._sig = null; } });
    items.forEach(function (it) { if (!nodes[it.key]) { nodes[it.key] = make(it); box._sig = null; } update(nodes[it.key], it); });
    if (box._sig !== sig) { order.forEach(function (k) { box.appendChild(nodes[k].root); }); box._sig = sig; }
  }
  function qbtn(key) { var b = el('button', 'q', '?'); b.type = 'button'; b.setAttribute('data-help', key); b.setAttribute('aria-label', 'Help'); return b; }
  function helpEntry(key) {
    var m = key.indexOf('m06:') === 0, e = m ? HELP.mode06[key.slice(4)] : HELP.pids[key];
    if (e && typeof e === 'object') return e;
    return { title: m ? 'On-board test' : pidName(key), measures: 'No bundled help for this reading yet.', use: [], typical: '', status: ['model_drafted', 'unreviewed'] };
  }
  function liveLine(key) {
    if (key.indexOf('m06:') === 0) return '';
    var v = latest(key); if (v === null || v === undefined) return 'not reported by this car';
    var u = unitOf(key), s = judge(winMedian(key), watchFor(key));
    return 'now ' + fmtAny(v) + (u ? ' ' + u : '') + (s === 'ok' ? ': normal' : s === 'watch' ? ': watch' : s === 'out' ? ': out of range' : '');
  }
  function closeHelp() { $('helpPanel').className = ''; helpKey = null; }
  function openHelp(btn, key) {
    var h = helpEntry(key), box = $('helpPanel');
    box.textContent = '';
    box.appendChild(el('h4', '', String(h.title)));
    box.appendChild(el('h5', '', 'What it measures')); box.appendChild(el('p', '', String(h.measures)));
    if (Array.isArray(h.use) && h.use.length) {
      box.appendChild(el('h5', '', 'How to use it'));
      var ul = el('ul'); h.use.forEach(function (x) { ul.appendChild(el('li', '', String(x))); }); box.appendChild(ul);
    }
    if (h.typical) { box.appendChild(el('h5', '', 'Typical / worry if')); box.appendChild(el('p', '', String(h.typical))); }
    var lv = liveLine(key); if (lv) box.appendChild(el('div', 'live', lv));
    if (Array.isArray(h.status) && h.status.indexOf('unreviewed') >= 0) box.appendChild(el('div', 'draft', 'Wording drafted by the model, not yet reviewed.'));
    box.className = 'open'; helpKey = key;
    var r = btn.getBoundingClientRect(), w = box.offsetWidth || 360, hgt = box.offsetHeight || 0, below = r.bottom + 8;
    box.style.left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12)) + 'px';
    box.style.top = (below + hgt > window.innerHeight ? Math.max(12, r.top - hgt - 8) : below) + 'px';
  }
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('.q') : null;
    if (b) { var k = b.getAttribute('data-help'); if (helpKey === k) closeHelp(); else openHelp(b, k); return; }
    if (helpKey !== null && !$('helpPanel').contains(e.target)) closeHelp();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeHelp(); });
  function loadHelp() {
    fetch(api('/api/help'))
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (j) { if (j && j.pids && typeof j.pids === 'object' && j.mode06 && typeof j.mode06 === 'object') { HELP = j; render(); } })
      .catch(function () {});
  }
```

(e) In `ingest`, replace the extras loop (from `Object.keys(st.channels).forEach(function (pid) {     // readings outside the fixed channels` through its closing `});`) with:

```js
    Object.keys(st.channels).forEach(function (pid) {     // readings outside the fixed channels: keep latest, min, max and the last minute
      if (PIDS.indexOf(pid) >= 0) return;
      var ch = st.channels[pid], x = xs[pid] = xs[pid] || { pid: pid, v: null, min: null, max: null, hist: [] };
      x.name = ch.name; x.unit = ch.unit; x.labels = ch.labels;
      ch.samples.forEach(function (sm) {
        if (sm[0] <= lastSeq) return;
        x.v = sm[2]; x.min = x.min === null ? sm[2] : Math.min(x.min, sm[2]); x.max = x.max === null ? sm[2] : Math.max(x.max, sm[2]);
        x.hist.push({ t: sm[1], v: sm[2] });
      });
      while (x.hist.length && x.hist[0].t < tNow - SPAN - 2) x.hist.shift();
    });
```

(f) Replace the head of `renderReadings` (from `function renderReadings() {` through the closing `});` of the `ids.forEach`, i.e. everything up to but not including the line `$('x_count').textContent = ...`) with:

```js
  function makeX(it) {
    var root = el('div', 'xt'), n = el('div', 'n'), v = el('div', 'v'), r = el('div', 'r');
    root.appendChild(qbtn(it.key)); root.appendChild(n); root.appendChild(v); root.appendChild(r);
    return { root: root, n: n, v: v, r: r };
  }
  function updX(nd, it) {
    var x = it.x, lab = x.labels && x.v !== null ? x.labels[String(Math.round(x.v))] : null;
    nd.n.textContent = x.name.replace(/_/g, ' ') + ' · ' + it.key;
    nd.v.textContent = lab ? lab : (x.v === null ? '—' : (Math.abs(x.v) >= 100 || x.v % 1 === 0 ? String(Math.round(x.v * 10) / 10) : x.v.toFixed(2)));
    if (!lab && x.unit) nd.v.appendChild(el('small', '', x.unit === 'C' ? '°C' : x.unit));
    nd.r.textContent = !x.labels && x.min !== null ? 'min ' + Math.round(x.min * 100) / 100 + ' · max ' + Math.round(x.max * 100) / 100 : '';
  }
  function renderReadings() {
    var st = state || {}, ids = Object.keys(xs).sort();
    keyed($('x_grid'), ids.map(function (p) { return { key: p, x: xs[p] }; }), makeX, updX);
```

Then inside the Mode 06 part of the same function: directly after the line `var m = st.mode06 || { read: false }, box = $('m6'), res = m.results || [];` replace the following `box.textContent = '';` with:

```js
    var msig = JSON.stringify(m); if (box._msig === msig) return; box._msig = msig;   // results do not change after the read; rebuilding would drop clicks
    box.textContent = '';
```

and change the Mode 06 header line to:

```js
      var h = el('div', 'm6h', midName(mid) + ' '); h.appendChild(el('span', '', 'MID ' + mid)); h.appendChild(qbtn('m06:' + midGroup(mid))); box.appendChild(h);
```

(g) At the very end of the script, change the last two lines `  poll();\n})();` to `  poll();\n  loadHelp();\n})();`.

- [ ] **Step 5: Run the Node test, then the whole suite**

Run: `node tests/js/page_logic_test.js src/obd_reader/web/console.html` -> expected `page logic OK`.
Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q` -> expected all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/js/page_logic_test.js src/obd_reader/web/console.html
git commit -m "feat: help popup on extra readings and Mode 06 tests, cards updated in place"
```

---

### Task 3: Overview tab, lamp and codes chips

**Files:**
- Modify: `src/obd_reader/web/console.html`, `tests/js/page_logic_test.js`, `tests/test_console_page.py`

**Interfaces:**
- Consumes: Task 2 helpers (`keyed`, `qbtn`, `series`, `latest`, `winMedian`, `watchFor`, `judge`, `unitOf`, `fmtAny`).
- Produces: view `v0`; element ids `o_tiles`, `o_attn`, `o_note`, `o_more`, `chipLamp`, `chipCodes`. Tile nodes carry `data-key` (`trims|ect|volts|load|map`) and className `tile`, `tile watch`, `tile out`, `tile neutral` or `tile idle`; each has children classed `big` and `sub`. Attention rows carry `data-key` = PID.

- [ ] **Step 1: Write the failing tests.** Insert before `console.log('page logic OK');`:

```js
  // 6) Overview: tile state from the catalog's watch ranges on a 10 s median, honest empty states, attention list
  const tw = { ok: [-10, 10], out: [-20, 20] };
  const mk = (title, w, extra) => Object.assign({ title, measures: title + ' explained.', use: [], typical: '', status: [] }, w ? { watch: w } : {}, extra || {});
  const OVF = { pids: { '06': mk('Short-term trim, bank 1', tw), '07': mk('Long-term trim, bank 1', tw), '08': mk('Short-term trim, bank 2', tw),
                        '09': mk('Long-term trim, bank 2', tw), '05': mk('Coolant', { ok: [null, 105], out: [null, 112] }),
                        '42': mk('Battery', { ok: [13.2, 14.8], out: [11.5, 15.5] }, { watch_engine_off: { ok: [12.2, 12.9], out: [11.5, 13.5] } }),
                        '04': mk('Engine load'), '0B': mk('Manifold pressure') }, mode06: {} };
  const base = () => ({ '0C': 700, '05': 90, '06': 2, '07': 1, '08': 2, '09': 1, '0B': 36, '42': 14.2, '04': 28 });
  const ovEnv = async (fn, tweak) => {
    const e = makeEnv(statesFor(30, fn).map(st => (tweak ? tweak(st) : st)), 'v0', OVF);
    for (let k = 0; k < 32; k++) await e.tick();
    return e;
  };
  const tile = (e, key) => { let r = null; walk(e.el('o_tiles'), n => { if (n.getAttribute('data-key') === key) r = n; }); return r; };
  const part = (t, cls) => t.children.filter(c => c.className === cls)[0].textContent;
  const rowsOf = e => e.el('o_attn').children.map(c => c.getAttribute('data-key'));

  const okEnv = await ovEnv(base);
  assert.deepStrictEqual(['trims', 'ect', 'volts', 'load', 'map'].map(k => tile(okEnv, k).className), ['tile', 'tile', 'tile', 'tile neutral', 'tile neutral'], 'healthy: normal tiles, no-threshold tiles neutral');
  assert.strictEqual(okEnv.el('o_note').textContent, 'Nothing out of range');
  assert.strictEqual(part(tile(okEnv, 'load'), 'sub'), 'live');
  const wEnv = await ovEnv(() => Object.assign(base(), { '06': 13, '42': 12.1 }));
  assert.strictEqual(tile(wEnv, 'trims').className, 'tile watch'); assert.strictEqual(part(tile(wEnv, 'trims'), 'big'), '13.0');
  assert(/bank 1/.test(part(tile(wEnv, 'trims'), 'sub')), 'the subtitle names the worst trim');
  assert.strictEqual(tile(wEnv, 'volts').className, 'tile watch');
  assert.deepStrictEqual(rowsOf(wEnv), ['06', '42'], 'attention lists only out-of-range readings'); assert.strictEqual(wEnv.el('o_note').textContent, '');
  const oEnv = await ovEnv(() => Object.assign(base(), { '09': 25, '42': 12.1 }));
  assert.strictEqual(tile(oEnv, 'trims').className, 'tile out'); assert.deepStrictEqual(rowsOf(oEnv), ['09', '42'], 'out of range sorts before watch');
  const offEnv = await ovEnv(() => Object.assign(base(), { '0C': 0, '42': 12.4 }));
  assert.strictEqual(tile(offEnv, 'volts').className, 'tile', 'engine off: 12.4 V is normal');
  assert.strictEqual(tile(wEnv, 'volts').className, 'tile watch', 'engine running: low voltage is flagged');
  const noLoad = await ovEnv(() => { const b = base(); delete b['04']; return b; });
  assert.strictEqual(tile(noLoad, 'load').className, 'tile idle'); assert.strictEqual(part(tile(noLoad, 'load'), 'sub'), 'not reported');
  const stale = await ovEnv((s) => { const b = base(); if (s > 10) delete b['04']; return b; });
  assert(/^last seen \d+ s ago$/.test(part(tile(stale, 'load'), 'sub')), 'a rotating extra shows its age: ' + part(tile(stale, 'load'), 'sub'));
  const stopped = await ovEnv(base, st => Object.assign(st, { status: 'stopped' }));
  assert.strictEqual(part(tile(stopped, 'ect'), 'sub'), 'not sampling'); assert.strictEqual(stopped.el('o_note').textContent, 'Not sampling');
  assert.deepStrictEqual(rowsOf(stopped), []);
  const chipsEnv = await ovEnv(base, st => Object.assign(st, { codes: { read: true, note: null, mil: true, stored: [{ code: 'P0300' }], pending: [], permanent: [] } }));
  assert.strictEqual(chipsEnv.el('chipLamp').textContent, 'lamp on'); assert.strictEqual(chipsEnv.el('chipCodes').textContent, '1 stored');
  const chipsNone = await ovEnv(base, st => Object.assign(st, { codes: { read: false, note: null } }));
  assert.strictEqual(chipsNone.el('chipLamp').textContent, 'lamp ?'); assert.strictEqual(chipsNone.el('chipCodes').textContent, 'codes not read');
  const qTrim = findQ(wEnv.el('o_attn'), '06'); assert(qTrim, 'attention rows have a ? button');
  wEnv.docHandlers.click({ target: qTrim }); assert(/Short-term trim, bank 1/.test(flat(wEnv.el('helpPanel'))) && /now 13/.test(flat(wEnv.el('helpPanel'))), 'row help shows the catalog and the live value');
```

In `tests/test_console_page.py` add `"chipLamp", "chipCodes", "o_tiles", "o_attn", "o_note", "helpPanel"` to the element-id tuple in `test_required_controls_exist_and_no_simulator_is_baked_in`, and change `assert {"v1", "v2", "v3", "v4", "v5"} <= views` to `assert {"v0", "v1", "v2", "v3", "v4", "v5", "v6"} <= views`.

- [ ] **Step 2: Run, expect FAIL**

Run: `node tests/js/page_logic_test.js src/obd_reader/web/console.html` -> expected `FAIL` (tile is null; `o_tiles` empty).
Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest tests/test_console_page.py -q` -> expected FAIL on missing ids.

- [ ] **Step 3: Implement in `src/obd_reader/web/console.html`.**

(a) CSS, add before `</style>`:

```css
  #v0 h3.sec { font: 700 12px var(--cond); letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin: 18px 0 8px; }
  #v0 h3.sec:first-child { margin-top: 0; }
  #v0 .tiles { display: grid; gap: 12px; grid-template-columns: repeat(5, 1fr); }
  #v0 .tile { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--ok); border-radius: 8px; padding: 10px 12px; position: relative; min-width: 0; }
  #v0 .tile.watch { border-left-color: var(--amber); } #v0 .tile.out { border-left-color: var(--bad); }
  #v0 .tile.neutral { border-left-color: var(--line); } #v0 .tile.idle { border-left-color: var(--line); opacity: .65; }
  #v0 .tile h3 { font: 700 12px var(--cond); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin: 0 0 6px; padding-right: 26px; }
  #v0 .tile .q { position: absolute; top: 8px; right: 8px; }
  #v0 .tile .sub { color: var(--muted); font-size: 12px; margin-top: 4px; min-height: 18px; }
  #v0 .tile.watch .sub { color: var(--amber); } #v0 .tile.out .sub { color: var(--bad); }
  #v0 .tile .spark svg, #v0 svg.spark { width: 100%; height: 34px; display: block; margin-top: 6px; }
  #v0 svg.spark polyline { fill: none; stroke: var(--cyan); stroke-width: 1.6; }
  #v0 .attn { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
  #v0 .attn:empty { display: none; }
  #v0 .orow { display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-top: 1px solid var(--line); }
  #v0 .orow:first-child { border-top: 0; }
  #v0 .orow .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--amber); flex: none; }
  #v0 .orow .dot.out { background: var(--bad); }
  #v0 .orow .nm { font: 700 13px var(--cond); letter-spacing: .05em; text-transform: uppercase; min-width: 170px; }
  #v0 .orow .val { font: 700 15px var(--cond); min-width: 82px; font-variant-numeric: tabular-nums; }
  #v0 .orow .why { color: var(--muted); font-size: 12.5px; flex: 1; }
  #v0 .note { color: var(--muted); font-size: 12.5px; margin: 0 0 8px; }
  #v0 .more { display: block; margin-top: 14px; color: var(--cyan); font: 600 13px var(--cond); letter-spacing: .05em; text-decoration: none; }
  @media (max-width: 900px) { #v0 .tiles { grid-template-columns: repeat(2, 1fr); } #v0 .tile:first-child { grid-column: span 2; } }
  @media (max-width: 560px) { #v0 .orow { flex-wrap: wrap; } #v0 .orow .nm { min-width: 0; flex: 1; } #v0 .orow .why { flex: 1 1 100%; order: 3; } }
```

(b) HTML. In `<nav class="switcher">` insert as the first button `<button class="vbtn is-active" data-view="v0" role="tab">Overview</button>` and remove `is-active` from the `data-view="v1"` button. In the status bar, add after the `chipCar` span:

```html
  <span class="chip" id="chipLamp">lamp ?</span>
  <span class="chip" id="chipCodes">codes not read</span>
```

Insert before `  <!-- A: COCKPIT -->` and remove `is-active` from `<section class="view is-active" id="v1"`:

```html
  <section class="view is-active" id="v0" role="tabpanel">
    <h3 class="sec">Health</h3>
    <div class="tiles" id="o_tiles"></div>
    <h3 class="sec">Needs attention</h3>
    <div class="attn" id="o_attn"></div>
    <p class="note" id="o_note"></p>
    <a class="more" href="#v6" id="o_more">All readings and on-board tests &rarr;</a>
  </section>
```

(c) JS. Change `function active() {...}`'s fallback `'v1'` to `'v0'`. Add to `chips()` just after the `chipCar` lines:

```js
    var cd = st.codes || {};
    $('chipLamp').textContent = 'lamp ' + (cd.read ? (cd.mil ? 'on' : 'off') : '?');
    $('chipCodes').textContent = !cd.read ? 'codes not read'
      : (cd.stored && cd.stored.length ? cd.stored.length + ' stored' : 'none stored') + (cd.pending && cd.pending.length ? ' · ' + cd.pending.length + ' pending' : '');
```

Add before `function render() {`:

```js
  /* ---------- Overview ---------- */
  var TILES = [
    { key: 'trims', title: 'Fuel trims', pids: ['06', '07', '08', '09'], dp: 1 },
    { key: 'ect', title: 'Coolant', pids: ['05'], dp: 0 },
    { key: 'volts', title: 'Battery', pids: ['42'], dp: 1 },
    { key: 'load', title: 'Engine load', pids: ['04'], dp: 0 },
    { key: 'map', title: 'Manifold pressure', pids: ['0B'], dp: 0 }
  ];
  var TRIM_NAME = { '06': 'short-term, bank 1', '07': 'long-term, bank 1', '08': 'short-term, bank 2', '09': 'long-term, bank 2' };
  var ROW_NAME = { '06': 'Short-term trim, bank 1', '07': 'Long-term trim, bank 1', '08': 'Short-term trim, bank 2', '09': 'Long-term trim, bank 2',
                   '05': 'Coolant temperature', '42': 'Battery voltage' };
  var ATTN = ['06', '07', '08', '09', '05', '42'];
  var RANK = { none: 0, neutral: 1, ok: 2, watch: 3, out: 4 };
  var WORD = { ok: 'normal', watch: 'watch', out: 'out of range', neutral: '', none: 'not reported' };
  function sparkSvg(s) {
    if (s.length < 2) return '';
    var lo = Infinity, hi = -Infinity, t0 = tNow - SPAN;
    s.forEach(function (p) { lo = Math.min(lo, p.v); hi = Math.max(hi, p.v); });
    if (hi === lo) { hi += 1; lo -= 1; }
    var pts = s.map(function (p) { return (Math.max(0, (p.t - t0) / SPAN) * 120).toFixed(1) + ',' + (32 - (p.v - lo) / (hi - lo) * 30).toFixed(1); }).join(' ');
    return '<svg class="spark" viewBox="0 0 120 34" preserveAspectRatio="none"><polyline points="' + pts + '"/></svg>';
  }
  function tileModel(t, run) {
    var main = null, mv = null, worst = 'none';
    t.pids.forEach(function (p) {
      var v = run ? winMedian(p) : latest(p);
      if (v === null || v === undefined) return;
      var s = run ? judge(v, watchFor(p)) : 'none';
      if (RANK[s] > RANK[worst]) worst = s;
      if (main === null || Math.abs(v) > Math.abs(mv)) { main = p; mv = v; }
    });
    var cls = !run || main === null ? 'idle' : worst === 'ok' ? '' : worst, sub;
    if (!run) sub = 'not sampling';
    else if (main === null) sub = 'not reported';
    else if (t.key === 'load') { var s2 = series('04'), age = tNow - s2[s2.length - 1].t; sub = age < 2 ? 'live' : 'last seen ' + Math.round(age) + ' s ago'; }
    else if (t.key === 'trims') sub = TRIM_NAME[main] + (worst !== 'ok' && WORD[worst] ? ' · ' + WORD[worst] : '');
    else sub = WORD[worst];
    return { key: t.key, title: t.title, cls: cls, help: main || t.pids[0], value: mv === null ? '—' : fmt(mv, t.dp), unit: unitOf(t.pids[0]),
             sub: sub, spark: sparkSvg(series(main || t.pids[0])) };
  }
  function makeTile(it) {
    var root = el('div', 'tile'), q = qbtn(it.help), h = el('h3', '', it.title), big = el('span', 'big'), unit = el('span', 'unit'),
        sub = el('div', 'sub'), spark = el('div', 'spark'), line = el('div');
    root.setAttribute('data-key', it.key);
    line.appendChild(big); line.appendChild(unit);
    [q, h, line, sub, spark].forEach(function (c) { root.appendChild(c); });
    return { root: root, q: q, big: big, unit: unit, sub: sub, spark: spark };
  }
  function updTile(nd, it) {
    nd.root.className = 'tile' + (it.cls ? ' ' + it.cls : '');
    nd.q.setAttribute('data-help', it.help);
    nd.big.textContent = it.value; nd.unit.textContent = it.unit; nd.sub.textContent = it.sub;
    nd.spark.innerHTML = it.spark;   // numbers only
  }
  function makeRow(it) {
    var root = el('div', 'orow'), dot = el('span', 'dot'), nm = el('span', 'nm', ROW_NAME[it.key]), val = el('span', 'val'), why = el('span', 'why');
    root.setAttribute('data-key', it.key);
    [dot, nm, val, why, qbtn(it.key)].forEach(function (c) { root.appendChild(c); });
    return { root: root, dot: dot, val: val, why: why };
  }
  function updRow(nd, it) {
    var e = HELP.pids[it.key];
    nd.dot.className = 'dot ' + it.s;
    nd.val.textContent = fmt(it.v, it.key === '05' ? 0 : 1) + ' ' + unitOf(it.key);
    nd.why.textContent = e && typeof e === 'object' ? String(e.measures) : '';
  }
  function renderOverview() {
    var run = !!state && state.status === 'running', models = TILES.map(function (t) { return tileModel(t, run); });
    keyed($('o_tiles'), models, makeTile, updTile);
    var rows = !run ? [] : ATTN.map(function (p) { var v = winMedian(p); return { key: p, v: v, s: judge(v, watchFor(p)) }; })
      .filter(function (r) { return r.s === 'watch' || r.s === 'out'; })
      .sort(function (a, b) { return RANK[b.s] - RANK[a.s] || ATTN.indexOf(a.key) - ATTN.indexOf(b.key); });
    keyed($('o_attn'), rows, makeRow, updRow);
    var have = models.some(function (m) { return m.cls !== 'idle'; });
    $('o_note').textContent = rows.length ? '' : !run ? 'Not sampling' : have ? 'Nothing out of range' : 'Waiting for readings';
  }
  $('o_more').addEventListener('click', function (e) { if (e.preventDefault) e.preventDefault(); show('v6'); });
```

In `render()`, change the chain `if (view === 'v1') { ... } else if (view === 'v2') {` by inserting, before the `if (view === 'v1') {` line, a new first branch; i.e. turn `if (view === 'v1') {` into:

```js
    if (view === 'v0') {
      renderOverview();
    } else if (view === 'v1') {
```

- [ ] **Step 4: Run, expect PASS**

Run: `node tests/js/page_logic_test.js src/obd_reader/web/console.html` -> `page logic OK`.
Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q` -> all pass.

- [ ] **Step 5: Look at it in the browser.** Run `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m obd_reader console --demo`, open the printed link, press Start sampling, click a few "?". Expected: five tiles fill in; the demo "rich" scenario pushes the trims tile amber/red and adds attention rows; popups open and close.

- [ ] **Step 6: Commit**

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js tests/test_console_page.py
git commit -m "feat: Overview tab with health tiles and needs-attention list, lamp and codes chips"
```

---

### Task 4: Retire Cockpit and Scope, trim the page text, docs

**Files:**
- Modify: `src/obd_reader/web/console.html`, `tests/js/page_logic_test.js`, `tests/test_console_page.py`, `README.md`

**Interfaces:**
- Consumes: everything above. Produces: tabs Overview, Guided test, Analyzer, Handheld, All readings; no `v1`/`v2`; no "read-only" page text; harness default view `v0`.

- [ ] **Step 1: Retarget the two tests that used the retired tabs.** In `tests/js/page_logic_test.js`:

1. Change the harness default `viewId = 'v1'` to `viewId = 'v0'`.
2. Test "4)": replace `const env4 = makeEnv(statesFor(5, idle).concat(statesFor(2, rev, 0, 0)));` with `const env4 = makeEnv(statesFor(5, idle).concat(statesFor(2, rev, 0, 0)), 'v3');` and `env4.el('v1rpm')` with `env4.el('v3rpm')`.
3. Test "7)": replace the four lines from `const a = statesFor(3, idle, 0, 0);` through the `assert(/min 2500 · max 2500/...` line with:

```js
  const a = statesFor(3, () => Object.assign(base0(), { '42': 15.4 }), 0, 0);   // run 1: seq 1..3, battery 15.4 V
  const b = statesFor(1, () => Object.assign(base0(), { '42': 12.1 }), 9, 1.2);  // run 2 already at seq 10, battery 12.1 V
  b[0].run = 2;
  const env7 = makeEnv(a.concat(b), 'v0', { pids: { '42': { title: 'Battery', measures: 'x', use: [], typical: '', status: [], watch: { ok: [13.2, 14.8], out: [11.5, 15.5] } } }, mode06: {} });
  for (let k = 0; k < 5; k++) await env7.tick();
  let vt = null; walk(env7.el('o_tiles'), n => { if (n.getAttribute('data-key') === 'volts') vt = n; });
  assert.strictEqual(vt.children.filter(c => c.className === 'sub').length, 1);
  assert(/^12\.1$/.test(vt.children[2].children[0].textContent), 'run 1 samples were dropped when run 2 began: battery reads 12.1, not the old 15.4');
```

and define `const base0 = () => ({ '0C': 700, '05': 90, '06': 2, '07': 1, '08': 2, '09': 1, '0B': 36, '42': 14.2 });` directly above this test's block. (Without the reset the 10 s median of [15.4, 15.4, 15.4, 12.1] is 15.4.)
4. In test "8)"-area handheld assertion `assert(/Check engine \(MIL\)/.test(hh.el('h_status').innerHTML) && /Read-only/.test(hh.el('h_status').innerHTML), 'status pane');` replace `/Read-only/` with `/Sampling/`.

- [ ] **Step 2: Run, expect FAIL only where the old tabs still exist**

Run: `node tests/js/page_logic_test.js src/obd_reader/web/console.html`
Expected: passes or fails on the `Sampling` assertion only after Step 3 removes the lamp (the retargeted tests should already pass against the current page). If the new test 7 fails, the run-reset logic is wrong; stop and diagnose before deleting anything.

- [ ] **Step 3: Delete Cockpit and Scope.** Save this as `scripts/retire_tabs.py` temporarily (do not commit it), run it from the repo root, then delete it:

```python
import re
p = "src/obd_reader/web/console.html"
L = open(p, encoding="utf-8").read().split("\n")
def cut(start_pat, end_pat):
    s = next(i for i, l in enumerate(L) if start_pat in l)
    e = next(i for i, l in enumerate(L) if end_pat in l and i > s)
    del L[s:e]
cut("/* v1 cockpit */", "/* v3 guided */")
cut("<!-- A: COCKPIT -->", "<!-- C: GUIDED TEST -->")
cut("Array.prototype.forEach.call(document.querySelectorAll('#strips .card')", "renderResults(); render();")
open(p, "w", encoding="utf-8").write("\n".join(L))
```

Then edit `render()` by hand: delete the `CH.forEach(function (c) { var e = $('v1' + c.id); ... });` line, and delete the `else if (view === 'v1') { ... }` and `else if (view === 'v2') { ... }` branches so the chain reads `if (view === 'v0') { renderOverview(); } else if (view === 'v4') { renderCabinet(); } else if (view === 'v5') { renderHandheld(); } else { <guided-test block> }`. Remove the two tab buttons (`data-view="v1"`, `data-view="v2"`) and rename the remaining labels to `Overview`, `Guided test`, `Analyzer`, `Handheld`, `All readings`.

Delete functions the two tabs orphaned, after confirming each is unused: run `for f in rpmGauge trimTag biBar; do echo $f $(grep -c "$f" src/obd_reader/web/console.html); done`; a count of `1` (the definition only) means delete that function. Do not delete `trend` (Guided test uses it) or `fmt`.

- [ ] **Step 4: Remove the extraneous text.** In `src/obd_reader/web/console.html`:
  - Delete the `<small>local page, token-protected, read-only</small>` element from the `.brand` div.
  - Delete the `<span class="chip ro"><b>READ-ONLY</b> &middot; this page cannot send commands</span>` line.
  - Analyzer plate: change `<small>READ-ONLY &middot; NO OUTPUTS &middot; SER. 0709</small>` to `<small>SER. 0709</small>`.
  - Analyzer codes label: change `plain-words meanings &middot; read-only` to `plain-words meanings`.
  - Analyzer lamp: delete the `<div class="lampbox lit"><i class="lens grn"></i><div><b>Read-only</b><em>cannot send commands</em></div></div>` element.
  - Handheld: in the `ledLamp(...)` line delete ` + ledLamp('', true, 'grn', 'Read-only', 'cannot send commands')`.
  - Footer: delete the sentence `Nothing on this page can send a command to the car. ` from the `<p class="foot">`.
  - Keep the amber `demoBanner`.
  Afterwards `grep -n -i "read-only\|cannot send" src/obd_reader/web/console.html` must print nothing.

- [ ] **Step 5: Update `tests/test_console_page.py`.**
  - `views` assertion: `{"v0", "v3", "v4", "v5", "v6"} <= views` and add `assert "v1" not in views and "v2" not in views`.
  - Element-id tuple: remove `"rpmGauge", "c1trims", "s_trim"`.
  - Delete `test_every_multi_line_chart_has_a_legend_naming_each_line` and `test_the_legend_distinguishes_lines_by_pattern_not_only_by_colour` (they test the retired Cockpit/Scope legends) and the `_section` helper if nothing else uses it.
  - Replace `test_page_states_it_is_read_only_and_marks_the_playbook_unreviewed` with:

```python
def test_page_has_no_read_only_banner_and_marks_the_playbook_unreviewed():
    assert "unreviewed" in HTML
    assert "READ-ONLY" not in HTML and "cannot send" not in HTML
```

- [ ] **Step 6: Update `README.md`.** In the verified-table row beginning `| Live console: Cockpit, Scope, Guided test, Analyzer cabinet, Handheld (phone), Readings |` replace the tab list with `Overview (health tiles and needs-attention list), Guided test, Analyzer cabinet, Handheld (phone), All readings`. Add after the "Car memory" paragraph:

`**Help popups:** every reading, tile and Mode 06 line has a "?" that says what it measures, how to use it and typical values. The wording is ours and unreviewed (it says so in the popup); the colors on the Overview use general rules of thumb, not limits for your particular car.`

- [ ] **Step 7: Run everything and look at it**

Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q` -> expected all pass.
Run: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m obd_reader console --demo`, open it at laptop and phone width, click through all five tabs and a few "?". Expected: Overview is the home tab, no READ-ONLY chip anywhere, the demo banner still shows, Guided test still runs its idle capture.

- [ ] **Step 8: Commit**

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js tests/test_console_page.py README.md
git commit -m "feat: retire the Cockpit and Scope tabs, drop the read-only page text, document the Overview and help"
```

---

## Self-Review

- **Spec coverage:** catalog, fields, `watch` semantics and `/api/help` (Task 1); popup behavior, one open at a time, Escape/outside close, generic fallback, `textContent` only (Task 2); Overview tiles, 10 s median, honest states, attention list, neutral tiles, status chips (Task 3); retire Cockpit/Scope, remove read-only text, keep demo banner, README (Task 4). The spec's "Mode 06 lines have help" is in Task 2. The spec's `rename Readings to All readings` is in Task 4 Step 3.
- **Deviations:** listed at the top of this plan (24-entry coverage, engine-off `out` range, chips in the shared bar, keyed updates).
- **Placeholder scan:** none; every code step has full code.
- **Type consistency:** help keys are a PID string or `m06:<group>` everywhere (`qbtn`, `helpEntry`, `liveLine`, tests); `watch`/`watch_engine_off` are `{ok:[lo,hi], out:[lo,hi]}` with `null` open ends in Python, JSON and `judge`; tile and row nodes carry `data-key`; `keyed(box, items, make, update)` items always have a `key`.
- **Known risk:** Task 4 Step 3 edits the shared page script by hand after a scripted block delete; Step 2 and the suite are the guard, so run the Node test and the full suite before committing.
