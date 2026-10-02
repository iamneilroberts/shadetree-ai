# Console stage 3: Retro cabinet, Handheld, phone defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the console redesign: the Analyzer stops being a separate page and becomes the Retro skin of the Dashboard on desktop (codes, lamps and the full PID table included); Handheld is rebuilt from the shared parts (Live | Codes, opening on Live, scenario dropdown, 2-up gauges, full PID table); a phone opens Handheld; the replay transport bar stays pinned at the bottom of a phone.

**Architecture:** Two new shared parts (a Lamps strip and a Codes panel) are built once in `console.html` and mounted by both the Dashboard and Handheld. The Dashboard gets cabinet chrome (rails, nameplate, screws, the Clarity rocker) that CSS shows only in the Retro skin above 600 px. The old Analyzer view (`v4`, `renderCabinet`, the `a_*` ids) is deleted. Handheld's Live pane draws the current scenario's gauges (`specsFor(curScenario())`) and `pidRows`; the scenario choice (`SC`) is shared with the Dashboard. A pure `pickView(hash, narrow)` chooses the opening view. No server changes.

**Tech Stack:** One-file `src/obd_reader/web/console.html` (vanilla JS, hash-pinned CSP), pytest, `node tests/js/page_logic_test.js`.

**Spec:** `docs/superpowers/specs/2026-10-01-console-coherence-design.md` (Stage 3, lines 34-38, plus the retained-features list). Stage 2 plan for style: `docs/superpowers/plans/2026-10-01-console-stage2-dashboard-and-scenarios.md`.

## Global Constraints

- Public repo, MIT: no VINs, real transcripts, `runs/`, `profiles/`, `shadetree-share*` in any file or test. Synthetic fixtures only.
- Read-only app; no new data capture, no server change, no new route.
- One file: `console.html` keeps exactly one `<script>` and one `<style>`, no external URLs, no framework; every colour is a CSS variable (`test_colours_live_only_in_the_token_blocks`); text from the car, a scenarios file or localStorage is set with `textContent` or passed through `esc()` before any `innerHTML`.
- Size budget in `tests/test_console_page.py::test_page_stays_one_file_under_its_size_budget` is 130,000 bytes (page is about 120,000 now); stage 3 deletes the Analyzer, so it should shrink or hold. Raising the budget needs a ruling in the ledger.
- Retained features (spec line 17) stay reachable at every commit: Capture all supported, Demo, Save run, replay picker and `?example=`, Mode 06 section, All readings stats, Units, Theme, Skin, "?" help popups, codes and the lamp, Guided test, upload, transport bar. `RETAINED` in `tests/test_console_page.py` is updated in the task that moves a feature, never weakened.
- The Plain skin and the phone layout must not pick up cabinet chrome: every new cabinet rule is scoped to `:root[data-skin="retro"]` inside `@media (min-width: 601px)`.
- Commands (from the worktree root; `PYTHONPATH=src` makes the worktree package shadow the editable install):
  - node: `node tests/js/page_logic_test.js src/obd_reader/web/console.html` (prints `page logic OK`)
  - page tests: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q tests/test_console_page.py`
  - full suite: `PYTHONPATH=src /home/neil/dev/obd-reader/.venv/bin/python -m pytest -q` (688 passed before stage 3)
- Commit per task, stage files by name, no attribution lines. Do not push or merge; Neil says "merge and push".

## Rulings made in this plan (cheap to undo; Neil may overrule)

1. **Analyzer tab is removed** (spec: "stops being a separate page"). `#v4` in a URL falls back to the default view.
2. **Codes and lamps move onto the Dashboard in both skins**, as a Lamps strip and a Codes panel under the gauges. Without this, Plain desktop would lose the codes view the Analyzer was the only desktop home of.
3. **Handheld modes are Live | Codes only.** Trims becomes the "Fuel trims" scenario (dropdown); the Status lamps become the Lamps strip at the top of Live. Handheld does not edit gauges (editing stays on the Dashboard); the scenario choice is shared.
4. **The opening view is not saved.** A viewport at or under 600 px opens Handheld unless the URL has a `#view` hash; a desktop opens the Dashboard. `?example=` does not change the view on its own (on a phone Handheld is already the default). Skin, theme and scenario keep their stored choices.
5. **The Clarity rocker moves into the cabinet's bench row** on the Dashboard (Retro skin only).
6. **Replay bar** is `position: fixed` at the bottom at 600 px and under, not just in Handheld.

## Review Focus

1. Plain skin and phone width must look exactly as before on the Dashboard (cabinet chrome leaking into them): tested by CSS-scope assertions that fail if a cabinet rule loses its `:root[data-skin="retro"]` + 601 px scope (Task 2).
2. Codes and the lamp stay reachable once the Analyzer is gone, and a code description or hint containing markup is shown as text (Tasks 1, 3).
3. A stale `#v4` hash, an unknown hash, and stage 2's saved scenarios (`shadetree.scen.*`, `shadetree.scenario`) all still work (Tasks 3, 5).
4. Handheld with no run, no channels, an emptied scenario (`[]`), a PID not in the run, and a scenario changed on the Dashboard while Handheld is open: gauges dim or say so, no fake zero, the dropdown stays in step (Task 4).
5. The phone default must not hijack: a `#v0` hash wins, a desktop width opens the Dashboard, resizing across 600 px after load does not switch views; the fixed replay bar must not cover the Handheld nav or Menu (Tasks 5, 6).

---

## File Structure

| File | Change |
|---|---|
| `src/obd_reader/web/console.html` | Lamps strip + Codes panel parts; cabinet chrome; delete Analyzer; rebuild Handheld; `pickView`; fixed replay bar |
| `tests/js/page_logic_test.js` | tests for each task; delete the Analyzer (`a_*`) tests; update Handheld tests |
| `tests/test_console_page.py` | `RETAINED`, Handheld frame test, cabinet-scope and replay-bar CSS tests, size budget |
| `docs/design.md` §7b, `README.md`, `CLAUDE.md` | document the new views and the test count |

---

### Task 1: Shared Lamps strip and Codes panel, mounted on the Dashboard

**Files:**
- Modify: `src/obd_reader/web/console.html` (parts after `pidTableEl`/before `BUILTIN`; Dashboard markup `#v0`; `renderDashboard`; hook), `tests/js/page_logic_test.js`

**Interfaces:**
- Consumes: existing `retroCommon()` (returns `{c, list, live, mil, stored}`), `codeList`, `codeRows(list, cls)`, `codeEmpty(c, running)`, `ledLamp(id, on, cls, b, e)`, `trimText(v)`, `esc`, `seven(el, value, digits, dp, colour, size)`, `last.ltft1/ltft2/ect`, `state.status`, `state.hz_measured`, `panel(title)`.
- Produces: `lampModel() -> [{id, on, cls, b, e}]` for ids `mil, ltft1, ltft2, ect, samp` in that order, with the exact texts below; `lampsHtml(model) -> string` (fixed markup, `ledLamp`); `renderLamps(box)` sets `box.innerHTML = lampsHtml(lampModel())` only when the string changed (`box._sig`); `codesPanel() -> {root, cnt, list}` (a `panel('Trouble codes')` whose body holds a seven-segment count window `.win.led`, a `.clist` and the `.cfoot` disclaimer); `renderCodes(cp)` fills it. Dashboard ids: `d_lamps` (a `.lamps` div), `d_codes_mount`, and inside the panel `d_cnt`, `d_codes`. Dashboard order: scenario bar, gauges panel, `d_lamps`, codes panel, General strip, table. Hook gains `lampModel`.

`lampModel` (same rules as today's `renderCabinet`/`renderHandheld`):

```js
  function lampModel() {
    var r = retroCommon(), st = state || {}, l1 = last.ltft1 !== null && Math.abs(last.ltft1) > 10, l2 = last.ltft2 !== null && Math.abs(last.ltft2) > 10,
        cold = last.ect !== null && last.ect < 60, run = st.status === 'running';
    return [
      { id: 'mil', on: r.mil, cls: 'red', b: 'Check engine (MIL)', e: r.mil ? 'ON' : (r.c.read ? 'off' : 'unknown') },
      { id: 'ltft1', on: l1, cls: 'red', b: 'LTFT bank 1', e: l1 ? trimText(last.ltft1) : 'within range' },
      { id: 'ltft2', on: l2, cls: 'red', b: 'LTFT bank 2', e: l2 ? trimText(last.ltft2) : 'within range' },
      { id: 'ect', on: cold, cls: 'amb', b: 'Coolant', e: cold ? 'reads cold' : 'warm' },
      { id: 'samp', on: run, cls: 'grn', b: 'Sampling', e: run ? (st.hz_measured ? st.hz_measured.toFixed(1) + ' Hz' : 'starting') : 'not sampling' }
    ];
  }
  function lampsHtml(m) { return m.map(function (x) { return ledLamp('', x.on, x.cls, x.b, x.e); }).join(''); }
```

- [ ] **Step 1: Write the failing node tests** (insert before `console.log('page logic OK')`; adapt harness idioms from the Dashboard tests, search `Dashboard` in the file)

```js
// 14) Lamps strip and Codes panel
{
  const mk = (over) => Object.assign({ status: 'running', hz_measured: 2.5, channels: {}, stats: {}, extras: {}, seq: 1,
    codes: { read: true, mil: true, stored: [{ code: 'P0171', desc: 'System too lean <b>x</b>', hint: 'check <i>air</i>' }], pending: [], permanent: [] } }, over);
  const e = makeEnv([mk({})], 'v0', OVF); for (let k = 0; k < 6; k++) await e.tick();
  const m = e.parts().lampModel();
  assert.deepStrictEqual(Array.from(m).map(x => x.id), ['mil', 'ltft1', 'ltft2', 'ect', 'samp']);
  assert.strictEqual(m[0].on, true); assert.strictEqual(m[0].e, 'ON');
  assert.strictEqual(m[4].e, '2.5 Hz');
  // the Dashboard shows the count, the code, and the text as text (no markup from the description)
  assert.strictEqual(e.el('d_cnt') !== null, true);
  const codes = e.el('d_codes');
  assert.ok(/P0171/.test(codes.innerHTML));
  assert.ok(!/<b>x<\/b>/.test(codes.innerHTML));            // escaped
  assert.ok(/&lt;b&gt;x&lt;\/b&gt;/.test(codes.innerHTML));
}
{
  // no read yet: the empty text, and the lamp says unknown; idle run says not sampling
  const e = makeEnv([{ status: 'idle', channels: {}, stats: {}, extras: {}, seq: 1, codes: { read: false, note: null } }], 'v0', OVF); await e.tick();
  assert.ok(/START SAMPLING TO READ CODES/.test(e.el('d_codes').innerHTML));
  const m = e.parts().lampModel();
  assert.strictEqual(m[0].e, 'unknown'); assert.strictEqual(m[4].e, 'not sampling');
}
```

Also assert: a read with zero codes shows `NO CODES STORED`; trims above +10 % light the LTFT lamp with the `LEAN: outside ±10 %` text; coolant at 40 C reads cold. Use `statesFor` with `last` values the way the Overview tests set them.

- [ ] **Step 2: Run node; expect FAIL** (`e.parts().lampModel` undefined).
- [ ] **Step 3: Implement.** Add `lampModel`, `lampsHtml`, `renderLamps`, `codesPanel`, `renderCodes` (the codes list HTML is `r.list.length ? codeRows(r.list, 'cab') : '<div class="cnone' + (r.c.read ? '' : ' wait') + '">' + codeEmpty(r.c, r.live) + '</div>'`, as `renderCabinet` does today; the count is `seven($('d_cnt'), r.c.read ? r.list.length : null, 2, 0, r.list.length ? 'var(--seg-red)' : 'var(--led-g)', 64)`). Mount in `#v0` markup (`<div class="lamps" id="d_lamps"></div><div id="d_codes_mount"></div>` between `#d_panel` and `#d_strip`); build the codes panel once in `renderDashboard`'s `if (!DB)` block; call `renderLamps($('d_lamps'))` and `renderCodes(DB.cp)` on every `renderDashboard`. The new parts use the existing `.lamps`, `.lampbox`, `.cwrap`, `.cntbox`, `.clist`, `.cfoot` rules; those are currently only styled inside the Analyzer `.retro` wrapper, so lift whichever of them are scoped by `.retro` / `.cab` to also apply under `#v0` (a selector list; no colour literals). Add `lampModel` to the hook.
- [ ] **Step 4: Run node, page tests, full suite; expect pass. Commit.**

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js
git commit -m "feat: console shared Lamps strip and Codes panel on the Dashboard (both skins): MIL, LTFT 1 and 2, coolant, sampling; the code count and the plain-words list, escaped"
```

---

### Task 2: Retro cabinet chrome on the Dashboard (desktop only)

**Files:**
- Modify: `src/obd_reader/web/console.html` (CSS for `.cab`/`.face`/`.plate`/`.screw`/`.bench`/`.rocker` currently lines ~115-230; `#v0` markup; the `clarity` handler ~1438), `tests/test_console_page.py`, `tests/js/page_logic_test.js`

**Interfaces:**
- Consumes: Task 1's Dashboard layout; existing cabinet rules (rails `.cab::before/::after`, `.face`, `.plate`, `.screw`, `.rocker`).
- Produces: a wrapper `<div class="dcab"><div class="dface"> … </div></div>` around the whole Dashboard content, with decorative `<span class="screw">` x4 and `<div class="plate"><span>Shadetree Model 7-A &middot; Engine Analyzer</span><small>SER. 0709</small></div>` as its first children, and a bench row at the end: `<div class="bench"><span class="lab">Display</span><button class="rocker" id="clarity" type="button">Clarity: standard</button></div>`. In the Plain skin and at 600 px or less the chrome elements are `display: none` and the wrapper adds no padding, border or background (the Dashboard looks as it does after stage 2). Clarity toggles class `max` on the `.retro` wrappers that remain; keep it working by putting the `retro` class on `.dcab` too, or by toggling `max` on `.dcab`.

- [ ] **Step 1: Write the failing tests**
  - `tests/test_console_page.py::test_cabinet_chrome_is_retro_desktop_only`: take the CSS, assert every rule whose selector mentions `.dcab`, `.dface` or `.dcab .plate`/`.screw`/`.bench` that gives it a visible look (border, background, padding, `::before/::after`) is scoped under `:root[data-skin="retro"]` inside a `@media (min-width: 601px)` block (regex over the parsed blocks; reuse `_css()`/`_block()` helpers from the file), and that the unscoped base rules for those chrome elements are only `display: none`. Prove it fails by mutating a rule's scope in a scratch copy (record how in the report).
  - Node: the Dashboard contains `clarity`; clicking it toggles its text between `Clarity: standard` and `Clarity: max` and does not throw; the Dashboard still renders 8 gauges (General).
- [ ] **Step 2: Run both; expect FAIL.**
- [ ] **Step 3: Implement.** Move the cabinet CSS so each rule is retro+desktop scoped (do not delete the old Analyzer rules yet; Task 3 removes what it orphans). Wrap `#v0`'s children. Move the `clarity` button and its handler's target. Ensure the gauges panel, lamps, codes panel and table sit inside `.dface` unchanged.
- [ ] **Step 4: Run node, page tests, full suite; expect pass. Commit.**

```bash
git add src/obd_reader/web/console.html tests/test_console_page.py tests/js/page_logic_test.js
git commit -m "feat: console Dashboard cabinet chrome in the Retro skin on desktop (rails, nameplate, screws, Clarity rocker); Plain and phone unchanged"
```

---

### Task 3: Delete the Analyzer view

**Files:**
- Modify: `src/obd_reader/web/console.html` (nav button `data-view="v4"` ~line 345, section `#v4` 453-492, `renderCabinet` 1405-1416 and its `render()` branch, helpers and CSS orphaned by the deletion), `tests/js/page_logic_test.js` (section 3 Analyzer tests ~200-230, units tests ~562-575 for `a_*`, Retro-light render of all views ~640), `tests/test_console_page.py` (`RETAINED`)

**Interfaces:**
- Consumes: Tasks 1-2 (codes, lamps, Clarity live on the Dashboard).
- Produces: no `v4` section, no Analyzer tab, no `a_*` ids, no `renderCabinet`; `RETAINED["Codes and lamp"]` requires `d_codes` and `h_codes` (was `a_codes`, `h_codes`); a URL with `#v4` opens the default view (the `init` check `$(init)` already fails for a missing id, so nothing extra is needed beyond a test).

- [ ] **Step 1: Write the failing tests.** pytest: no `id="v4"` and no `data-view="v4"` in the page; `RETAINED` updated. Node: `makeEnv(..., 'v0', ...)` with `page.hash = '#v4'` (add a `hash` option to the harness `location` if absent) leaves the Dashboard active; the five-views render test now iterates the four views (`v0, v3, v5, v6`) under Retro light without throwing; unit conversion for coolant and MAP is asserted on the Dashboard gauges and the table rows instead of `a_ect`/`a_map` (US units show °F and inHg).
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Delete** the nav button, the `#v4` section, `renderCabinet`, its `render()` branch, and then every helper, id lookup and CSS rule that nothing else uses (`meter()`, `ledBar`, `.trims`, `.meters`, `.cab` rules not reused by `.dcab`, etc.). Prove each is unused with `grep` before removing; keep what Handheld (Task 4) or the cabinet chrome uses and note what you kept in the report. Update the tests above (delete the Analyzer-only ones, keep their intent on the Dashboard).
- [ ] **Step 4: Run node, page tests, full suite; expect pass.** Check the page byte size dropped (report the number). Commit.

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js tests/test_console_page.py
git commit -m "feat: console Analyzer view removed: its codes, lamps and display controls live on the Dashboard, and a stale #v4 opens the default view"
```

---

### Task 4: Handheld rebuilt from the shared parts (Live | Codes)

**Files:**
- Modify: `src/obd_reader/web/console.html` (`#v5` markup, `renderHandheld`, `setMode`, `.hh` CSS, `drawTabs`, hook), `tests/js/page_logic_test.js`, `tests/test_console_page.py::test_handheld_frame_has_a_fixed_size_...` (panes become `["live", "codes"]`)

**Interfaces:**
- Consumes: `SC`, `curScenario()`, `setScenario(id)`, `drawTabs()`, `specsFor`, `gauges(box, specs)`, `pidRows`, `pidTableEl`, `renderLamps`, `retroCommon`, `codeRows(list, 'hh')`, `codeEmpty`.
- Produces: `#v5` inner markup:

```html
<div class="hh-top">…existing h_mil, h_miltxt, h_live, h_n…</div>
<div class="hh-scen"><select class="b" id="h_sel" aria-label="Scenario"></select></div>
<div class="hh-body">
  <div class="hh-pane" data-mode="live" id="h_livepane">
    <div class="lamps" id="h_lamps"></div>
    <div class="gauges" id="h_gauges"></div>
    <div id="h_table"></div>
  </div>
  <div class="hh-pane" data-mode="codes" id="h_codes" hidden></div>
</div>
<nav class="hh-nav"><button data-mode="live" class="on">Live</button><button data-mode="codes">Codes</button></nav>
```

`drawTabs()` fills `#h_sel` as well as `#d_sel` (same options, value `SC.id`); a change on `h_sel` calls `setScenario`. `renderHandheld()` keeps the top strip and the codes pane (unchanged text and `codeRows(..., 'hh')`), and in Live calls `renderLamps($('h_lamps'))`, `gauges(HB.g, specsFor(curScenario()))` and `pidRows(HB.rows, Object.keys(state.channels || {}).sort())` (the table part is built once into `#h_table` via `pidTableEl()`). CSS: `.hh .gauges { grid-template-columns: repeat(2, 1fr); }`, the table scrolls inside its `.rwrap`, Live pane scrolls inside `.hh-body` (`overflow-y: auto`), no horizontal scroll at 390 px.

- [ ] **Step 1: Write the failing tests**
  - Node: Handheld opens with Live active (`h_livepane` not hidden, `h_codes` hidden, the Live nav button has class `on`); Codes button shows codes and hides Live; `h_sel` has the 5 scenario options, value `general`; choosing `fuel` in `h_sel` changes `SC.id`, stores `shadetree.scenario`, and the Dashboard's `d_sel` value follows; Live shows 8 gauges for General and the table has one row per channel; a PID not in the run is a dim gauge with `not in this run`; an emptied saved scenario (`store['shadetree.scen.general'] = '[]'`) draws no gauges and the table still lists the run; with no channels the table body is empty and nothing throws; the `h_n` count and `h_miltxt` text are unchanged from today.
  - Pytest: panes are exactly `["live", "codes"]` in that order; no `h_rpm`, `h_l_stft1`, `h_status` ids remain.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** per the Interfaces. Remove the Trims and Status panes, `ledLamp`-built `h_status`, the `seven()`/`ledBar` calls and the `h_*` window ids, and the CSS they orphan (prove with `grep` first).
- [ ] **Step 4: Run node, page tests, full suite; expect pass. Commit.**

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js tests/test_console_page.py
git commit -m "feat: console Handheld rebuilt from the shared parts: Live (lamps, the scenario's gauges 2-up, the full PID table) and Codes, opening on Live with a scenario dropdown shared with the Dashboard"
```

---

### Task 5: Phone opens Handheld

**Files:**
- Modify: `src/obd_reader/web/console.html` (init near line 1496; hook), `tests/js/page_logic_test.js`

**Interfaces:**
- Produces: `pickView(hash, narrow) -> 'v0' | 'v5' | <view id>`: returns `hash` when it names a known view id (`v0`, `v3`, `v5`, `v6`), else `'v5'` when `narrow`, else `'v0'`. Known ids are checked against a fixed list, not `$()`, so `#v4`, `#vp`, and arbitrary hashes fall through. Init uses `show(pickView(hash, matchMedia('(max-width: 600px)').matches))` instead of the hash-only block, keeping the `scrollTo(0, 0)` on load when a hash was present. The opening view is not stored. Hook gains `pickView`.

- [ ] **Step 1: Write the failing node tests**

```js
// 17) pickView and the opening view
{
  const P = makeEnv(statesFor(3, base), 'v0', OVF).parts();
  assert.strictEqual(P.pickView('', false), 'v0');
  assert.strictEqual(P.pickView('', true), 'v5');
  assert.strictEqual(P.pickView('#v6', true), 'v6');   // hash given with or without '#': accept both forms
  assert.strictEqual(P.pickView('v3', false), 'v3');
  assert.strictEqual(P.pickView('v4', true), 'v5');    // removed view falls through to the default
  assert.strictEqual(P.pickView('nonsense', false), 'v0');
}
```

Plus env tests (use `page.narrow`, `page.hash`, `page.search`): narrow with no hash opens Handheld (`v5` section has `is-active`, its tab does too) on Live; narrow with `#v0` opens the Dashboard; desktop opens the Dashboard; desktop with `?example=x.json` opens the Dashboard (replay starts, view unchanged); narrow with `?example=x.json` opens Handheld; a stored scenario still wins; a `resize` event after load does not change the active view. Add `hash` to the harness `location` if it is not there yet.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** `pickView`, use it at init, add it to the hook.
- [ ] **Step 4: Run node, page tests, full suite; expect pass. Commit.**

```bash
git add src/obd_reader/web/console.html tests/js/page_logic_test.js
git commit -m "feat: console opens Handheld on a phone (600 px or less) unless the URL names a view; desktop opens the Dashboard; removed or unknown views fall back to the default"
```

---

### Task 6: Replay bar pinned at the bottom on a phone

**Files:**
- Modify: `src/obd_reader/web/console.html` (`.rbar`/`#rbar` CSS ~291-296, the 430 px Handheld block ~214-221, the 600 px block ~224-229), `tests/test_console_page.py`

**Interfaces:**
- Produces: at 600 px or less, while the bar is shown, `.rbar` is `position: fixed; left: 0; right: 0; bottom: 0` with a background token and a top border, laid out in at most two rows (range full width on its own row), and `--rbar-h` (a fixed height variable, 88px) is reserved: `body:has(.rbar:not([hidden])) .stage { padding-bottom: var(--rbar-h); }` and the Handheld frame height becomes `calc(100dvh - var(--topbar-h) - var(--rbar-h))` while the bar is shown. (Read how the bar is shown and hidden, `hidden` attribute or `display`, and key the selector on that.) The Handheld nav stays above the bar; the Menu stays reachable. No new colour literals.

- [ ] **Step 1: Write the failing pytest** (mutation-proof, like the Handheld frame test): inside the 600 px media block assert `.rbar` is `position: fixed` with `bottom: 0`; `--rbar-h` is defined once and used by both the stage padding and the Handheld frame calc; the rules are keyed to the bar being shown; no colour literal; and outside the 600 px block `.rbar` is not fixed. Verify each assertion fails on a mutated copy of the page (scratch dir) and say how in the report.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement the CSS.**
- [ ] **Step 4: Run page tests, node, full suite; expect pass. Commit.**

```bash
git add src/obd_reader/web/console.html tests/test_console_page.py
git commit -m "feat: console replay transport bar is pinned to the bottom on a phone, with room reserved for it, so the page and Handheld do not scroll under it"
```

---

### Task 7: Docs and counts

**Files:**
- Modify: `docs/design.md` §7b, `README.md`, `CLAUDE.md` (test count only if quoted)

- [ ] **Step 1:** Update §7b: Analyzer is gone (the Retro Dashboard on desktop has the cabinet chrome, lamps, codes and the full table); Handheld is Live | Codes with the scenario dropdown; phone defaults (Handheld, Retro, Live, General; hash wins; saved skin/theme/scenario win); the replay bar is pinned on a phone. README: views row and the phone line. Run the full suite for the test count and update the places that quote 688.
- [ ] **Step 2:** Run the three CHECK commands; paste results into the commit notes.
- [ ] **Step 3: Commit** (also adds this plan file).

```bash
git add docs/design.md README.md CLAUDE.md docs/superpowers/plans/2026-10-02-console-stage3-cabinet-handheld-phone.md
git commit -m "docs: console stage 3 (Retro cabinet Dashboard, Handheld Live | Codes, phone defaults, pinned replay bar); stage 3 plan"
```

---

## Neil's screenshot pass (before "merge and push")

Agents cannot see a browser. After Task 7 the controller starts a loopback console (`--demo --http-port 8799`) and shares: desktop Retro Dashboard (dark and light) with the cabinet chrome, lamps, codes and table; desktop Plain Dashboard (should look as after stage 2); Handheld at 390 px, Live with each of two scenarios, and Codes; the Menu in Handheld; a replay at 390 px with the pinned bar. Neil checks the cabinet look, the 2-up gauges, the table scrolling inside its card, and that the bar does not cover the Handheld nav.

## Self-review

- **Spec coverage (stage 3):** Analyzer as the Retro Dashboard with the full PID table (Tasks 1-3); Handheld single column, scenario dropdown on top, Live | Codes, Live default, 2-up gauges then the full table, Codes unchanged (Task 4); under 600 px opens Handheld, Retro, Live, General, saved choices override, `?example=` (Task 5, ruling 4); transport bar pinned, no horizontal page scroll, table scrolls inside its card (Tasks 4, 6). Retained features: codes and the lamp move to the Dashboard and Handheld (RETAINED updated in Task 3); Clarity moves to the bench row.
- **Stage 2 carry-overs:** the replay-bar overflow in Handheld (Task 6); the deferred minors from stage 2 stay deferred.
- **Type consistency:** `lampModel`/`lampsHtml`/`renderLamps`, `codesPanel`/`renderCodes`, `pickView`, `HB` (the Handheld handle `{g, rows}` built once, like `DB`) are each defined once; Task 4 reuses Task 1's parts; Task 5's `pickView` is the only opener.
- **Known soft spots:** DOM test snippets give the assertions and defer harness idioms (`makeEnv` options such as `hash`, `narrow`, `search`) to what the file actually offers; Tasks 2, 3 and 6 are CSS-heavy and rely on mutation-proofed pytest scope checks plus Neil's screenshot pass, because no agent can render the page.
