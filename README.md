# shadetree-ai

A **read-only** OBD-II diagnostic assistant for DIY mechanics. Plug in an adapter, scan the car into a snapshot, and troubleshoot with Claude using that snapshot plus cited reference material.

> **Status (2026-09-30):** working and tested (439 tests), still early. It can scan a car read-only, replay recorded scans without a car, serve 17 read-only MCP tools to Claude, and show live data in a local web console. The reference store and guided playbooks are not built yet. See [What works today](#what-works-today) and [docs/design.md](docs/design.md).

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
| Live console: Cockpit, Scope, Guided test, Analyzer cabinet, Handheld (phone), Readings | done, demo tested in a browser (Readings tab: server data checked in demo, page not yet viewed) | sampling runs against the Ridgeline; Analyzer, Handheld and Readings not yet checked on real hardware or a phone |
| Extra readings on the console (car's supported PIDs, up to 16 per run, rotated) and unsupported PIDs dropped | done | 2024 Ridgeline: PID discovery (`0100` to `01A0`, two ECUs) and rotating extra readings sampled (`0104`, `0111`, `010D`, `010E`, `0143`, `0144`); MAF (`0110`) unanswered, MAP (`010B`) used |
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

A local web page that shows live data as it is sampled, in five layouts: **A Cockpit** (gauges and trim bars), **B Scope** (stacked strip charts with a hover cursor), **C Guided test** (a fuel-trim check with timed captures; the playbook is a draft, unreviewed), **D Analyzer** (a 1970s shop-analyzer cabinet with LED numerals, trim bars, lamps, and the trouble codes up top) and **E Handheld** (the same readouts in a fixed-size phone frame with Codes, Live, Trims and Status modes; open it with `#v5`, e.g. from the laptop in the car and the phone in the mechanic's hand). Trouble codes (stored, pending, permanent, and the check-engine lamp) are read once when sampling starts and only on CAN cars; the plain-words meanings are model-drafted and unreviewed. The Clarity button fades the unlit segments for maximum contrast.

```
shadetree-ai console --demo
shadetree-ai console --port /dev/serial/by-id/<your-adapter>
```

`--demo` uses a built-in simulated car (healthy, rich or lean) so you can try it without a vehicle. The command prints a link like `http://127.0.0.1:8765/?t=<token>`; open it in a browser (`--http-port N` picks another port if 8765 is taken). From Claude, the `open_console` tool starts the same page and `console_data` reads the same numbers.

The console is read-only: it can only start and stop sampling and save a run to `runs/`. It binds to `127.0.0.1`, needs the token in the link, and refuses other `Host` and `Origin` values; the page's one script is pinned by hash in the Content-Security-Policy, and text from the adapter is only ever shown as text.

**On a phone or tablet on the same WiFi:** start it with `--host 0.0.0.0 --allow-lan`. It prints a second link (`console (other devices): http://<your-ip>:<port>/?t=<token>`) to open on the device. Anyone on your network who has that full link can watch live data, so use it only on a network you trust. If the device cannot connect, check the laptop's firewall and that the WiFi does not isolate clients.

While the console samples, other live tools report the adapter as busy and point to `console_data`.

## License

MIT (see [LICENSE](LICENSE)). Reference data pulled in later keeps its own per-record license tag; share-alike or non-commercial data stays out of this repo.

## Grounding

Every diagnostic claim cites a reference record ID or is labeled "general knowledge, unverified".
