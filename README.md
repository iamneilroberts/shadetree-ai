# shadetree-ai

A **read-only** OBD-II diagnostic assistant for DIY mechanics. Plug in an adapter, scan the car into a snapshot, and troubleshoot with Claude using that snapshot plus cited reference material.

> **Status:** design phase. No production code yet. See [docs/design.md](docs/design.md).

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

A local web page that shows live data as it is sampled, in three layouts: **A Cockpit** (gauges and trim bars), **B Scope** (stacked strip charts with a hover cursor) and **C Guided test** (a fuel-trim check with timed captures; the playbook is a draft, unreviewed).

```
shadetree-ai console --demo
shadetree-ai console --port /dev/serial/by-id/<your-adapter>
```

`--demo` uses a built-in simulated car (healthy, rich or lean) so you can try it without a vehicle. The command prints a link like `http://127.0.0.1:8765/?t=<token>`; open it in a browser. From Claude, the `open_console` tool starts the same page and `console_data` reads the same numbers.

The console is read-only: it can only start and stop sampling and save a run to `runs/`. It binds to `127.0.0.1`, needs the token in the link, and refuses other `Host` and `Origin` values. To view it on a tablet on your shop WiFi, bind the laptop's address explicitly: `--host <laptop-ip> --allow-lan` (anyone with the link can then watch live data). While the console samples, other live tools report the adapter as busy and point to `console_data`.

## License

MIT (see [LICENSE](LICENSE)). Reference data pulled in later keeps its own per-record license tag; share-alike or non-commercial data stays out of this repo.

## Grounding

Every diagnostic claim cites a reference record ID or is labeled "general knowledge, unverified".
