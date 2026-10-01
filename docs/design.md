# OBD Diagnostic Assistant — Design (draft 1)

_Status: design of record, updated 2026-09-30. Project name `shadetree-ai` (provisional; import package `obd_reader`, repo dir `obd-reader`). Built so far: Phases 1 and 2, the tool layer and MCP server (Phase 3a), and the live console with its Overview tab, help popups and per-car profiles (§7b). Not built: the reference store and grounding checker (Phase 3b), legacy-protocol decode (Phase 4), playbooks and evals (Phase 5). See the README "What works today" table for hardware-verification status._

## 1. Purpose

A read-only OBD-II assistant for DIY mechanics working on many, often older, cars. A mechanic plugs in an adapter; the system scans the car into a **vehicle snapshot**; Claude troubleshoots conversationally from that snapshot plus **provenance-tagged reference material**.

Primary user: Austin (side-work mechanic, older cars, laptop on a bench near the car, uses Claude Desktop/Code with his own subscription). Builder/owner: Neil (2024 Honda Ridgeline, 2023 Toyota Highlander — both CAN, so they cannot exercise legacy buses).

## 2. Decisions already made

| Decision | Choice |
|---|---|
| Scope | 1996+ US OBD-II: J1850 PWM/VPW, ISO 9141-2, KWP2000, CAN. No OBD-I, no Tesla/Mercedes/secure-gateway cars |
| Safety | Read-only, enforced in code at the transport layer, not in prompts |
| Front end | MCP server (Claude Desktop / Claude Code) plus the local live console (§7b, added 2026-09-30). A chat web UI + FastAPI stays deferred |
| Distribution | Public repo, MIT (changed from private on 2026-09-29). Per-record license tags stay mandatory; share-alike/NC/proprietary reference data must not be committed |
| Depth (v1) | Codes + freeze frame + general reasoning + 4–5 guided playbooks (P0171/P0174, misfire, P0420, charging, parasitic draw), Claude-drafted and Austin-reviewed. Long-term: live-data test procedures (voltage while cranking, etc.) |
| Adapter | OBDLink EX (USB, ~$70) on a USB extension; wireless (LX/MX+) is a later config change |
| Approach | Own thin pyserial ELM/STN transport; snapshot-first; MCP on top |

## 3. Goals and non-goals

**Goals**
- Structurally read-only: no code path can send a mode/command outside the allowlist.
- Every scan is recorded (raw transcript + parsed snapshot) and replayable, so development and tests need no car.
- Every diagnostic claim cites a reference record ID or is labeled `general_knowledge_unverified`; a test can enforce it.
- Legacy-bus cars are first-class (protocol pinned per car, not blindly auto-detected).

**Non-goals (v1)**
- Clearing codes, actuator tests, coding, flashing, any write. Ever.
- Manufacturer-specific PIDs / Mode 22 (later, opt-in, OBDb).
- A chat web UI (the live console is a viewer only), a phone app, a phone-to-laptop relay. (The console can be opened on a phone or tablet on the same WiFi with `--allow-lan`.)
- Credentialed commercial references (ALLDATA/Mitchell/Identifix/OEM) — hypothetical late phase; ToS risk unresolved.
- Diagnosing while driving. The tool is for parked cars.

## 4. Architecture

```
adapter (OBDLink EX, USB)
  └─ transport.py        ONLY module that imports pyserial; allowlist gate on every write; records transcript
      └─ elm.py          ELM/STN session: init, protocol pin, request/response framing, multi-ECU parse
          └─ scanner.py  scan plan → Snapshot (pydantic)
              └─ tools/  scan, read_dtcs, freeze_frame, live_data, lookup_reference, ...
                  └─ mcp_server.py   MCP Python SDK (FastMCP), stdio
reference/  (SQLite store + playbooks YAML) ──> tools/lookup_reference
replay/     fake ELM over pty/in-process, driven by transcripts ──> same transport interface
```

**Stack** (justification in one line each)
- Python 3.11+: official MCP SDK, pyserial, works on Windows/Mac/Linux (Austin's OS unknown).
- pyserial (own transport, not python-OBD): python-OBD is GPL-2.0+, sparsely maintained (last release 2025-04), has open legacy-bus issues (#153, #263), and its command layer makes a hard allowlist awkward.
- pydantic: snapshot schema + exported JSON Schema.
- SQLite (stdlib): reference store. httpx: NHTSA vPIC/recalls/complaints.
- pytest + hypothesis: allowlist fuzzing, replay tests.

**Prior art to read, not fork:** `ayhammouda/obd-mcp-server` (Apache-2.0; read-only core, simulator, 7 tools, no legacy buses yet). Others (`petrpatek`, `iamsyc`) expose `clear_dtc` — explicitly what we do not do.

## 5. Transport allowlist

### 5.1 Allowed traffic
| Layer | Allowed | Grammar |
|---|---|---|
| OBD services | Modes 01, 02, 03, 05, 06, 07, 09, 0A | `01 PP`, `02 PP FF`, `03`, `05 TID SENSOR`, `06 MID`, `07`, `09 PP`, `0A` — hex, exact arg lengths per mode |
| ELM AT | `ATZ ATD ATE0 ATL0 ATS0 ATH0/1 ATSP<0-9> ATTP<0-9> (A-C = J1939 or user CAN: refused) ATDP ATDPN ATRV ATI AT@1 ATCAF1 ATST<hh> ATAT0/1/2 ATSH<hex> ATCRA<hex> ATWS` | explicit list |
| STN read-only | `STI STDI STIX`-style identify commands only | explicit list |
| Later, gated | UDS `19 xx` read-DTC over ISO-TP (own phase, after a real-car test); UDS `22` waits for OBDb | not enabled |

### 5.2 Explicitly refused (non-exhaustive)
Mode 04 (clear DTCs), 08 (control), 0B+, any UDS service other than 19, `ATPP` (programmable-parameter writes), `STPX`/raw-send/other STN write or config-persisting commands, `ATMA` (bus monitor flood), anything not matching the table.

**Stateful-adapter rule (found in Phase 1 review):** `ATCAF0` (CAN auto-formatting off) makes the first hex byte the ISO-TP PCI byte, so an allowed-looking `0104` would go out as a Mode 04 frame. `ATCAF0` is refused; only `ATCAF1` is allowed. Any future AT command that changes how later bytes are framed needs the same scrutiny (the gate is stateless).

### 5.3 Enforcement (defense in depth)
1. **Typed requests.** Scanner code builds `Request(mode, pid)` objects from an enum table; there is no string-building API for callers.
2. **Gate at the only write point.** `Transport.write(cmd)` validates `cmd` against the compiled allowlist grammar and raises `ForbiddenCommand` before touching the port. No other module imports `serial`.
3. **Import boundary test.** A test fails if any module other than `transport.py` imports `serial`/`pyserial`.
4. **No tool exposes raw commands.** MCP tools take PIDs/durations, never command strings. Tool count is a reviewed list (a test asserts the tool-name set).
5. **Rate/size caps.** `live_data`: ≤8 PIDs, ≤120 s, capped poll rate.

### 5.4 Tests
- Table-driven: every allowed form passes; every refused form raises.
- **hypothesis fuzz:** for arbitrary strings, either `ForbiddenCommand` is raised or the string matches the allowlist regex; a spy port asserts nothing else was written.
- Full-scan integration test on the replay transport asserts the set of bytes written ⊆ allowlist.
- Mutation check: temporarily add `04` to the fixtures and confirm the fuzz/table tests fail (proves the gate is actually tested).

## 6. Vehicle snapshot (draft schema)

Two artifacts per scan:
- `transcripts/<id>.jsonl` — raw `{t, tx, rx}` lines (replay source of truth).
- `snapshots/<id>.json` — parsed, versioned:

```jsonc
{
  "schema_version": "0.1",
  "snapshot_id": "2026-09-28T15-04-11Z-ridgeline",
  "captured_at": "2026-09-28T15:04:11Z",
  "source": {
    "kind": "live | replay | import",
    "adapter": {"ati": "...", "sti": "...", "chip": "STN2232", "genuine_stn": true},
    "tool_version": "0.1.0",
    "transcript": "transcripts/<id>.jsonl"
  },
  "vehicle": {
    "vin": "…", "vin_source": "obd | manual | photo | none",
    "decoded": {"make": "…", "model": "…", "year": 2024, "engine": "…",
                "source": "nhtsa_vpic", "error_code": "0"}
  },
  "protocol": {"name": "ISO 15765-4 CAN 11/500", "atsp": "6", "pinned": true},
  "ecus": [{"header": "7E8", "role": "engine", "modes_seen": ["01","03","09"]}],
  "supported_pids": {"01": ["00","04","05"], "09": ["00","02"]},
  "dtcs": {
    "stored":    [{"code": "P0171", "ecu": "7E8", "ref": "dtc:P0171"}],
    "pending":   [],
    "permanent": []
  },
  "mil": {"on": true, "dtc_count": 1},
  "freeze_frame": {"dtc": "P0171", "pids": {"0C": {"name": "rpm", "value": 2150, "unit": "rpm", "raw": "…"}}},
  "readiness": {"misfire": {"supported": true, "complete": true}, "catalyst": {"supported": true, "complete": false}},
  "live_sample": {
    "conditions": {"engine": "idle | 2500rpm | cranking | koeo", "note": "warm, A/C off"},
    "duration_s": 30, "rate_hz": 2,
    "series": {"06": {"name": "stft_b1", "unit": "%", "samples": [[0.0, 1.6], [0.5, 2.3]]}}
  },
  "user_context": {"symptoms": "rough idle when cold", "recent_work": ""},
  "warnings": ["VIN unsupported via Mode 09; entered manually"]
}
```

Rules: unsupported ≠ error (`NO DATA` and negative responses map to `unsupported`); every decoded value keeps its `raw` hex; snapshots contain a VIN, so they stay local and are gitignored except synthetic fixtures.

## 7. MCP tools (defined once, in `tools/`)

All carry `readOnlyHint: true`. No tool accepts a command string.

| Tool | Args | Returns |
|---|---|---|
| `scan` | `protocol?`, `sample_seconds?` (default 0), `symptoms?` | new `snapshot_id` + summary |
| `get_snapshot` / `list_snapshots` | `snapshot_id` | snapshot JSON / index |
| `read_dtcs` | `kind: stored\|pending\|permanent` | DTCs with `ref` record IDs |
| `freeze_frame` | — | freeze-frame block |
| `live_data` | `pids[≤8]`, `seconds≤120`, `conditions?` | series + summary stats (min/max/mean/trend) |
| `decode_vin` | `vin` | vPIC decode + recalls/complaints refs |
| `lookup_reference` | `id` or `query`, `kind?` | records with source/confidence/license |
| `get_playbook` | `id` | structured playbook steps with cites |
| `check_citations` | `answer_text` | valid/invalid `[ref:ID]` tags, uncited-claim report |
| `import_snapshot` | `path` | validates + registers a recorded/imported snapshot |
| `open_console` | `demo?`, `start?` | starts the live console web page (§7b) and returns its local URL |
| `console_data` | `seconds?` | latest values and exact stats from the console's sampler (what the page shows) |

Live mode = same snapshot format with a time series; the tool layer is the same for replay and live.

## 7b. Live console

A local web page for watching live data, built as three parts: a **LiveHub** (one background thread that owns the adapter through the Session lock and gated transport; it samples 8 core Mode 01 PIDs every sweep, rotates extra PIDs the car says it supports a few at a time up to 16 PIDs in all, and on CAN cars reads the trouble codes and lamp bit, the Mode 06 test results and the VIN once per run), a **ConsoleServer** (stdlib HTTP server: one page plus `GET /api/state`, `GET /api/help`, `GET /api/runs`, `POST /api/start`, `/api/stop`, `/api/save`, `/api/sim`, `/api/replay`, `/api/replay/control`), and a single-file page that polls every 400 ms. Claude reads the same buffer through `console_data`, so the human and the model see identical numbers, and the refresh rate never multiplies traffic on the car's bus.

**Page.** Five tabs: *Overview* (the home tab: five health tiles for fuel trims, coolant, battery, engine load and manifold pressure, each with a 60 s sparkline and a state color, plus a "Needs attention" list of readings out of range), *Guided test* (timed idle and 2500 rpm fuel-trim captures; a draft, unreviewed playbook), *Analyzer* (shop-analyzer cabinet), *Handheld* (fixed phone frame) and *All readings* (a compact table, one row per channel in the run, main channels and extras: now, min, max and average, from a `stats` field in the state reply that the hub keeps as running totals; over the run so far when live, over the whole file in a replay, so a seek does not change them; plus the Mode 06 results). The status bar shows the adapter and protocol, the car key, the lamp and the code count. Tile state is judged in the page from each reading's `watch` ranges on the median of the last 10 s, so a brief spike does not flip a tile. A reading the car does not report shows "not reported", a stopped run shows "not sampling", and a failed or slow help fetch says the ranges are not loaded instead of reporting all clear. Tiles with no universal threshold (engine load, manifold pressure) stay neutral. A Units button switches the page between metric and US display (a single conversion table in the page; manifold and barometric pressure in inHg, other pressures in psi); data, saved runs, replays and the `watch` ranges stay metric, the choice is kept in the browser's `localStorage`, and the help text carries both units. Engine off is judged on the low side only, because a hybrid or a start-stop pause charges the battery at 14 V with rpm 0. A page URL may add `&example=<file>` next to `?t=<token>`: the page then replays that public example on load with the same `POST /api/replay` (`source: examples`) the picker uses; the name must pass the server's run-file rule, only `examples/runs/` is addressable this way (never My runs), and a bad or unknown name shows "Example not found" over the normal page.

**Help.** Every tile, attention row, extra reading and Mode 06 group has a "?" that opens a panel: what it measures, how to use it, typical values and the live value. The text comes from `stat_help.py` (`HELP` by PID, `MODE06` by monitor group), served by `GET /api/help` behind the same token, `Host` and `Origin` checks. Wording is ours, tagged `model_drafted` and `unreviewed` (the panel says so) until Austin reviews it; `watch` holds general rules of thumb, never limits for a particular car. Catalog and adapter text reaches the page only through `textContent`. A PID without an entry gets a generic panel. This catalog is also what runbooks (a symptom picks the readings) will read later; runbooks are not built.

**Car memory.** On CAN cars the hub reads the VIN once per run (Mode 09, `0902`) and keeps only a partial key (positions 1-8 and 10: make, model, engine, year; never the check digit or serial). `profiles.py` stores one JSON file per key under `<home>/profiles/` (local, gitignored) with the PIDs that never answered, so the next run drops them after one miss instead of three; a PID that answers is always kept, a corrupt file loads as "no profile", and a failed save never stops a run.

**Replay.** A saved run can be replayed in the page. `replay_run.py` validates a run file as untrusted input (at most 64 readings, 600,000 samples, 24 h and 8 MB; reading ids two hex digits; finite numbers; names at most 80 characters; optional codes, Mode 06 and car-key fields whitelisted) and groups its samples into sweeps by timestamp. The hub plays the sweeps into the same buffers the sampler uses, so the page, the tiles and `console_data` need no special cases; a seek rebuilds the last 60 s and starts a new run id so viewers reset cleanly. A replay never opens the Session or the adapter, writes nothing (no autosave, no Save run) and is exclusive with live sampling. Runs come from two folders, chosen by `source` on `POST /api/replay`: `mine` is `runs/` (private, gitignored) and `examples` is `examples/runs/` in the repo (public, committed; `--examples-dir` points elsewhere, since a wheel does not ship it). Each lists its 50 newest valid files; names must match a strict pattern, be regular files and resolve inside the folder the source names, and any other source value is refused. Runs can also come from an upload held in memory only (8 MB cap on that one route). A run file may carry a `meta` label `{make, model, year, title}` (text at most 40/40/80 printable characters, an integer year 1996-2100, refused if any field holds 17 VIN characters in a row), written by `shadetree-ai label-run`; `load_run` ignores it and a bad label lists as unlabelled. `GET /api/runs` returns `runs` (mine) and `examples`, each entry with its label and a time from the name's UTC stamp (else the file time). The page picks a source, then Make, Model and Year (each narrows the next, "(unlabelled)" last), then a run newest first. A test fails the suite if any file in `examples/runs/` does not load or holds VIN-shaped text or a `vin` field. `console_data` reports `source: replay` with the run name so Claude cannot mistake replayed numbers for the car. Save run now also stores `codes`, `mode06` and `vehicle.key` (the partial key only, never the VIN) so replays of new runs show them.

Rules: the console adds no command (start/stop sampling, save a run file, and load or control a replay only; no route accepts a command string; `/api/help` is read-only data); binds `127.0.0.1` unless `--allow-lan`; every request needs the random token plus an allowed `Host` header, POSTs also check `Origin`; no CORS; bodies capped at 4096 bytes (8 MB on the replay upload route only); request lines are never logged; one run at most 1800 s (default 600 s), 0.1-10 Hz, at most 16 PIDs; a silent bus ends the run after 3 empty sweeps. `console --demo` runs a simulated car behind the same gated transport; it comes up idle (as `--no-start` does for a real adapter), so an `&example=` link can load its replay, and the page's Demo button (shown only on a demo console, hidden while a run is going) starts the simulated run with the chosen `--scenario`. The polling design is deliberately the same as MCP Apps' app-only-tool pattern, so the page can later be wrapped as an in-chat widget.

## 8. Reference store and grounding rule

**SQLite**, one table plus a source table:

```
source(id, name, url, license, redistributable, retrieved_at, notes)
record(id, kind, key, title, body, source_id, confidence, license,
       review_status, reviewer, reviewed_at, supersedes, created_at)
  kind        : dtc_generic | pid | playbook | recall | tsb | complaint | note
  confidence  : authoritative | curated | community | provenance_unknown | model_drafted
  review_status: unreviewed | reviewed | rejected
```

Playbooks are YAML (steps, conditions, tool calls, expected readings, branches, per-step `cites`) compiled into `record` rows. `model_drafted` + `unreviewed` playbooks are labeled as such in every answer until Austin reviews.

**Grounding rule.** Every diagnostic claim in an answer carries `[ref:<record_id>]` or `[general knowledge, unverified]`.
- **Enforceable:** in evals and via `check_citations` — IDs must exist, uncited claims fail, invented PIDs/DTC names fail against the PID/DTC tables.
- **Not hard-enforceable in MCP chat mode:** the server does not control Claude's output. Mitigations: server `instructions` + tool descriptions state the contract, `lookup_reference` results include the citation syntax, and Claude can self-check with `check_citations`. Stated plainly so nobody believes runtime enforcement exists.

**Initial sources and license posture** (research, 2026-09-28; not legal advice)

| Source | License | Use |
|---|---|---|
| SAE J2012 / J1979 text | paid, copyrighted | do not copy |
| fabiovila/OBDIICodes (2,381 DTCs) | MIT, provenance unknown | seed generic DTCs, `provenance_unknown` |
| python-OBD tables | GPL-2.0+ | do not copy (own tables from public facts) |
| Wikipedia OBD-II PIDs | CC BY-SA 4.0 | reference for hand-written PID table |
| NHTSA vPIC / recalls / complaints | US gov, no auth | runtime fetch; check `ErrorCode` (HTTP 200 can carry errors) |
| NHTSA MfrComms.txt (TSB summaries) | public domain | flat-file import, summaries only |
| OBDb | CC-BY-SA-4.0 | later (Mode 22); modern/EV-heavy, weak for older cars |
| iFixit | CC BY-NC-SA | link only |
| ALLDATA/Mitchell/Identifix/OEM | proprietary | not used; see §13 |

## 9. Eval plan

**Cases** (`evals/cases/<id>/`): recorded snapshot (+ transcript), `expected.yaml` with root cause, acceptable alternates, `must_cite` record IDs, `must_not` items (recommends clearing codes to "fix" it, invents a PID, unsupported certainty).

**Sources of cases:** (1) real recordings from Neil's cars (healthy baselines); (2) fault-injected variants on replay (e.g. bias fuel trims to +18% at idle, +4% at 2500 rpm → vacuum leak); (3) Austin's real jobs with known outcomes (highest value; ~5–10 cases).

**Graders**
- Deterministic: all `[ref:]` IDs exist; every claim cited or labeled; every PID/DTC named exists in the tables; no write action suggested.
- Rubric (LLM judge, human spot-check): root cause matches expected or acceptable alternate; recommended next step matches playbook; run ×3 per case.

**Pass bar (initial):** 100% citation validity, 0 invented identifiers, cause-match on ≥80% of cases; tune after first data.

## 10. Phased build order

| # | Phase | Est. | Demo |
|---|---|---|---|
| 0 | Research + hygiene: design doc, README, CLAUDE.md, **data-source landscape deep-dive** (subagent report with sources) | ~1 day | `docs/design.md`; `docs/research/data-sources.md` |
| 1 | Replay core: snapshot schema, allowlist gate, fake ELM transport, fuzz tests | ~2 evenings | `pytest` — forbidden bytes rejected; synthetic snapshot replays |
| 2 | Real scan: EX on Ridgeline + Highlander; transcript recorder | ~1 evening after adapter arrives | real `snapshot.json` + transcript |
| 3 | MCP tools + generic DTC store with provenance + grounding checker | ~1 week of evenings | Claude Code explains a real code, citing record IDs |
| 4 | Austin's old car: legacy protocols, pinned protocol, VIN fallback chain | ~1 evening on-site + fixes | old-car transcript replays in CI |
| 5 | Playbooks + eval harness; `live_data` guided tests; first playbook (P0171) | 2–3 weeks | guided P0171 diagnosis on a recorded case, eval green |
| Later | phone capture/import, credentialed connectors, Mode 22/OBDb, Mode 06, UDS 19, wireless adapter, web UI, C-level playbooks | — | — |

## 11. Top risks (ranked) and cheap experiments

1. **Legacy-bus flakiness on Austin's cars.** _Exp:_ EX on Austin's oldest car, pinned protocol, save raw transcripts (~30 min).
2. **Hallucinated causes/PIDs.** _Exp:_ one playbook (P0171) + 3 recorded snapshots with known causes; run the deterministic graders (~1 evening).
3. **Newer-car gateways (2023–24 Honda/Toyota) block or limit generic reads.** Unverified. _Exp:_ one scan of the Ridgeline (~10 min).
4. **Allowlist bypass** (AT/ST commands, not just modes). _Exp:_ fuzz + spy-port test (~2 h).
5. **Pre-2005 VIN read fails.** No failure-rate data found. Fallback chain: check 0900 bitmap → manual entry → photo of VIN plate → vPIC. Low severity.
6. **Dataset licensing/provenance.** Private repo lowers it; per-record tags keep it visible.
7. **Adapter clones.** Genuine EX only; connect-time identify (`ATI`/`STI`) and refuse-or-warn on non-STN.

## 12. Hardware notes (from research)

- OBDLink EX: USB, **STN2232 v5.12.4 (read from the unit via `STI`, 2026-09-29; the earlier STN2120 claim was from a web page and is wrong for this unit)**, reports `ELM327 v1.4b` to `ATI` and `OBDLink EX r2.7.1` to `STDI`; enumerates on Linux as FTDI `0403:6015` → `/dev/ttyUSB0`, works at 115200 baud first try. Lists J1850 PWM/VPW, ISO 9141, KWP, CAN; no SW-CAN; Windows/Android (no iOS). MS-CAN: the obdlink.com product page lists it, but the OBD Solutions "which adapter" article says it lacks it — sources conflict (irrelevant to generic scans). Linux is not an officially listed platform; verify USB-serial enumeration on arrival (180-day money-back guarantee).
- OBDLink SX ($49.95) also lists PWM/VPW; older chip, no MS-CAN.
- OBDLink CX: BLE only, **no J1850** — excluded. LX/MX+: Bluetooth Classic, `rfcomm`, the wireless upgrade path.
- Cheap ELM327 clones often lack PWM and ISO 9141; many claim v1.5/v2.1 while running v1.4-era code.
- Python-OBD auto-detect order 6,8,1,7,9,2,3,4,5,A; we pin instead.

## 13. Open questions

1. **Mode 05/06 — decided 2026-09-30: enabled.** (Was: add Mode 06?) Read-only per J1979 and very useful (misfire counts, catalyst tests), but outside the decided list. Recommendation: add in Phase 5 behind the same gate. Mode 05 (O2 test results, non-CAN) similar.
2. **UDS 0x19** over ISO-TP: enable in a later phase, needs its own gate rules.
3. **`ATSH`/`ATCRA` allowed** for ECU targeting — constrain to hex values in valid ranges?
4. **Austin's laptop OS** (Windows/Mac/Linux) and how he installs the MCP server.
5. **DTC seed:** fabiovila vs hand-built vs audited Wal33D dataset (claims 9,415 generic entries — unaudited, likely inflated). **Decided 2026-09-28:** `provenance_unknown` DTC data is allowed, always tagged as such.
6. **Playbook review workflow:** who signs off, and what `reviewed` requires (Austin's shop experience is the scarce input). **Decided 2026-09-28:** Austin may read paid/credentialed sources himself and write original playbooks from that knowledge (read-then-rewrite). No copying or automated ingestion of vendor text; his playbooks are tagged `curated`, reviewer Austin.
7. **Credentialed connectors** (voygent `/onboard` method: transport ladder, `legal-policy.mjs` ToS gate, `burn-ledger.mjs`): each user needs their own account; vendor ToS on automation must be an explicit recorded decision; no retention policy exists yet. Late phase, gitignored cache, `no-redistribute` tag.
8. **Phone capture path:** no documented phone-to-laptop relay found; candidates: CSV import from existing phone apps, screenshot + vision, WiCAN Pro pilot (unproven).
9. **Repo name** (see README/chat suggestions).
10. **ELM327-emulator** is CC-BY-NC-SA and has no standalone record/replay: dev-only, not vendored; we build our own replay fake.

## Appendix A — Research status (2026-09-28)

Gathered by subagents from web/GitHub/APIs; **not independently re-verified by the driver**. Key sources: github.com/ayhammouda/obd-mcp-server, github.com/brendan-w/python-OBD, github.com/OBDb, github.com/Ircama/ELM327-emulator, obdlink.com/products, scantool.net/development-tools/obd-chips, vpic.nhtsa.dot.gov/api, www-odi.nhtsa.dot.gov/downloads/flatfiles.cfm, en.wikipedia.org/wiki/OBD-II_PIDs, webstore.ansi.org (SAE J2012/J1979).

**Could not verify:** measured 1996–2004 Mode 09 VIN failure rate; primary CARB/J1979 text for the ~2005 VIN requirement; ELM327-emulator J1850 support; python-OBD `socket://` end to end; chips for MX+/CX/vLinker/Veepeak and their current prices; provenance of every free DTC dataset; vPIC on pre-1981 VINs; NHTSA terms text (403); any Reddit/HN Claude+OBD posts; OBDb pre-2008/non-CAN coverage; STI/AT@1 clone-detection procedure; WiCAN Pro legacy-bus behavior; phone relay apps.
