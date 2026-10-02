# Console redesign, stages 1-3 (merged 2026-10-01 to 2026-10-02)

Sources: `git log` (first stage commit d52ddf5, last fix 0ba2107), `docs/superpowers/specs/2026-10-01-console-coherence-design.md`, plans `2026-10-01-console-stage1-skin-and-shared-parts.md`, `2026-10-01-console-stage2-dashboard-and-scenarios.md`, `2026-10-02-console-stage3-cabinet-handheld-phone.md`. Test count after stage 3: 712 passed; `node tests/js/page_logic_test.js src/obd_reader/web/console.html` prints `page logic OK`. The console is still one file, `src/obd_reader/web/console.html`, with a 130,000-byte size budget in `tests/test_console_page.py`. No server routes were added by stage 3.

Not seen on a real adapter or real phone: all of this was checked against the simulator, replays and tests, plus Neil's screenshot passes.

## Stage 1: skin and shared parts (2026-10-01)
- Every colour became a CSS variable (2527d3f); Skin button picks Plain or Retro, each dark and light, via `data-skin` beside `data-theme` (7a2ae35).
- Shared parts built once and reused by every view: Panel, Gauge (dial, LED bar, seven-segment, bands from the help watch ranges), and the PID table rows (0b336a1, 71d1bce, 92f2d60).
- Also that day: Theme button, `?example=` replay links, Capture-all (two-tier sampling), All readings stats (std, sample count, age, min/max time), `console --demo` comes up idle.

## Stage 2: Dashboard and scenarios (2026-10-01)
- Dashboard replaced the Overview tab as the default desktop view (296ce98): scenario tabs (dropdown on a phone), up to 8 gauges, the full PID table. Overview's health tiles and "Needs attention" list survive as the General scenario's strip.
- Five built-in scenarios (General, Fuel trims, Cooling, Idle/misfire, Charging/electrical) live in console.html; `--scenarios FILE` and `GET /api/scenarios` let a file add or override them by id (validated: at most 12 scenarios, 8 gauges, hex PIDs, 32 KB) (0225305, 5d73c20).
- Edit mode (pencil): add, remove, reorder, change form, Reset; saved per scenario in the browser (31373a9).
- Phone Menu button collapses the header and controls at phone width (74f4383).

## Stage 3: cabinet, Handheld, phone defaults (2026-10-01 to 2026-10-02)
- Analyzer view (`#v4`) removed (c7fb35d); its look is the Retro skin of the Dashboard on desktop, with cabinet chrome (rails, nameplate, screws, Clarity rocker) (82dc7d7). A stale `#v4` opens the default view.
- Shared Lamps strip and Codes panel on the Dashboard in both skins (7a497af).
- Handheld rebuilt from the shared parts as Live | Codes, opening on Live; the old Trims and Status modes are gone (c500b3c). A phone (600 px or less) opens Handheld unless the URL names a view (c92dae3); the replay transport bar is pinned to the bottom on a phone (68c0b64).
- Views now: Dashboard, Guided test, Handheld, All readings.
- 2026-10-02 fix pass (369af1f to 0ba2107): round dial labels in every unit, "check engine: ON / off / ?" chip, short gauge titles, thinner dial labels, even PID-table left bars, health strip hides tiles already shown as gauges, "All readings (N)" button in Handheld, per-card ink so Retro dark is readable.

## UI polish pass (2026-10-02, branch worktree-ui-polish)
- Handheld repeats the Dashboard summary bar (`#h_sum`). Guided test captures reset on a new run or simulated scenario. Engine-off battery band now ends at the running high limits (24 V at 0 rpm is out of range). Codes panels say "read at run start, not live". An open help popup keeps its "now" line current.
- Phone Handheld has one scroller (page footer hidden, its caveat inside the frame). 44 px touch targets at 600 px or less and on coarse pointers (`--topbar-h` 57 px). An open Menu leaves room to scroll Handheld's nav above the replay bar. The help dialog takes focus, is `aria-modal` and labelled, and Esc returns focus to its `?`. Page budget is now 150,000 bytes.

## Scenario gaps (2026-10-02, branch worktree-scenario-gaps)
- Readiness monitors and the freeze frame on the console: the hub reads them once per run with the codes (readiness from the same 0101 answer; Mode 02 only when a stored code was read), saved runs store them, old files replay them as "not in this recording". Dashboard panels after Codes; Handheld's Codes pane lists both. The simulator now answers monitor bytes and a Mode 02 frame (rich, lean).
- Richer built-in scenarios: Fuel trims (trims, fuel system status, O2 B1S1 voltage, MAF, rpm), Cooling (coolant, oil, intake, outside air, rpm, load, speed, battery), Idle / misfire (rpm, timing, MAP, load, both STFTs, coolant, throttle); help entries for 03, 10 and 14. Charging and General unchanged. No per-slot fallbacks (a car without MAF shows that gauge as not supported by this car).
- Scenario acquisition: choosing a scenario POSTs its PIDs to `/api/focus`; the hub reads the ones the car's bitmap lists first among its extras (default runs; capture-all unchanged; allowlist unchanged). Gauges and a line under them name PIDs the car does not list ("not supported by this car") or a recording does not hold ("not in this recording").

## Left over
Open phone/Handheld polish (Clarity rocker stays on in Handheld after switching to Plain, lamps wrap at 390 px, replay bar fit at 360 px) and the real-car verification pass are listed in the 2026-10-02 stocktake handoff, not here. `ConsoleService` / MCP `open_console` still cannot pass `--scenarios`.

Still open after the polish pass and scenario gaps (2026-10-02): Clarity rocker below 44 px on the Retro desktop view; no focus trap in the help dialog; fuel trims read "normal" with the engine off (should be neutral); the help "now" line for RPM shows decimals; `#v5` at desktop width loads scrolled down; per-slot fallback PIDs (MAF to MAP, PID 14 to 24), a total-trim value per bank and a Mode 06 misfire summary in Idle / misfire; MCP `console_data` does not expose readiness or the freeze frame; the Terminal skin (GitHub issue #1). Nothing in this file has run on a real adapter.
