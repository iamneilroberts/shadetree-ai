# Quirks files: a how-to

A quirks file holds what is known about how one class of car answers: which protocol it talks, how fast it can be
polled, which PIDs it advertises but never answers. They are **hints, never decisions**. A quirks file cannot make
the tool write to a car: the read-only allowlist is enforced in the transport and quirks do not touch it. A wrong
hint costs time, not safety: a pinned protocol that finds nothing falls back to automatic search, and a "lying" PID
that answers anyway is kept.

Status: built and tested on recorded transcripts only. **No quirks file has been used on a real car yet.**

## The flow

1. Probe the car (read-only) and ask for a proposal:
   `shadetree-ai probe --port /dev/ttyUSB0 --propose-quirks`
   (or `--replay TRANSCRIPT` with no adapter). The VIN-free report goes to `probes/<id>.json` (a live probe also
   keeps its snapshot and transcript, which hold the VIN). No quirks file is written yet.
2. Read the proposal it prints. It is built from one probe, so every note says `confidence: low`,
   `verified: false`. Drop anything that looks wrong.
3. Accept it: `shadetree-ai quirks accept probes/<id>.json`. This writes `quirks-local/<vehicle key>.json` and is
   the only command that writes a quirks file. It refuses to overwrite: add `--replace` to overwrite, or edit the
   file by hand.
4. Edit the file if you know more (an ECU's role, a note from a service manual).
5. Check it: `shadetree-ai quirks check quirks-local/1HGCM826-3.json`. It prints `ok: <key>, hints: ...` or each
   problem in plain words (exit 1). A file with any problem is ignored by the tool as if it were not there, so
   always check after editing.
6. See which file applies: `shadetree-ai quirks show 1HGCM826-3`. It lists each file tried, in order, with why it
   was skipped (missing, or the problems), and the hints of the one that applies.
7. Run the console. Once the car is named, the file applies; `/api/state` reports it under `quirks` (the file,
   its hints, `protocol_pinned`, `hz_capped`). The console page does not show it yet.

## Vehicle key and WMI

Files are named by **vehicle key** or by **WMI**, never by VIN.

- Vehicle key: VIN characters 1-8, a dash, VIN character 10 (the model year), e.g. `1HGCM826-3`. It names a make,
  model, engine and year, not one car. The probe report shows it as `vehicle_key`.
- WMI: VIN characters 1-3, e.g. `1HG` (the maker). A WMI file applies to every car from that maker that has no
  key file, so keep WMI files to hints true for all of them.

`quirks show` also accepts a full VIN and turns it into the key without printing it.

## Search order

For a car with key `1HGCM826-3`, the first of these that loads applies; the rest are not read:

1. `quirks-local/1HGCM826-3.json` (yours, in the data home)
2. `quirks/1HGCM826-3.json` (committed, reviewed)
3. `quirks-local/1HG.json`
4. `quirks/1HG.json`

## Fields

```json
{
  "key": "1HGCM826-3",
  "example": false,
  "protocol": "6",
  "max_hz": 2.0,
  "pids_lie": ["2B"],
  "ecus": {"7E8": "engine", "7E9": "transmission"},
  "notes": [
    {"text": "advertised but answered NO DATA in one probe: 2B", "source": "probe 2026-10-07T12-00-00Z-probe",
     "confidence": "low", "verified": false}
  ]
}
```

| Field | Meaning |
|---|---|
| `key` | The vehicle key or WMI. Must match the file name (`1HGCM826-3.json`). Required. |
| `example` | `true` only for a made-up file that shows the format (`quirks/example.json`). Default `false`. |
| `protocol` | ATSP value (`1`-`9`, `A`-`C`; `6` is CAN 11-bit 500k, `2` J1850 VPW) tried instead of automatic search. Used only when you have not set `--protocol` yourself. |
| `max_hz` | Upper limit on live sweeps a second (0.1 to 10). The console lowers its rate to this, never raises it. |
| `pids_lie` | Mode 01 PIDs (two upper-case hex digits) the car advertises but always answers NO DATA. The console tries them once, quietly, instead of three times. One that answers is kept. |
| `ecus` | ECU header (upper-case hex) to a role of at most 40 characters. Recorded for reference; nothing acts on it yet. |
| `notes` | Where each hint came from: `text`, `source` (a probe id, a person, a manual), `confidence` (`unverified`, `low`, `medium`, `high`) and `verified` (`true` only if someone confirmed it on a car). All four are required. |

No other fields are allowed; a misspelt field makes the file invalid (`quirks check` names it).

## Where files live

`quirks-local/` sits in the **data home**, the same folder that holds `snapshots/`, `transcripts/`, `runs/` and
`probes/`. It is gitignored.

- Command line: `--out-dir` (default: the current folder). Use the same `--out-dir` for `probe`, `quirks accept`,
  `quirks show` and `console`, or they will not see each other's files.
- MCP server: the `SHADETREE_HOME` environment variable (default: the current folder).
- The Windows desktop shortcuts currently use `Documents\Shadetree`.

`quirks check` takes any file path; it does not look in the data home.

## Sharing a file back

Committed files live in `quirks/` at the repo root and help everyone with that class of car.

1. Run `shadetree-ai quirks check` on the file. It must say `ok`.
2. Copy it into `quirks/` in a checkout, named `<vehicle key>.json`, or `<WMI>.json` if every hint holds for the
   whole maker.
3. Mark it honestly: `confidence` and `verified` say what you know, not what you hope. A single probe is `low` and
   `verified: false`. Say in `source` where each note came from.
4. Open a pull request. The repo is public: the file must not carry a VIN. `tests/test_quirks.py` scans `quirks/`
   and fails on any VIN-looking token, and `quirks check` refuses one too.

## Current limits

- Never run on a real car yet; tested on recorded transcripts and the simulator only.
- Committed `quirks/` files load only when the tool runs from a source checkout. A `pip` or `pipx` install has no
  `quirks/` folder, so only `quirks-local/` applies there (`quirks show` says so).
- The console page does not show quirks yet; read `/api/state`.
- `ecus` is recorded but not used.
