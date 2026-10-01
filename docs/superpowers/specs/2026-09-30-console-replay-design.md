# Console Replay Mode

Status: draft for review, 2026-09-30. Design agreed section by section in chat the same day.

## Goal

Replay a saved run in the console UI, with play, pause, speed, a scrubber and restart, so a drive can be re-examined on the Overview, Analyzer, Handheld, Guided test and All readings tabs without a car. Replay never touches the adapter.

## Decisions already made

- Replay is a second source inside the hub (not a separate hub, not a rebuilt ELM stream).
- Runs come from a dropdown of `runs/` and from an in-memory upload. No CLI flag.
- Save run also stores trouble codes, Mode 06 results and the partial car key, so replays of future runs show them. Old files keep working.
- Save run stays disabled during replay.
- Out of scope: looping, frame step, keyboard transport shortcuts, writing an uploaded run to disk.

## Run file (existing, plus optional fields)

`{"kind": "live_run", "demo": bool, "adapter": {...}, "live_sample": {"duration_s": float, "rate_hz": float, "series": {"<PID>": {"name": str, "unit": str|null, "samples": [[t, v], ...]}}}}`. All readings in one sweep share a timestamp, so sweeps are rebuilt by grouping samples on `t`. New optional keys written by Save run: `codes` (same shape as `state.codes`), `mode06` (same shape as `state.mode06`), `vehicle` (`{"key": str}` only; never the VIN, serial or check digit).

## Components

- **`src/obd_reader/replay_run.py`** (pure, no threads): `load_run(obj) -> Run` validates and normalises an untrusted object; `Run.duration`, `Run.sweeps` (list of `(t, {pid: value})` sorted by `t`), `Run.window(pos, span)` returns the sweeps in `[pos - span, pos]`. `list_runs(runs_dir) -> list[dict]` returns the 50 newest valid files as `{name, size, duration}`; `read_run_file(runs_dir, name)` opens one by name.
- **`LiveHub` replay mode** (`hub.py`): `start_replay(run, name)`, `replay_control(action, pos=None, speed=None)`, `exit_replay()`. A player thread advances a position by `dt * speed` and publishes every sweep with `t <= pos` into the same buffers the sampler uses. Any seek rebuilds from scratch: reset buffers, bump the run id, publish `Run.window(pos, 60)`, so the page resets cleanly.
- **`ConsoleServer` routes** (`console.py`): `GET /api/runs`, `POST /api/replay` (body `{"name": "<file>"}` or `{"run": {...}}`), `POST /api/replay/control` (body `{"action": "play|pause|seek|speed|restart|exit", "pos": s, "speed": x}`). The upload route has an 8 MB body cap; every other route keeps `MAX_BODY` (4096).
- **Page** (`web/console.html`): Replay button and panel, transport bar, banner, disabled controls, all driven by `state.replay`.

## Hub behavior

- `state()` gains `replay: null | {name, duration, pos, speed, playing, ended}`. While a replay is loaded `status` is `running` (so tiles stay lit when paused), `demo` is false, `now` is the replay position, `seconds_left` is null, and `codes`, `mode06` and `vehicle` come from the file when present, otherwise `codes = {read: false, note: "not stored in this run"}`.
- At the end of the run playback stops (`ended: true`, position at the end); play from the end restarts at 0.
- **Exclusion:** `start_replay` raises `HubBusy` while live sampling runs; live `start` raises `HubBusy` while a replay is loaded; `exit_replay` clears the buffers and returns to idle.
- **No disk writes:** `_autosave_run` and `save_run` do nothing or refuse (`ValueError("a replay cannot be saved")`) while a replay is loaded. Replay never opens the Session, the transport or the adapter.
- **Source label:** `tools.console_data` adds `"source": "replay"` (with the run name) or `"live"`; the page banner says `Replay: <name> · not a live car`.

## Validation and limits (`load_run`)

`kind == "live_run"`; `live_sample.series` is an object of at most 64 readings; keys match `[0-9A-F]{2}`; `name` and `unit` are strings of at most 80 characters (unit may be null); samples are `[t, v]` pairs of finite numbers with `t >= 0`, at most 600,000 in total; duration (largest `t`) at most 86,400 s; at least one sample. Optional `codes`, `mode06`, `vehicle` are whitelisted field by field with type checks and length caps (at most 64 codes, 400 Mode 06 results, key matching the profile key pattern); anything else is dropped. Failure raises `ValueError` with a plain message that the route returns as 400.

`list_runs` and `read_run_file` accept only names matching `[A-Za-z0-9T:_.-]{1,100}\.json`, regular files (no symlink) that resolve inside `runs/`, at most 8 MB. Unreadable or invalid files are skipped from the list. Unknown name: 404. Over-cap upload: 413. Every route keeps the token, `Host` and `Origin` checks, and none accepts a command string.

## Page behavior

- **Replay button** (status bar, next to Start sampling) opens a panel: a dropdown of saved runs (`2026-09-30 21:32 · drive-rebuilt · 6:10`) with Load, and a Choose file input (client rejects files over 8 MB with a message before sending; the file is read with `file.text()` and posted as `{"run": ...}`). Load errors show as one line in the panel. Loading starts playback at 1x.
- **While replaying:** amber banner; transport bar with restart, play/pause, speed menu (0.5, 1, 2, 4, 8), scrubber with `m:ss / m:ss`, Exit replay. The scrubber label updates while dragging, the seek is sent on release, and the thumb ignores incoming state during a drag. Start sampling, Save run and the simulator controls are disabled.
- All run, file and adapter text reaches the DOM through `textContent`. Phone width: buttons and speed menu on one row, scrubber on its own full-width row.

## Files

- Create `src/obd_reader/replay_run.py`, `tests/test_replay_run.py`.
- Modify `src/obd_reader/hub.py`, `src/obd_reader/console.py`, `src/obd_reader/tools.py`, `src/obd_reader/web/console.html`, `README.md`, `docs/design.md`.
- Tests: additions to `tests/test_hub.py`, `tests/test_console.py`, `tests/test_console_page.py`, `tests/js/page_logic_test.js`.

## Build order (each step leaves the console working)

1. `replay_run.py` with tests (~1.5 h).
2. Hub replay mode and exclusion rules (~2 h).
3. Server routes and the per-route size cap, plus `console_data` source (~1.5 h).
4. Page: panel, transport bar, banner, disabled controls (~2.5 h).
5. Save run stores codes, Mode 06 and the key; replay shows them (~1 h).
6. README and `docs/design.md` (~30 min).

## Testing

- **`replay_run`:** a good file loads; wrong kind, bad reading key, NaN or infinite value, too many samples or readings, over-long names, empty series, and traversal or symlink names are rejected; sweeps group by `t`; `window` returns the right slice; optional fields are whitelisted and capped.
- **Hub:** seq grows while playing and holds while paused; speed changes the rate; a backward seek bumps the run id and restarts seq; play from the end restarts; live start during replay and replay during live sampling both raise `HubBusy`; no file appears in `runs/` after a replay ends; `save_run` is refused; `state` shows codes and key from the file and the "not stored" note otherwise.
- **Server:** `GET /api/runs` lists only valid names; load by name; upload accepted and an over-cap upload gets 413; a bad name gets 400 or 404; all routes need the token and refuse a bad `Host` or `Origin`; other routes still reject a body over 4096.
- **Save run:** the written file contains `codes`, `mode06` and `vehicle.key`, and no 17-character VIN-shaped text.
- **Node page tests:** banner, scrubber, play/pause label and speed menu render from `state.replay`; controls post the right endpoint and body; Start and Save are disabled; a hostile run name renders as text; the picker lists runs; a fake uploaded file is posted; an oversize file is refused client-side.

## Risks

- The page polls `/api/state` with `after`; seeking republishes only the last 60 s, so sparklines and the 10 s windows have what they need but the Guided test's capture state is reset by the run-id bump.
- An upload is held in memory (at most 8 MB of JSON, roughly 600,000 samples). One replay at a time.
- Claude's `console_data` can read replayed numbers; the `source` field is the guard, and its docstring says to check it.
