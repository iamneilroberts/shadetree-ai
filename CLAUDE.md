# shadetree-ai

Name chosen 2026-09-28 (provisional). PyPI dist/CLI: `shadetree-ai`; Python import package stays `obd_reader` for now; repo directory is still `obd-reader`.

Read-only OBD-II diagnostic assistant. Design: `docs/design.md` (source of truth). Status (2026-10-04): Phases 1–3a, the live console (Dashboard + scenarios, Retro cabinet skin, Handheld, replay, help popups, profiles; stages 1–3), the trust fixes (one `assess()`, source states), the `probe` command with its VIN-free report, reply classes, Honda DTC hints, the UI polish pass and scenario gaps (readiness, freeze frame, scenario PID requests via `POST /api/focus`) are built and merged, as are the 1970s cabinet skin (desktop and phone), the Options drawer, Capture level min/std/max, the Terminal view (`#v7`) and legacy-bus decoding (J1850, ISO 9141, KWP; tested on one J1850 VPW GMC truck) (843 tests, main pushed at `21a8de3`). See `docs/summaries/console-stages-1-3.md` and `docs/superpowers/specs/2026-10-02-probe-design.md`. Not built: reference store, playbooks, quirks file (probe step 4), legacy Mode 09 CAL ID/CVN/ECU name. Console page budget is 260,000 bytes (`tests/test_console_page.py`; the page is about 250,000 with three embedded OFL fonts). Hardware-verified only on the OBDLink EX bench and one 2024 Ridgeline scan; Mode 06, 29-bit ECU headers, legacy ECU source-address parsing, the new Mode 09/ATRV/STDI reads, reply classification, Mode 02 and readiness on the console, and the console on a real adapter are still unverified. See README "What works today".

## Decisions (do not relitigate without a real flaw)
- Users: a tester with older cars (laptop on the bench, own Claude subscription) and the maintainer (CAN-only cars). **Public repo, MIT** (github.com/iamneilroberts/shadetree-ai, made public 2026-09-29): never commit real snapshots/transcripts (VINs), secrets, or share-alike/NC/proprietary data.
- Scope: 1996+ US OBD-II incl. J1850 PWM/VPW, ISO 9141, KWP2000, CAN. No OBD-I, Tesla, Mercedes, secure-gateway cars.
- **Read-only, enforced in code.** Allowlist at the single write point (`transport.py`); only that module imports pyserial. Allowed: Modes 01, 02, 03, 05, 06, 07, 09, 0A (+ explicit AT/STN identify list; 05/06 approved 2026-09-30). UDS 0x19 later, 0x22 not before OBDb. Never clear, write, actuate. No tool takes a raw command string.
- Front ends: the MCP server (17 read-only tools) and a local read-only live console (stdlib HTTP server + one-file page, `shadetree-ai console`; token, Host/Origin checks, hash-pinned CSP). A chat web UI/FastAPI app stays deferred; an in-chat MCP Apps widget is a possible later wrapper of the console page.
- Own thin pyserial ELM/STN transport (not python-OBD: GPL-2.0+, legacy-bus issues). Python 3.11+, pydantic, SQLite, pytest + hypothesis.
- Snapshot-first: every scan records a raw transcript + parsed snapshot JSON; replay drives all tests (no car needed).
- Grounding rule: every diagnostic claim cites `[ref:<record_id>]` or `[general knowledge, unverified]`. Enforced in evals / `check_citations`, not at MCP runtime.
- Reference records carry source, confidence, license. `model_drafted`/`unreviewed` playbooks are labeled as such until the tester reviews.
- Adapter: genuine OBDLink EX (USB). CX has no J1850 — excluded. No cheap ELM327 clones.
- `provenance_unknown` DTC data allowed if tagged (decided 2026-09-28). The tester may read paid sources and rewrite original playbooks (no copying, no automated vendor ingestion).
- Credentialed commercial references (ALLDATA etc.) and Mode 22/OBDb: later phases, opt-in, gitignored cache, `no-redistribute` tag.

## Working rules
- Never claim a scan or tool ran unless it actually ran. No adapter attached → say so and use replay.
- Ask before installing system packages or touching attached hardware.
- Stage files by name; do not commit until the maintainer says so.
- Snapshots contain VINs: keep local, gitignored (synthetic fixtures excepted).
- Mockups: never publish design mockups as Artifacts. Build one self-contained HTML file (inline CSS/JS, example data only) and host it on a `fuxed.org` subdomain. The voygent-lite `/mock` skill (`~/dev/voygent-lite/.claude/skills/mock`) is the pattern, but its deploy script targets voygent.ai, so it needs a fuxed.org target first.
