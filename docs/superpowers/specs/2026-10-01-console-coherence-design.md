# Console coherence: one dashboard, shared skin, scenarios

Date: 2026-10-01. Status: draft for Neil's review. Source of truth for the console stays `docs/design.md` §7b; update it as each stage merges.

## Goal
Make the console one coherent product instead of five differently styled views (`v0` Overview, `v3` Guided test, `v4` Analyzer cabinet, `v5` Handheld, `v6` All readings). Neil's requests:
- The retro (oxblood) skin works for every view.
- The default view shows the most important indicators as gauges/display panels at the top, and the full PID table below.
- Scenario views: a configurable set of key indicators per scenario, full table below.
- Mobile defaults to the Handheld layout, opening on its live view (not Codes), with the full PID table added.
- Decided with Neil: skip the impeccable skill; all existing features are retained.

## Non-goals
New data capture, Mode 06 sampling changes, any server API other than `--scenarios`, splitting the page into multiple files or adding a framework (the one-file, hash-pinned-CSP design stays).

## Retained features (checklist test per stage)
Capture all supported, Demo button, Save run, replay with the Examples/My runs picker and `?example=`, Mode 06 section, All readings stats (Now, Min, Max, Avg, Std, Samples, last-seen, min/max time), Units, Theme, "?" help popups, codes and the lamp, Guided test, upload, transport bar. Each must stay reachable in the new layout.

## Design

### Stage 1: skin and shared parts (~2-3 h)
- Two skins, **Plain** (today) and **Retro** (oxblood), each with dark and light variants. All colours are CSS variables; the skin is one attribute on `<html>` next to the existing `data-theme`. Header button "Skin: Plain/Retro" beside Theme; choice saved in localStorage (try/catch). Default: Plain on desktop, Retro on phone.
- Shared parts every view builds from: **Panel** (bordered card with a title plate), **Gauge** (forms: dial, bar, 7-segment; input = PID, range, warning zones from the existing watch ranges, so no new data path), **PID table** (today's All readings table as a reusable component taking a PID list).
- No server or data changes.

### Stage 2: Dashboard and scenarios (~4-6 h)
- A **Dashboard** view replaces Overview as the default: up to 8 gauges in a panel on top, the full PID table below. A scenario picker (tabs on desktop, dropdown on phone) switches the indicator set; the table stays full and highlights the scenario's PIDs.
- Built-in scenarios: General (default: RPM, speed, coolant, load, throttle, MAP, battery V, fuel trims), Fuel trims (STFT/LTFT both banks, equivalence ratio, MAP, RPM, load), Cooling (coolant, intake temp, load, RPM, speed, battery V), Idle/misfire (RPM, load, MAP, STFT, timing advance, throttle, battery V), Charging/electrical (control-module V, RPM, load, throttle).
- Configurable: a pencil button puts the gauge panel in edit mode (add/remove from PIDs present in the run or car, reorder, choose gauge form), with Reset to defaults. Edits saved per scenario in the browser.
- JSON defaults: `shadetree-ai console --scenarios FILE` loads shared scenario definitions; server-validated (hex PIDs only, at most 8 gauges, short names, bounded file size). In-page edits layer on top.
- A gauge for a PID not in the run is dimmed with "not in this run"; never a fake zero.
- Overview's health tiles and "needs attention" list move into General as a strip. Guided test stays its own view.

### Stage 3: Retro Analyzer, Handheld, phone (~3-4 h)
- Analyzer stops being a separate page: it is the **Retro skin of the Dashboard on desktop** (cabinet rails, nameplate, lamps around the same panel, tabs and table). Neil (2026-10-01): the cabinet view must include the full All readings details (the PID table with Now/Min/Max/Avg/Std/Samples), not only the meters and lamps.
- Handheld is the phone layout and also a selectable view on desktop, built from the shared parts: single column, scenario dropdown on top, modes **Live | Codes**, opening on **Live** (2-up gauges, then the full PID table); Codes unchanged.
- A viewport under about 600 px opens Handheld, Retro skin, Live, scenario General. Saved skin/theme/scenario choices override these defaults; `?example=` still opens its replay in Handheld.
- Replay on phone: the transport bar stays pinned at the bottom; no horizontal page scroll; the table scrolls inside its card.

## Testing
- Node page test: skin, theme, scenario and edit logic, phone-default selection (pure functions extracted).
- Pytest: `--scenarios FILE` validation (bad PIDs, more than 8 gauges, oversized names, size limit).
- Existing CSP and replay tests stay green. Retained-features checklist per stage.
- Agents cannot see a browser: Neil does a desktop and phone screenshot pass before each merge.

## Risks
1. `console.html` is about 1,190 lines; the refactor could break the single-file hash-pinned CSP. Each stage has a size check and the CSP test.
2. Gauge rendering on real-car data is unverified; gauges use existing watch ranges only.
3. Retro CSS is entangled with the old Analyzer/Handheld markup; stage 1 isolates it into variables first.

## Build plan
Three stages, each in its own worktree: TDD, verified merge, Neil's phone check, then the next stage. Push only on "merge and push".
