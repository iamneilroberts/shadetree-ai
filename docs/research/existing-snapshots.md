# Existing public OBD-II recordings: assessment (2026-09-28)

Bottom line: nothing public gives us raw ELM327 transcripts with labeled faults, and nothing public covers 1996-2008 protocols (J1850/ISO 9141/KWP). Public data is mostly (a) decoded live-data CSV with no DTCs and (b) simulator dictionaries. We must record our own for anything fault- or legacy-related.

Method note: verified via WebFetch/WebSearch only. `gh`/Bash was unavailable in this session (worktree guard), so no sample files were downloaded and no file was inspected byte-for-byte. Kaggle pages are JS-rendered and returned no license/size metadata.

## Summary table

| Source | Type | Vehicle/protocol | License | Convert effort | Labeled faults? |
|---|---|---|---|---|---|
| Ircama/ELM327-emulator `obd_message.py` ('car' scenario) | Simulated ELM traffic dictionary (Toyota Auris Hybrid) | CAN 11-bit 500k | README badge CC-BY-NC-SA-4.0; GitHub API says NOASSERTION | Easy (regex request/response pairs) | No (DTC lists empty by default) |
| Ircama `obd_dictionary` tool (generate your own) | Scanner that walks all standard requests on a real car | Any ELM-supported | Tool is same repo/license; output is our own data | Easy | No, only what the car has |
| python-OBD tests + obdsim | Mocked responses / simulator | Synthetic | GPL-2.0 | Hard (mocks, not transcripts) | No |
| cephasax/OBDdatasets (Barreto "dailyRoutes", "19drivers", 4 drivers); Kaggle `cephasax/obdii-ds3` | Decoded live-data CSV | 14 vehicles 2003-2016 (dailyRoutes); 2015 Chevrolet S10 (19drivers); ELM327 + Android OBD Reader | Not verified (repo page shows none) | Moderate (time series only) | No |
| Kaggle `eron93br/obd2data` | Decoded live-data CSV, 27 params, idle+motion, 4 routes | Toyota Etios 2014 1.5, Carloop | Not verified | Moderate | No |
| HCRL "This Car is Mine" / HCRL Driving (IEEE DataPort) | Decoded OBD CSV, 1 Hz, 51 params, 30 sessions | Hyundai YF Sonata, 4 drivers | Not verified | Moderate | No (driver ID, not faults) |
| IEEE DataPort "IoT Vehicle Telemetry" | CSV, 38.76 MB | Unspecified | Not specified; login required | Moderate | No |
| Edge Impulse OBD tutorial dataset | CSV 2 Hz: MAF, NOx, pedal, RPM, MAP, lambda | Unspecified | Not verified | Moderate | Yes, but only 2 classes: healthy vs intake air leak (NOx) |
| ORNL ROAD (dyno fault injection) | Raw CAN frames, not OBD PIDs | 2013 Ford Fusion Hybrid, CAN | Not verified | Hard (needs DBC decode) | Injected injector/spark-plug faults, not DTC-labeled |
| thatlarrypearson/telemetry-obd | Logger (JSON-lines: command_name, value, timestamps) | Tested on F-450, EcoSport, Wrangler, Sienna Hybrid | MIT | n/a: tool, ships no data | No |
| Kaggle `donnetew/odb2-powertrain-codes`, todrobbins/dtcdb | DTC description tables | n/a | Not verified | n/a | Reference only, useful for DTC lookup |
| Forum case studies (Toyota Nation, ford-trucks.com, JustAnswer) | Prose, occasional freeze frame / trim values | Various, mostly pre-2010 | Copyrighted forum posts | Hard (manual) | Yes, root cause in text |

## Per-source notes

### 1. ELM327-emulator (best transcript-format match)
- https://github.com/Ircama/ELM327-emulator, `elm/obd_message.py` (~95-110 KB by estimate, ~2,500 lines), updated 2026-09-17.
- Scenarios: `AT`, `default`, `car` (Toyota Auris Hybrid), `mt05` (Delphi MT05 motorcycle ECU). Ships 0100 -> `41 00 BE 3F A8 13` (identical to our sample line), 0101, 0902 VIN as multi-frame ISO-TP, 03/07/0A via `dtc_frames()`. Freeze frame mostly returns NRC `12`.
- The `car` VIN bytes decode to `WP0ZZZ99ZTS390000`, which looks like a placeholder VIN, not a real car.
- No fault state: DTC lists are empty; MIL logic is programmatic (`status_byte()`). Legacy protocols appear only as emulated AT-command handling, not recorded ECU data.
- License risk: README badge is CC-BY-NC-SA-4.0 (non-commercial, share-alike); GitHub reports NOASSERTION. Fine to run locally as a fixture generator. Do not copy the dictionary into a public or commercial repo without asking the author. Safer: run the emulator (nothing bundled) and capture our own transcripts from it.
- Its `obd_dictionary` tool can walk a real car and produce a dictionary, a cheap way to record our own vehicles.

### 2. Decoded live-data CSVs
- These give only the time-series half of our snapshot (RPM, coolant, speed, throttle, sometimes trims/O2). No VIN, DTCs, readiness, or raw hex. Column names vary by Android app.
- cephasax/OBDdatasets (https://github.com/cephasax/OBDdatasets, https://www.kaggle.com/datasets/cephasax/obdii-ds3): the only source with a range of older vehicles (2003-2016), decoded values only; repo README is sparse; thesis is in Portuguese.
- obd2data (https://www.kaggle.com/datasets/eron93br/obd2data): single 2014 Toyota Etios.
- HCRL (reviewed in arXiv 2510.25856; IEEE DataPort): 51 params at 1 Hz. Volume and shape, not diagnosis.
- Redistribution: assume internal use only until a license is confirmed on the download page. Keep out of the repo (fetch script) until confirmed.

### 3. Labeled faults
- Edge Impulse (https://docs.edgeimpulse.com/tutorials/end-to-end/obd-automotive-data): CSV with `time (ms.)`, `fault_label`, values at 2 Hz; classes `healthy` and `airleak_nox`, about 10 min per class. Only public labeled-fault OBD CSV found, but one fault type, uses NOx (not a standard PID on most cars), no DTCs.
- ORNL ROAD: injected faults on raw CAN, not OBD-II mode 01. Not usable in our pipeline.
- Forum case studies (e.g. https://www.toyotanation.com/threads/2002-ce-p0171-and-cant-find-the-vacuum-leak.1697376/): real root causes (vacuum leak, intake manifold gasket, cracked intake box) but data is pasted in prose. Reference only; hand-transcription per case, text is copyrighted.

### 4. Legacy vehicles (1996-2008) / non-CAN
- Searched GitHub and forums for raw J1850/ISO 9141/KWP logs: none found. Only libraries (kierandrewett/obd, RyoheiHashimoto/obd2 simulated ECUs) and datasheets. A Peugeot Forums hyperterminal thread (https://www.peugeotforums.com/threads/odb2-elm327-bluetooth-and-ecu-with-hyper-terminal.252370/) may hold raw AT sessions; not opened, and forum text is unlicensed.
- Conclusion: legacy recordings must be self-recorded, or hand-written from spec and clearly marked synthetic.

## Ranked recommendation for Phase 1-2

1. **ELM327-emulator as a generator (run locally).** Use the `car` scenario with injected DTCs (stored/pending/permanent) and MIL on; capture our JSONL transcripts from it. Exact ELM formatting incl. multi-frame VIN/DTC. ~1-2 hours to script. Synthetic, so it tests parsers and replay, not diagnostic quality. Commit only transcripts we generate, after license comfort check.
2. **cephasax dailyRoutes CSV (14 vehicles, 2003-2016).** Best breadth for the live-data series; ~half a day to map columns. Confirm license before committing; use a fetch script until then.
3. **Edge Impulse healthy vs air-leak CSV.** Only labeled-fault time series; one "air/fuel fault" eval example. ~1-2 hours; confirm license first.

Must record ourselves: real ELM327/STN transcripts with real DTCs, freeze frames, readiness and mode 0A from at least one CAN car; deliberate known-cause faults (unplugged MAF/O2 sensor, induced vacuum leak) on a spare vehicle; any 1996-2008 J1850/ISO 9141/KWP vehicle; a real VIN transcript.

## Could not verify

- License, file sizes, column lists for all Kaggle datasets (dommatap/obd-dataset returned 404) and the cephasax GitHub repo.
- HCRL and IoT Vehicle Telemetry licenses (IEEE DataPort needs login; page states none).
- Whether any decoded CSV has fuel trim/O2 columns or a DTC column.
- Exact ELM327-emulator license (badge vs API NOASSERTION; LICENSE file not confirmed); `obd_message.py` size is estimated and the `car` excerpts came from a summarized fetch, not a byte-level read.
- Whether the emulator repo or its issues hold community real-car dictionaries beyond the Toyota.
- Edge Impulse dataset license/size; whether ROAD has a decoded OBD form.
- Any public J1850/ISO 9141/KWP raw session (none found; absence not proven).
- python-OBD is GPL-2.0 (GitHub API); its test contents rest on a summarized fetch.
