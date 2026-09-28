# obd-reader (working name)

A **read-only** OBD-II diagnostic assistant for DIY mechanics. Plug in an adapter, scan the car into a snapshot, and troubleshoot with Claude using that snapshot plus cited reference material.

> **Status:** design phase. No production code yet. See [docs/design.md](docs/design.md).

## Read-only safety promise

- This tool never clears codes, never writes to an ECU, never runs actuator tests, coding, or flashing.
- Enforcement is in code, not in prompts: the transport layer allowlists OBD Modes 01, 02, 03, 07, 09, 0A (plus a short list of adapter identify/config commands) and refuses everything else before any byte reaches the port.
- No MCP tool accepts a raw command string.
- Allowlist behavior is covered by table-driven and fuzz tests (see design doc §5).

## Scope

1996+ US OBD-II cars: J1850 PWM/VPW, ISO 9141-2, KWP2000, CAN. Not OBD-I, Tesla, Mercedes, or secure-gateway vehicles. Use on parked cars only.

## Grounding

Every diagnostic claim cites a reference record ID or is labeled "general knowledge, unverified".
