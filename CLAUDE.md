# obd-reader

Read-only OBD-II diagnostic assistant. Design: `docs/design.md` (source of truth). Status: design phase — **no production code until the design is approved and Phase 1 starts.**

## Decisions (do not relitigate without a real flaw)
- Users: Austin (older cars, laptop on bench, own Claude subscription) and Neil (2024 Ridgeline, 2023 Highlander — CAN only). Private repo.
- Scope: 1996+ US OBD-II incl. J1850 PWM/VPW, ISO 9141, KWP2000, CAN. No OBD-I, Tesla, Mercedes, secure-gateway cars.
- **Read-only, enforced in code.** Allowlist at the single write point (`transport.py`); only that module imports pyserial. Allowed: Modes 01, 02, 03, 07, 09, 0A (+ explicit AT/STN identify list). Never clear, write, actuate. No tool takes a raw command string.
- v1 front end: MCP server only. Web UI/FastAPI deferred.
- Own thin pyserial ELM/STN transport (not python-OBD: GPL-2.0+, legacy-bus issues). Python 3.11+, pydantic, SQLite, pytest + hypothesis.
- Snapshot-first: every scan records a raw transcript + parsed snapshot JSON; replay drives all tests (no car needed).
- Grounding rule: every diagnostic claim cites `[ref:<record_id>]` or `[general knowledge, unverified]`. Enforced in evals / `check_citations`, not at MCP runtime.
- Reference records carry source, confidence, license. `model_drafted`/`unreviewed` playbooks are labeled as such until Austin reviews.
- Adapter: genuine OBDLink EX (USB). CX has no J1850 — excluded. No cheap ELM327 clones.
- `provenance_unknown` DTC data allowed if tagged (decided 2026-09-28). Austin may read paid sources and rewrite original playbooks (no copying, no automated vendor ingestion).
- Credentialed commercial references (ALLDATA etc.) and Mode 22/OBDb: later phases, opt-in, gitignored cache, `no-redistribute` tag.

## Working rules
- Never claim a scan or tool ran unless it actually ran. No adapter attached → say so and use replay.
- Ask before installing system packages or touching attached hardware.
- Stage files by name; do not commit until Neil says so.
- Snapshots contain VINs: keep local, gitignored (synthetic fixtures excepted).
