# Example runs (public)

Saved console runs that anyone can replay without a car. The console lists them under **Examples** in the
Replay panel; your own runs in `runs/` (gitignored, private) show under **My runs**.

This folder is committed to a public repo. Everything in it is public.

- **No VINs.** No VIN, no `vin` field, no 17-character VIN-shaped text anywhere in a file. A test
  (`tests/test_example_runs.py`) fails the suite if one appears. The console's saved runs never store the
  VIN, only a partial car key, but check anyway.
- **Nothing private.** No transcripts, snapshots, names, places or notes you would not post publicly.
  Remove anything you are unsure of before committing.

## Add a run

1. Pick a saved run from `runs/` and copy it here under the same file name (the name's
   `YYYY-MM-DDTHH-MM-SSZ` prefix is the time the picker shows).
2. Label it so the picker can group it by make, model and year:

   ```
   shadetree-ai label-run examples/runs/<file>.json --make Honda --model Ridgeline --year 2024 --title "Ridgeline 6 min drive"
   ```

   Make and model take at most 40 characters, the title 80, the year is a plain number (1996-2100).
   A label that looks like a VIN is refused. An unlabelled run shows under "(unlabelled)".
3. Run the tests (`pytest tests/test_example_runs.py tests/test_no_real_vins.py`) and read the diff before
   committing.

The console finds this folder when run from a checkout. A pip install does not include it; point the
console at a copy with `shadetree-ai console --examples-dir PATH`.
