# Console Overview and Help Popups

Status: draft for review, 2026-09-30. Mock approved: `docs/mocks/overview.html`.

## Goal

Open the console and see, in one screen, whether anything about the car needs attention, with a plain-language "?" on every statistic saying what it measures and how to use it. Replace the early-mock tabs that duplicate each other. Runbooks (symptom picks the readings) are a later layer and are not built here.

## Decisions already made

- Ranked dashboard first; runbooks later (chosen 2026-09-30).
- One shared help catalog, reusable by runbooks later.
- Help wording is our own, tagged `model_drafted` / `unreviewed` until Austin reviews it.
- Remove extraneous "read-only" messaging from the page (user request 2026-09-30). Read-only stays enforced in code (`transport.py` allowlist, no write routes); only the page text goes.

## Scope

In:
1. New Overview tab (home): status strip, five health tiles, "Needs attention" list, link to All readings.
2. `src/obd_reader/stat_help.py`: the help catalog. `GET /api/help` serves it.
3. "?" popup on Overview tiles and rows, the Readings tab (extras) and Mode 06 lines.
4. Retire Cockpit (A) and Scope (B). Keep Guided test (C), Analyzer (D), Handheld (E); rename Readings (F) to "All readings".
5. Remove the READ-ONLY chip, the header subtitle, the footer paragraph and the "cannot send commands" / "read-only" wording on the Analyzer and Handheld pages. Keep the amber demo banner only when the data is simulated.

Out: runbooks, curated per-model thresholds, Mode 06 unit scaling, new PIDs, any change to hub, transport or allowlist.

## Overview screen

- **Status strip:** live state, car chip (existing), protocol, lamp, codes ("none stored", "N stored", or "not read" with the existing note). Save run and Start/Stop sampling stay here.
- **Five tiles:** Fuel trims (all four trims in one tile, big number is the trim furthest from zero, subtitle names which one), Coolant (`05`), Battery (`42`), Engine load (`04`), Manifold pressure (`0B`). Each has a value, a 60 s sparkline and a state border.
- **Tile state** is computed in the page from the catalog's `watch` ranges on the median of the last 10 s, so a brief throttle spike does not flip a tile. States: normal, watch, out of range, neutral (no universal threshold), and no data.
- **Needs attention:** one row per reading whose state is watch or out of range, worst first: name, value, the catalog's one-line meaning, a "?". With nothing out of range it says "Nothing out of range".
- **Honest states:** a reading not reported by the car shows "not reported", never a normal color. Engine load is an extra that rotates in, so its tile shows "last seen N s ago" when the newest sample is older than 3 sweeps. Not sampling: tiles greyed and labeled "not sampling".
- Deliberate change from the mock: Engine load and Manifold pressure have no universal threshold (they depend on engine and altitude), so their border is neutral, not green.

## Help catalog

`stat_help.py` holds `HELP: dict[str, dict]` keyed by PID string (`"06"`) plus `MODE06: dict[str, dict]` keyed by monitor group. Each entry:

| field | meaning |
|---|---|
| `title` | plain name |
| `measures` | one sentence |
| `use` | 2-3 short bullets |
| `typical` | typical healthy range in words |
| `watch` | optional `{"ok": [lo, hi], "out": [lo, hi]}`; inside `ok` is normal, outside `ok` but inside `out` is watch, outside `out` is out of range |
| `status` | `"model_drafted"`, `"unreviewed"` |

Entries are written for the ~25 readings the console shows or rotates. A PID with no entry gets a generic popup ("no bundled help for this reading"), so nothing breaks. `watch` contains only general rules of thumb: trims ok ±10, out beyond ±20; running battery voltage ok 13.2-14.8, out below 11.5 or above 15.5 (engine off uses 12.2-12.9 ok, decided from rpm = 0); coolant high side only (ok up to 105, out above 112). No model-specific limits are invented.

`GET /api/help` returns `{"pids": {...}, "mode06": {...}}` as JSON. It follows the existing GET pattern: token, Host and Origin checks, no POST variant. The page fetches it once at load; if it fails the "?" buttons show the generic popup. The hash-pinned CSP is unchanged (still one script block).

## Popup behavior

A "?" button next to every tile, row and reading. Click or tap opens one panel; a second click, Escape or a click outside closes it; only one is open at a time. The panel has: title, "What it measures", "How to use it", "Typical / worry if", a live line ("now 3.1 %: watch") and the "wording not yet reviewed" line. Keyboard reachable. All catalog text is set with `textContent`, never markup.

## Files

- Create `src/obd_reader/stat_help.py`.
- Modify `src/obd_reader/console.py` (one GET route), `src/obd_reader/web/console.html` (Overview tab, popup, tab changes, text removal).
- Tests: new `tests/test_stat_help.py`; additions to the console server tests and `tests/js/page_logic_test.js`; `tests/test_console_page.py` element-id list updated.
- `README.md`: one paragraph.
- `docs/mocks/overview.html` stays as the design record.

## Build order (each step leaves the console working)

1. Catalog and `/api/help` plus Python tests.
2. Popup component on the existing Readings tab and Mode 06 plus Node tests.
3. Overview tab, tile state and the attention list plus Node tests.
4. Retire Cockpit and Scope, remove the extraneous text, update README, check in a browser.

## Testing

- Python: every PID the console displays (`DEFAULT_PIDS` plus `EXTRA_PIDS`) has a catalog entry with all fields and a well-formed `watch` (`ok` inside `out`). `/api/help` needs the token, rejects a bad Host/Origin, has no POST variant, and its JSON contains no 17-character VIN pattern.
- Node fake DOM: a hostile catalog string renders as text; tile state follows `watch` (normal, watch, out) using the median window; a missing reading shows "not reported"; a rotating extra older than 3 sweeps shows "last seen"; an empty attention list says so; Escape and outside-click close the popup; one popup open at a time.
- Existing tests that reference Cockpit/Scope element ids (7 references in `page_logic_test.js`) move to the Overview ids or are removed with the tabs. No test is deleted without its behavior being covered elsewhere.
- Manual: view in a browser at laptop and phone width against `console --demo`.

## Risks

- Retiring Cockpit/Scope touches the page script shared by all tabs (channel buffers, sparklines, gauges). Mitigation: step 4 is last, after the Overview works; the shared `CH` buffers stay.
- Help wording can be wrong or overconfident. Mitigation: the `unreviewed` tag is always visible, `watch` is general-rule only, and Austin reviews before the tag is removed.
- The 10 s median needs the sample buffer the page already keeps; if a run is shorter than 10 s the tile uses what exists.
