# Probe and vehicle-variation structure

Date: 2026-10-02. Status: draft for Neil's review. Source of truth stays `docs/design.md`; update it as each step merges.

## Goal
Point the tool at a car it has never seen (Neil's Ridgeline and Highlander, Austin's older cars) and come away with a record of what that car supports, how it answers, and how it differs from other cars. Neil should be able to share that record without sharing the VIN. All of it stays read-only: Modes 01-0A plus the AT/STN identify list. No allowlist change is needed for anything below.

## Done in step 1 (this branch)
- `scan()` now reads Mode 09 `0904` (CAL ID), `0906` (CVN) and `090A` (ECU name), but only the ones the `0900` bitmap advertises, and only on CAN (the same gate as the VIN). Results go into `Snapshot.mode09` {cal_ids, cvns, ecu_names}: one union list per item across all ECUs, first-seen order, not attributed to an ECU because headers are off. Advertised items that get no usable reply produce one warning.
- `scan()` reads `ATRV` and stores it as `Adapter.supply_voltage`. On a genuine STN it also reads `STDI` and stores it as `Adapter.device`. Both are optional fields, so older snapshots still load. `vehicle_info` and the CLI `scan` summary show them.
- Every console run file now has `"transcript": "transcripts/<stamp>-console.jsonl"`, a path relative to the data home, so a run can be traced back to its raw replies. (The hub.py change is about 5 lines in `_reset`, `_run` and `_write_run`; `Transport.transcript_path` exposes the recorder's path.)

## What the real Ridgeline bitmaps say (tests/fixtures/ridgeline_2024_can29.jsonl, 2 responding ECUs; headers off, so "first"/"second" is reply order, assumed stable across pages)
- Mode 01, first responder: 01 03 04 06-09 0B-0E 11 13 15 19 1C 1F 21 23 24 28 2C-31 33 3C 3D 41-44 47 49 4A 51 55-58 62 63 66 67 68 6C 8E 9D-9F A3 A6. Second: 01 04 05 0C 0D 11 1F 21 30 31 33 41 42 45 47 49 4A.
- The truck does not advertise 0F (IAT), 10 (MAF), 46, 5C or 5E. If the example run is the same truck, it did not skip those PIDs; the truck never offered them. It advertises 66/67/68 (MAF, coolant and intake-air sensors A/B) instead, and `pids.py` cannot decode those. So the most useful "unknown PID" work on this truck is 66/67/68, not a long tail.
- Mode 09: the first ECU advertises 02 04 06 08 0A 13 14 16-19 and page 20. The second advertises 04 06 0A, so both should answer CAL ID, CVN and ECU name. Not yet checked on the real truck.

## Next steps, in order
1. **Reply classification** (~3 h). Today `elm.parse_all` returns `[]` for NO DATA, `?`, `7F xx` and wrong-SID replies alike, so a negative response looks the same as silence everywhere except the transcript. Add `elm.classify(lines, sid)` returning one of `ok | no_data | nrc:<code> | wrong_sid | adapter_error | garbled`, and keep `parse_all` as it is (callers still want payloads). The scanner and probe count the classes per command. Real-car check: does the Ridgeline answer unsupported PIDs with NO DATA or with a 7F?
2. **Unknown-PID raw capture** (~3 h). For every PID a car advertises in Mode 01 that `pids.py` cannot decode, ask once and keep `{pid, raw_hex, class}`. Snapshot gets an optional `undecoded` block (Mode 01 only), capped at 32 PIDs, sent at the same pace as the bitmap walk. Do not add decoders here. Adding 66/67/68 to `pids.py` is a separate, sourced change.
3. **`probe` command and VIN-free report** (~5 h). `shadetree-ai probe` runs `scan()` plus items 1-2, one Mode 06 MID-bitmap pass, and per-command latency (transport already records `t`). It writes `probes/<stamp>.json` and a short Markdown summary. The shareable form leaves out the VIN, the VIN serial and the full transcript. It keeps the vehicle key (WMI + VDS + year char; it names a class of car, not one car), protocol, adapter, ECU names, CAL IDs/CVNs (they are calibration versions shared by every car with that software, not per-car), the bitmaps, reply classes and latencies. Add a test like `test_no_real_vins` that runs the report on the synthetic fixtures and asserts `vin.find_vins(report) == []`.
4. **Quirks file keyed by vehicle key / WMI** (~5 h). `quirks/<key>.json`, falling back to `quirks/<WMI>.json`: hints only, schema-validated (malformed means "no quirks", like `profiles.py`). Fields: `pids_lie` (advertised but always NO DATA), `max_hz`, `protocol` (ATSP pin), `ecus` (header → role), `notes[]`, each with `source`, `confidence`, `verified`. The probe *proposes* entries from what it saw (classes and latency). A person accepts them, and nothing is written automatically. Load the file in `session.connection` / the hub run as a hint, never as a decision. Per-vehicle watch ranges come after this.

## Out of scope here
Legacy-bus decode (needs Austin's transcripts first), per-ECU attribution of Mode 09/DTC replies (needs a headers-on pass per command, and 29-bit header parsing is still unverified on hardware), VIN to make/model decode, Mode 22/UDS (barred), `export-run` using the new `transcript` field instead of its timestamp pairing (small follow-up).

## Not verified
Every step-1 read so far has run only against replay fixtures. The simulator reports a non-CAN protocol, so a scan against it skips Mode 09. Still unverified: how the real OBDLink EX + Ridgeline answer 0904/0906/090A, STDI and ATRV during a scan, and whether 0904's multi-frame reply parses as expected on 29-bit CAN.
