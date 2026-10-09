# Bus listen: capture broadcast traffic for mapping

Date: 2026-10-08. Status: draft for Neil's review. Source of truth stays `docs/design.md`; update it as this merges.

## Goal
Find out whether each car's OBD port carries broadcast traffic (ECUs talking to each other: wheel speeds, steering angle, brake switch, door state), and capture it alongside known driver actions so it can be mapped later. Priority (Neil, 2026-10-08): capture the maximum amount of data and work through decoding it afterwards. Nothing is discarded at capture time.

Targets: the GMC truck (J1850 VPW), the 2024 Ridgeline (CAN, may be gatewayed) and Dylan's 2015 4Runner (CAN). Neil brings the laptop and the OBDLink EX to each car. All captures stay on his disk.

This is sub-project 1 of 2. Sub-project 2 (its own spec, after real captures exist) is the offline analysis: per ID and byte, what changes inside which action window, counters and checksums filtered out, candidate maps tagged `unverified`, confirmed by a second capture.

## Decisions
- Listen-only monitoring approved by Neil on 2026-10-08 ("Yes listen only"). From the moment monitoring starts until the adapter's prompt returns, nothing is transmitted on the bus.
- Approach A: monitor all IDs, record overflow gaps honestly. Filtered passes (`ATCRA`, already allowed) or a faster adapter baud (`STBR`) only if real captures show heavy drops.
- Markers come from a guided script, not free typing: the tool prompts each action and knows its window.
- CLI first. No console view or MCP tool in this sub-project.

## Gate changes (`allowlist.py`, `transport.py`)
- Allowlist adds `STMA`, `ATMA` (monitor all), `ATCSM1` (CAN silent monitoring on) and `ATAL` (allow long messages, so J1850 frames over 7 data bytes are kept). `ATCSM0` stays refused.
- `ATCAF0` stays refused by `check_command`. The transport allows it only inside `Transport.monitor()`, the stateful rule: while raw mode is on, every command that is not `AT`/`ST` is refused before the port; `ATCAF1` is restored in a `finally` before `monitor()` returns, also on an exception. This is how raw frames are captured by default (with auto-formatting on, the adapter may hide frames that do not look like diagnostic replies [general knowledge, unverified]).
- Silence is checked, not assumed: on a CAN protocol, `monitor()` sends `ATCSM1` first; a `?` reply stops the listen before any monitor command, with the reason. ELM327 v1.4b and later do not ACK in `ATMA` (Linux can327 driver docs); the STN behaviour is unverified until bench step 0. J1850 VPW skips the check (no per-frame ACK in that sense [general knowledge, unverified]).
- Setup uses existing allowed reads only: `ATH1`, `ATS1`, the protocol search `Session.connection` already does (or the quirks-pinned protocol).
- `Transport.monitor(cmd, seconds)` (the transport stays the only module that imports pyserial) streams `(t, line)` pairs instead of reading to the `>` prompt; the monitor command is `STMA` when `STI` answered at identify, else `ATMA`; hard limit `seconds`, at most 900. It stops by sending one CR, and only when no `>` has been seen in the stream (at a prompt a CR repeats the last command). `BUFFER FULL` returns the adapter to the prompt: `monitor()` yields a gap record and re-issues the monitor command until the time is up.
- `SerialPort.write` keeps refusing anything that is not one canonical command; the stop CR goes through a separate, named method on the port used only by `monitor()`.

## Command and guided script
`shadetree-ai listen --port DEV` (`--seconds N` overrides the script length; cap 900), and `shadetree-ai listen --summarize captures/<id>.jsonl` (no adapter).

Flow on each car:
1. Connect and identify: adapter (ATI/STI), protocol, vehicle key (VIN key only, as the console does).
2. Standard-data sweep: the existing `scan(..., mode06=True)` that `probe` runs (raw replies for every advertised Mode 01 PID `pids.py` cannot decode, Mode 09 items, the Mode 06 MID bitmap). The private snapshot is saved as usual; the capture header names it.
3. Guided listen, about 6 minutes, engine running, in Park, parking brake on. Each step shows a prompt and a 10 s countdown, then 5 s of rest. Steps: baseline idle (30 s), brake pedal x3, throttle blips x3, steering lock to lock, left signal, right signal, hazards, headlights, high beams, driver door, windows, HVAC fan, lock/unlock, shifter P-R-N-D with a foot on the brake.
4. Keys: `s` skips a step the car cannot do (recorded as skipped); `q` stops early and keeps the file. The screen shows the step, countdown, live frames per second, distinct IDs and gaps.

The engine is already running because cranking can dip the adapter's supply and reset it. An engine-off pass can be a second run later. The script is a fixed list in code, the same for every car so captures compare; no script files.

## Capture file
`captures/<id>.jsonl` (id style as `probes/`), local, gitignored; `captures/` joins `.gitignore` and the committed-files VIN guard. Setup commands also go into the session's normal raw transcript. JSON Lines, written and flushed as it goes, so a 30-40 MB CAN capture never has to fit in memory and a crash leaves every written line readable:
- header (first line): `schema` 1, tool version, wall-clock start, adapter, protocol, vehicle key, snapshot id, each setup command and its reply, the script (step id, prompt text, window and rest seconds).
- frame: `{t, raw}`, the adapter line exactly as received; `t` is seconds since start on `time.monotonic`.
- step: `{t, step, phase}` with phase `start`, `end` or `skipped`.
- gap: `{t, gap, seconds}` for `BUFFER FULL`, a monitor restart, or an adapter that stopped answering.
- end: why it stopped (`finished`, `quit`, `time_limit`, `error`) and totals.

Summary, printed and written as `captures/<id>.md` (and by `--summarize` from any capture, partial ones included): frame count, gap seconds, then one row per message ID with frames, rate in Hz, data length, the number of byte positions that ever changed, and the steps during which it changed most (the up to three step windows holding the most payload changes for that ID, rest periods excluded). The summary never contains payload bytes, so a VIN some car broadcasts cannot leak through it; payloads stay in the `.jsonl` for sub-project 2.

## Testing (no car needed)
- `test_allowlist.py`: the four new commands pass; `ATCSM0` and plain `ATCAF0` are refused; hypothesis: while raw mode is on, every non-AT/ST string is refused before the port, and CAF1 is restored when `monitor()` raises.
- `monitor()` against a scripted fake port: timestamped streaming, the time limit, the stop CR only when no `>` was seen, `BUFFER FULL` gives a gap record and a restart, `?` to `ATCSM1` stops a CAN listen before any monitor command.
- `SimPort` gets a monitor mode streaming made-up CAN 11-bit and J1850 VPW broadcast frames (invented IDs, no VIN), so `listen --port sim` runs end to end in tests and as a demo.
- Script runner on a fake clock: order, 10 s / 5 s timing, `s` and `q`.
- Capture and summary: a file truncated mid-line still summarizes; the summary of a capture holding a VIN-shaped string as hex payload contains no payload bytes and `find_vins` finds nothing.

## Hardware steps (Neil)
0. Bench, OBDLink EX, no car (~10 min): replies to `ATCSM1`, `STMA` vs `ATMA`, `ATCAF0`. No VIN on a bench, so the transcript can become a test fixture. If `ATCSM1` is refused, CAN listening stays off until we decide.
1. GMC truck, Ridgeline, 4Runner (~10 min each): `listen`, then `--summarize`.

## Out of scope here
Decoding and mapping (sub-project 2); filtered passes and `STBR`; driving captures; engine-off and cranking captures; sharing captures off this machine (VIN scrubbing); console or MCP access; UDS and Mode 22.

## Not verified
STN silent monitoring and `STMA` output format; whether `ATCAF1` hides broadcast frames; J1850 monitoring on the OBDLink EX; whether the 2024 Ridgeline's port carries any broadcast traffic (gateway); serial throughput on a busy 500 kbps bus.
