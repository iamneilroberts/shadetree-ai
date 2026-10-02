# shadetree-ai

A **read-only** OBD-II diagnostic assistant for DIY mechanics. Plug in an adapter, scan the car into a snapshot, and troubleshoot with Claude using that snapshot plus cited reference material.

> **Status (2026-09-30):** working and tested (701 tests), still early. It can scan a car read-only, replay recorded scans without a car, serve 17 read-only MCP tools to Claude, and show live data in a local web console. The reference store and guided playbooks are not built yet. See [What works today](#what-works-today) and [docs/design.md](docs/design.md).

## Quick start

```
git clone https://github.com/iamneilroberts/shadetree-ai.git && cd shadetree-ai
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

Try it without a car:

```
.venv/bin/python -m obd_reader replay tests/fixtures/synthetic_sedan.jsonl --protocol 6
.venv/bin/python -m obd_reader console --demo
```

With an adapter (OBDLink EX tested; the car parked, ignition on, engine off):

```
.venv/bin/python -m obd_reader scan --port /dev/serial/by-id/<your-adapter> --label my-car
```

`scan` prints VIN, protocol, codes and warnings, and saves `snapshots/<time>-<label>.json` plus the raw `transcripts/<time>-<label>.jsonl`. Both hold the VIN, so they are gitignored.

## What works today

| Area | State | Verified on real hardware |
|---|---|---|
| Read-only command gate (Modes 01, 02, 03, 05, 06, 07, 09, 0A) | done, fuzz-tested | adapter identify commands (OBDLink EX, STN2232) |
| Scan: VIN, protocol, supported PIDs, DTCs, MIL, readiness, freeze frame, multi-ECU union | done | 2024 Honda Ridgeline (CAN 29-bit): VIN, PIDs, DTC modes, readiness |
| Record and replay (snapshot + raw transcript) | done | real Ridgeline transcript replays to the same snapshot |
| 17 MCP tools (9 offline, 8 live) | done | not yet exercised against a car through Claude |
| Live console: Dashboard (default on a desktop; the health tiles and needs-attention list are its General strip; Retro skin on a desktop adds the analyzer cabinet look), Guided test, Handheld (phone; opens by default at 600 px or less), All readings | done, demo tested in a browser (Readings tab: server data checked in demo, page not yet viewed) | sampling runs against the Ridgeline; Handheld and Readings not yet checked on real hardware or a phone |
| All readings table: one row per channel (speed included) with now, min and max (each with when it happened, m:ss into the run), average, standard deviation (sample, Welford), sample count and last-seen age (shows dropouts; in a replay against the replay clock), in the chosen units; whole run in a replay, run so far when live | done, tested (hub stats and page logic, the Ridgeline example replayed through the server); not yet viewed in a browser or on a phone | n/a (computed from the samples) |
| Replay a saved run in the console (play, pause, speed 0.5x-8x, scrubber, restart; pick from `runs/` or upload a file) | done, demo tested in a browser | not yet used on a real saved run |
| Public example runs: `examples/runs/` (committed, no VINs) under **Examples** in the Replay panel, picked by Make, Model, Year; `label-run` writes the label | done, tested (API and page logic); picker not yet viewed in a browser | one real run: a 2024 Ridgeline 6 min drive |
| Dark/light theme button on the console (follows the system setting until you choose; the choice is remembered) | done, tested (page logic: choice order, bad stored value, blocked storage); not yet viewed in a browser | n/a |
| Plain/Retro skin button on the console (Retro is the oxblood look for every view; Retro by default on a phone-width screen, Plain on a desktop; the choice is remembered) and the shared Panel, Gauge (dial, LED bar, seven-segment) and PID-table parts the Dashboard is built from | done, tested (page logic: choice order, bad stored value, blocked storage, gauges for missing readings, table lists; contrast of all four skin/theme colour sets); not yet viewed in a browser | n/a |
| Console Dashboard (default view): scenario tabs (a dropdown on a phone), up to 8 gauges, the full PID table below with the scenario's PIDs marked; five built-in scenarios (General, Fuel trims, Cooling, Idle / misfire, Charging / electrical); pencil edit mode (add from the PIDs in the run, remove, reorder, change form, Reset), saved per scenario in the browser; `--scenarios FILE` adds or replaces shared scenarios | done, tested (page logic, server, scenarios file validation); not yet viewed in a browser | n/a |
| Link straight to an example replay: add `&example=<file>` to the console URL (examples only; a bad name says "Example not found") | done, tested (page logic and server); not yet opened in a browser | n/a |
| Extra readings on the console (car's supported PIDs, up to 16 per run, rotated) and unsupported PIDs dropped | done | 2024 Ridgeline: PID discovery (`0100` to `01A0`, two ECUs) and rotating extra readings sampled (`0104`, `0111`, `010D`, `010E`, `0143`, `0144`); MAF (`0110`) unanswered, MAP (`010B`) used |
| "Capture all supported" option on the console (next to Start sampling and Demo; `capture: "all"` on `/api/start`): every decodable Mode 01 PID the car reports, in two tiers: engine speed, vehicle speed, load and throttle every sweep (2.5 Hz), the rest rotated a few a sweep (about 0.25 Hz each, at most 4 a sweep). Off by default: the normal run is unchanged. Stats on irregularly sampled channels are over the samples actually taken (an average is a mean of those samples, not a time-weighted mean) | done, tested in the simulator (30 supported PIDs; tier counts, save and replay of mixed rates, old run files) | **not verified** on a real adapter: how many PIDs an OBDLink EX (STN2232) sustains at this cadence has to be checked on a car |
| Car identification and learned profile (partial VIN key, per-car list of PIDs that never answer), CAN cars only | done | 2024 Ridgeline: the VIN request (`0902`, one ECU, multi-frame) parsed, the partial key was derived and a profile file was written. A second run that loads the profile (car seen before) has **not** been checked |
| Trouble codes on the console (Modes 03/07/0A + lamp), CAN cars only | done | 2024 Ridgeline (CAN 29/500, two ECUs): Modes 03, 07, 0A and the lamp bit read; the car had no codes and the lamp was off. A car that has codes has **not** been seen yet |
| Mode 06 test results (MCP tool and console Readings tab) | done; reply layout is 9-byte groups `MID TID UASID value min max` | 2024 Ridgeline: 20 MIDs, 53 results, all within limits; values are raw (unit scaling not applied) |
| 29-bit ECU header attribution | written | **not verified** on a real car |
| Legacy protocols (J1850, ISO 9141, KWP) | scanner skips DTC/VIN decode on non-CAN | **not built yet** (needs Austin's older cars) |
| Reference store, DTC lookup, playbooks, `check_citations` | not built | n/a |

## Roadmap

1. Run the console and Mode 06 against the Ridgeline; confirm the 29-bit header parse.
2. Legacy-protocol scans (non-CAN DTC and VIN layouts) on Austin's older cars.
3. Reference store with provenance-tagged records, NHTSA lookups, and the grounding check.
4. Author and review the first playbooks (P0171/P0174, misfire, P0420, charging, parasitic draw).
5. Later: UDS 0x19 read-DTC, phone capture, an in-chat MCP Apps widget for the console.

## Read-only safety promise

- This tool never clears codes, never writes to an ECU, never runs actuator tests, coding, or flashing.
- Enforcement is in code, not in prompts: the transport layer allowlists OBD Modes 01, 02, 03, 05, 06, 07, 09, 0A (plus a short list of adapter identify/config commands) and refuses everything else before any byte reaches the port.
- No MCP tool accepts a raw command string.
- Allowlist behavior is covered by table-driven and fuzz tests (see design doc §5).

## Scope

1996+ US OBD-II cars: J1850 PWM/VPW, ISO 9141-2, KWP2000, CAN. Not OBD-I, Tesla, Mercedes, or secure-gateway vehicles. Use on parked cars only.

## Use with Claude Code (MCP)

The MCP server exposes 17 read-only tools: 9 offline tools that read saved snapshots and 8 live tools that talk to the adapter (including `open_console` and `console_data`, below). Register it with one line (replace the paths; `SHADETREE_HOME` holds `snapshots/` and `transcripts/`, which contain VINs, so keep it out of git):

```
claude mcp add shadetree-ai -e SHADETREE_PORT=/dev/serial/by-id/<your-adapter> -e SHADETREE_HOME=$HOME/shadetree-data -- /path/to/shadetree-ai/.venv/bin/python -m obd_reader.mcp_server
```

Settings (environment variables): `SHADETREE_PORT` (required for live tools), `SHADETREE_BAUD` (default 115200), `SHADETREE_TIMEOUT` (seconds per command, default 10), `SHADETREE_HOME` (default `.`).

Live tools need the car parked with the ignition on. Only one tool can use the adapter at a time; every command sent is recorded in `transcripts/`.

## Live console

A local web page that shows live data as it is sampled, in four views: **Dashboard** (the default on a desktop: scenario gauges, a lamps strip, the trouble codes and the full PID table; its General scenario adds health tiles for fuel trims, coolant, battery, engine load and manifold pressure where its gauges do not already show them, plus a list of anything out of range), **Guided test** (a fuel-trim check with timed captures; the playbook is a draft, unreviewed), **Handheld** (a single-column phone layout with Live and Codes modes, the scenario dropdown shared with the Dashboard, the lamps, two-up gauges and the full PID table; it opens by default on a screen 600 px wide or less, or with `#v5`, e.g. from the laptop in the car and the phone in the mechanic's hand) and **All readings** (every reading in the run with its minimum, maximum, average, standard deviation and sample count). Trouble codes (stored, pending, permanent, and the check-engine lamp) are read once when sampling starts and only on CAN cars; the plain-words meanings are model-drafted and unreviewed. On a desktop the Retro Dashboard is drawn as a 1970s shop-analyzer cabinet (nameplate, rails, LED numerals), and its Clarity button fades the unlit segments for maximum contrast. On a phone the replay controls stay pinned to the bottom of the screen.

```
shadetree-ai console --demo
shadetree-ai console --port /dev/serial/by-id/<your-adapter>
```

`--scenarios FILE` loads shared Dashboard gauge scenarios (JSON, at most 12 scenarios of 1-8 gauges each; format and an example in [docs/design.md](docs/design.md) section 7b).

`--demo` uses a built-in simulated car (healthy, rich or lean) so you can try it without a vehicle. A demo console comes up idle (so an `&example=<file>` link can load its replay); press **Demo** on the page to start the simulated run. With a real adapter the console starts sampling at once unless you pass `--no-start`. The command prints a link like `http://127.0.0.1:8765/?t=<token>`; open it in a browser (`--http-port N` picks another port if 8765 is taken). From Claude, the `open_console` tool starts the same page and `console_data` reads the same numbers.

The console is read-only: it can only start and stop sampling and save a run to `runs/`. It binds to `127.0.0.1`, needs the token in the link, and refuses other `Host` and `Origin` values; the page's one script is pinned by hash in the Content-Security-Policy, and text from the adapter is only ever shown as text.

**Help popups:** every reading, tile and Mode 06 line has a "?" that says what it measures, how to use it and typical values. The wording is ours and unreviewed (the popup says so); the colors on the Overview use general rules of thumb, not limits for your particular car.

**Units:** the **Units** button switches the page between metric and US units (°C/°F, km/h/mph, kPa/psi, g/s to lb/min; manifold and barometric pressure show in inHg). It only changes what is displayed: saved runs, replays and the Overview colors stay metric underneath, and the choice is remembered in the browser.

**Remote access:** start the console with `--allow-host <name>` to accept a public host name served by a tunnel (the console stays on loopback); `scripts/remote_access.py` sets up a Cloudflare Tunnel with a Cloudflare Access email gate and adds or removes friends. See [docs/remote-access.md](docs/remote-access.md).

**Replay:** press **Replay…** in the status bar, pick a saved run from `runs/` (or choose a run file, such as a bundle copied from the laptop) and press Load. The page shows the run as it was sampled: play, pause, speed (0.5x to 8x), drag the scrubber, restart, Exit replay. A replay never touches the adapter and writes nothing; live sampling and Save run are off while one is loaded, and Claude's `console_data` says its numbers are a replay. Runs saved from now on also store the trouble codes, Mode 06 results and the partial car key, so their replays show those too; older runs replay the readings only.

**Car memory:** on CAN cars the console reads the VIN once per run and keeps only a partial key (make, model, engine and year; never the serial) in the "car" chip. It remembers, per key, which readings the car never answers, in `profiles/` (local, gitignored), and stops asking for them sooner next time. A saved profile is a hint, not a fact: a PID that answers is always kept.

**Example runs:** the Replay panel has two sources: **Examples** (public runs committed in `examples/runs/`) and **My runs** (your private `runs/`). Pick a make, then a model, then a year; each list narrows the next, runs without a label sit under "(unlabelled)", and the runs show newest first as time · length · title. To share a run as an example, copy it into `examples/runs/` and label it with `shadetree-ai label-run FILE --make Honda --model Ridgeline --year 2024 --title "Ridgeline 6 min drive"`; see [examples/runs/README.md](examples/runs/README.md) (no VINs, nothing private). A pip install does not ship the examples: use `console --examples-dir PATH`.

**Moving a saved run to another machine:** press **Save run**, then `shadetree-ai export-run` (from the folder you started the console in) writes `shadetree-share.tgz` with the newest run, its transcript and a `SUMMARY.txt` (protocol, codes, lamp, Mode 06 MIDs, per-channel min/mean/max). Use `--latest 3` for more runs. The transcripts can contain the VIN, so copy it with `scp` and never commit it (the bundle name is gitignored).

**On a phone or tablet on the same WiFi:** start it with `--host 0.0.0.0 --allow-lan`. It prints a second link (`console (other devices): http://<your-ip>:<port>/?t=<token>`) to open on the device. Anyone on your network who has that full link can watch live data, so use it only on a network you trust. If the device cannot connect, check the laptop's firewall and that the WiFi does not isolate clients.

While the console samples, other live tools report the adapter as busy and point to `console_data`.

## License

MIT (see [LICENSE](LICENSE)). Reference data pulled in later keeps its own per-record license tag; share-alike or non-commercial data stays out of this repo.

## Grounding

Every diagnostic claim cites a reference record ID or is labeled "general knowledge, unverified".
