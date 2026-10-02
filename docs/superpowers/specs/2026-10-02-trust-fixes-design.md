# Console trust fixes: never show healthy, live or no-codes without the data

Date: 2026-10-02. Status: draft for Neil's review. Source: overlap items 1-6 of `pause-2026-10-02-stage3-merged-stocktake.md` (two UI reviews agree). `docs/design.md` §7b stays the source of truth; update it when this merges.

## Goal
Every colour, word and lamp on the console is backed by data that is present, current and judged by one rule. Missing data says "not available", old data says "not current", playback never says LIVE, an unanswered request never says "no codes".

## Non-goals
New PIDs or scenarios, readiness/freeze-frame views, layout or tap-target work, vehicle identity, ECU attribution, scanner.py (another lane), the transport allowlist.

## 1. One assessment model (page)
`assess(pid)` is the only place a reading is judged. Lamps, gauges, health tiles, Needs attention, the help popup and the summary bar all call it; nothing else holds a threshold.

| State | When | Shown as |
|---|---|---|
| `na` (not available) | PID not in the run, or no sample yet | lamp off "not available"; gauge "not in this run" / "waiting" / "no answer from the car" (PID in `unsupported`) |
| `stale` | the source is not current (stopped, error, lost server), or the reading's newest sample is more than 10 s old on the data clock | last value kept, no colour, "not current" |
| `neutral` | no watch range for the PID, or the help ranges did not load | value, no verdict |
| `ok` / `watch` / `out` | `judge()` on the 10 s median against `stat_help` `watch` (engine-off battery range below 300 rpm, as today) | normal / watch / out of range |

It returns `{s, now, v, m}`: `s` the 10 s state above, `now` the same rule on the latest sample, `v` latest value, `m` the median. Sustained displays (lamps, tiles, attention, summary) use `s`, so a one-sweep spike does not flip them (unchanged). A gauge shows the latest number, so it is coloured by the worse of `s` and `now` and its note names both windows: "10 s: normal", or "now: out of range · 10 s: normal" when they differ.

Lamps lose their hardcoded rules (LTFT ±10 %, coolant < 60 °C): an LTFT lamp is amber for `watch`, red for `out`, off otherwise, with RICH/LEAN by sign. The cold-coolant cue moves into the shared range: `stat_help` coolant `ok` becomes `[60, 105]` (below 60 °C = watch: not warm yet, or a sensor reading cold), so the lamp and the gauge agree. Rule of thumb, Austin to review.

## 2. Unanswered vs unsupported vs empty (hub)
- `_read_codes`: per list (03 stored, 07 pending, 0A permanent) and the MIL (0101), an answer with no codes is an empty list; no answer (NO DATA, negative response, garbled) puts the name in `codes.unanswered` and leaves the list empty; the MIL is `null` when 0101 is unanswered. If none of the three lists answered, `read` is false with a note. Non-CAN stays "not supported yet" (unsupported).
- `_read_mode06`: no supported MIDs reported -> `read: false`, note "the car did not answer Mode 06". MIDs but zero results -> `read: true`, no results.
- Replay keeps `mil: null` and `unanswered`; old files load as before.
- Page: green "0"/"NO CODES STORED" only when every list answered; otherwise "NO ANSWER FOR PENDING CODES" etc. The MIL is ON/off only from a boolean, else "no answer"/"unknown". Mode 06 with no results says "no results" in neutral, never "0 outside limits" green.

## 3. Freshness and connection loss (page)
A failed poll keeps the last state and sets `lost`; it no longer replaces the state with `{status: 'disconnected'}` (which erased the source). A banner (`#lostBanner`, repeated in Handheld's notice line) says which: lost server, adapter error, or sampling stopped, each "showing the last readings, not current". Every reading is then `stale` (section 1). A per-PID dropout is `stale` for that reading only.

## 4. One source/playback state (page + replay)
`source()` derives every status label from one place: kind = Live car / Simulated / Recorded car / Recorded simulation; phase = sampling / stopped / error / idle / playing / paused / ended / lost. The status chip and Handheld header say LIVE only for a live car sampling, SIMULATED/SIM for the demo, REPLAY / REPLAY · PAUSED / REPLAY · ENDED in playback, NOT SAMPLING when idle. The Sampling lamp is lit green only while sampling a car or the simulator, never in playback. A saved demo run already records `demo: true`; `load_run` now keeps it and the replay state carries it, so a replayed simulation is labelled "Recorded simulation".

## 5. Summary bar (Dashboard)
`#d_sum` above the scenario tabs and gauges, in every scenario: source and phase, MIL, distinct code count, readings out of range / to watch (or "No flags in the N readings assessed"), and one next action (e.g. "Review the codes below", "Look at LTFT bank 1 first", "Start sampling for current readings"). The Codes panel is hidden while it has no codes (the bar states why). "Nothing out of range" becomes "No flags in the N readings assessed".

## 6. Gauge labelling
Seven-segment gauges print the unit under the digits. A PID with labels (fuel system status) shows its label, not a number. A `ratio` reading (lambda) shows 2 decimals everywhere (gauge, help), so 0.96 is not 1.0.

## Also
- Guided test: each bank with both captures is classified on its own; a verdict needs every such bank to agree and the 2500 rpm capture to average 2300-2700 rpm; anything else says "Pattern not classified" with the numbers. Captures reset on a new run.
- The unbuilt `[ref:playbook:...]` citations become `[general knowledge, unverified]`; the footer no longer mentions an OUTSIDE tag.

## Tests
TDD: Python (hub codes/Mode 06, replay demo provenance, stat_help range) and `tests/js/page_logic_test.js` (assessment states, lamps agree with gauges, stale after Stop and on poll failure, source labels, summary bar, units on digits, verdict). Tests that pinned the wrong wording are updated on purpose and listed in the merge report. Page budget stays under 130,000 bytes.
