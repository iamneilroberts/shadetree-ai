"""GM Mode $06 test names, units and help for J1850 VPW (Class 2) vehicles, keyed by TID, component and limit type.

Source: GM, "Mode $06 data definitions for GM vehicles using J1850/Class2 diagnostic data link", J1850/Class2 rev3,
16 pages, https://gsi.ext.gm.com/gmspo/mode6/pdf/GM%20Class2%20mode%20$06%20data%20final_dm.pdf (read 2026-10-04).
The facts (which TID and component is which test, the limit type, the unit and range) are restated here in our own
words; GM's document is not copied or redistributed. Confidence: manufacturer-published. License: facts only, cite
GM. Review: model_drafted, unreviewed until Austin checks it. The help wording is ours and drafted by the model.

Keys use the component id with bit 7 cleared plus the limit type, because the car sends the type in bit 7 (set =
low limit). GM's table lists some rows with bit 7 cleared (TID 02) and some with it set (e.g. 05/85, 0E/B5); both
map to the same key here. That rule was checked against all 11 TID 02 rows a 2003 GMC truck returned.

Scaling is our inference from GM's decimal and hex ranges: a range like -3276.8..+3276.7 over hex 0000-FFFF is
an offset of 32768 times 0.1; over hex 8000-7FFF it is a signed (two's complement) number times 0.1.
"""
from typing import Literal

SOURCE = ("GM, Mode $06 data definitions for GM vehicles using J1850/Class2 diagnostic data link (rev3), "
          "restated in our own words")

# unit key -> (unit label, factor); None factor = GM gives no scaling we can apply (raw shown)
_UNITS: dict[str, tuple[str | None, float | None]] = {
    "raw": (None, None), "ixs": ("index-s", 0.1), "inh2o": ("in H2O", 0.1), "s10": ("s", 0.1),
    "inh2o_s": ("in H2O/s", 0.001), "slope": ("% slope error", 0.390625), "counts": ("counts", 1),
    "kpa": ("kPa", 0.001), "mv_cat": ("mV", 1110 / 65536), "mv": ("mV", 2048 / 65536), "ms1024": ("ms", 1024 / 65536),
    "switches": ("switches", 1), "ratio8": ("ratio", 8 / 65536), "ms": ("ms", 1), "samples": ("samples", 1),
    "ms2048": ("ms", 2048 / 65536), "sec": ("s", 1), "gcyl": ("g/cyl", 1 / 256), "kpa_half": ("kPa", 0.5),
    "kpa_egr": ("kPa", 90 / 65536), "in": ("in", 0.0001), "ratio4": ("ratio", 4 / 65536), "ratio256": ("ratio", 1 / 256),
    "liters": ("L", 0.001), "s_cat": ("s", 0.001), "norm": ("ratio", 2 / 65536), "amps": ("A", None),
    "ohms": ("ohm", 0.001),
}

# what each monitor (TID) does: (title, what it measures, how to use it)
MONITORS: dict[str, tuple[str, str, list[str]]] = {
    "02": ("EVAP monitor, 0.040 in leak", "The computer seals the fuel vapor system, pulls a vacuum on it with the "
           "purge valve and watches how fast the vacuum builds and decays, to find leaks of about 0.040 in and larger.",
           ["A test that cannot pull enough vacuum points at a large leak: fuel cap, filler neck, vent valve or a hose.",
            "These tests run only under narrow conditions (fuel level, temperature, after a cold soak), so many rows "
            "stay at zero until the test has run."]),
    "03": ("Secondary air injection (AIR) monitor", "Checks that the air pump pushes air into the exhaust on a cold "
           "start, and that the shut-off valve closes, from a pressure sensor in the AIR system.",
           ["Pressure low with the pump on points at the pump, its fuse or relay, or a leaking hose.",
            "Pressure with the pump off points at a shut-off valve stuck open."]),
    "04": ("Catalyst monitor, steady state", "Compares the oxygen sensors before and after the converter at a steady "
           "speed to estimate how much oxygen the converter stores.",
           ["A worn converter stores less oxygen, so the rear sensor starts to follow the front one.",
            "Fix misfires and mixture faults first: they damage converters and spoil this test."]),
    "05": ("Oxygen sensor monitor", "Times how fast and how often the oxygen sensors switch between rich and lean, "
           "and checks the sensors after the converter for open circuits and for reaching rich and lean voltages.",
           ["A slow or lazy sensor shows long switch times, few switches or a lopsided rich/lean response.",
            "A post-converter sensor that never reaches its rich or lean voltage points at the sensor or an exhaust leak."]),
    "06": ("Oxygen sensor heater warm-up", "Times how long each heated oxygen sensor takes to become active after a "
           "start.", ["A long time points at a failed heater, its fuse or wiring."]),
    "07": ("EGR monitor", "Opens and closes the EGR valve during idle, off-idle or deceleration tests and checks that "
           "airflow or manifold pressure changes as much as it should.",
           ["Too little change points at clogged EGR passages or a stuck valve.",
            "Change with the valve commanded shut points at a valve stuck open or leaking."]),
    "0A": ("EVAP monitor, 0.020 in leak", "A second set of EVAP tests: vacuum-decay tests with the engine running, "
           "and engine-off natural vacuum tests that watch tank pressure as the fuel cools after the engine stops.",
           ["The engine-off tests run after a drive, with the key off; a missing result is normal on short trips.",
            "A failing small-leak result points at the cap seal, a cracked hose or a vent valve that does not seal."]),
    "0C": ("Catalyst efficiency monitor", "Measures how much oxygen the converter stores (oxygen storage capacity) "
           "from the oxygen sensors before and after it.",
           ["A result moving toward its limit means the converter is wearing out.",
            "Fix misfires and mixture faults first."]),
    "0E": ("Oxygen sensor heater current", "Watches the current each oxygen sensor heater draws.",
           ["Too little current points at an open heater or wiring; too much at a shorted heater."]),
    "16": ("Oxygen sensor heater resistance", "Compares each oxygen sensor heater's resistance with what the computer "
           "expects.", ["An error outside the limits points at a heater wearing out, or wiring resistance."]),
}

# vehicle-specific notes from GM's footnotes, restated
_NOTES = {
    1: "GM scales this row as a signed number and planned to phase it out (CARB mail-out 98-01).",
    2: "2004 Saturn LS, Grand Am, Sunfire, Alero, Cavalier and Classic with the 2.2 L (VIN F): GM says this row may "
       "use a signed range (-32768 to +32767).",
    3: "2004-2005 vehicles with the 4.6 L (VIN Y or 9): GM says the limits of 05/43 and 05/44 may be swapped.",
    4: "2004-2005 trucks with the 2.8 L (VIN 8) or 3.5 L (VIN 6): GM says this value is invalid.",
    5: "2004-2007 parallel hybrid trucks with the 5.3 L (VIN T): GM says this limit is really a minimum, so a value "
       "above it passes.",
    6: "2007 Rendezvous 3.5 L (VIN 8), LaCrosse 3.8 L (VIN 2) and Grand Prix 3.8 L (VIN 2 or 4): if the limit reads "
       "8.8 s the value may be invalid; check it against whether P0446 is set.",
    7: "2005-2006 Colorado, Canyon, H3, Trailblazer, Envoy, Rainier, 9-7X, Ascender, Malibu 2.2 L, Cobalt SS and "
       "ION Redline: the limit reads 0; GM says to treat it as 1 count (0 or 1 passes).",
    8: "Same 2005-2006 vehicles as above: the limit reads 0; GM gives the real limit as 0.7299 (0.4000 while P0450 "
       "is active), and a value at or below it passes.",
    9: "Same 2005-2006 vehicles as above: the limit reads 0; GM gives a real limit per vehicle group, from about "
       "0.40 to 0.65 (about 0.33 to 0.45 while P0450 is active).",
}

Limit = Literal["min", "max"]
# (tid, component with bit 7 cleared, limit type, name, unit key, mode, footnote): mode "u" unsigned, "o" offset
# 32768, "s" signed. Rows GM lists twice (bit 7 set and cleared) appear once.
_ROWS: list[tuple[str, str, Limit, str, str, str, int | None]] = [
    ("02", "04", "min", "Canister loading", "raw", "u", None),
    ("02", "06", "min", "Excess vacuum, pass test 2", "ixs", "o", None),
    ("02", "10", "min", "Weak vacuum, pass test 1", "inh2o", "s", 1),
    ("02", "11", "min", "Purge leak, pass test", "s10", "u", None),
    ("02", "12", "max", "Small leak, vacuum decay rate", "inh2o_s", "s", 1),
    ("02", "20", "max", "Weak vacuum, fail test 1", "ixs", "s", 1),
    ("02", "21", "max", "Purge leak, vapor fail test", "s10", "u", None),
    ("02", "26", "max", "Excess vacuum, test 1", "inh2o", "s", 1),
    ("02", "30", "min", "Weak vacuum test 2, vacuum time", "s10", "u", None),
    ("02", "31", "max", "Purge leak, vacuum fail test", "inh2o", "o", None),
    ("02", "36", "max", "Excess vacuum, fail test 2", "s10", "u", None),
    ("02", "40", "min", "Weak vacuum test 2, vapor time", "s10", "u", None),
    ("02", "46", "min", "Excess vacuum, pass test 2", "ixs", "s", 1),
    ("02", "50", "min", "Weak vacuum, pass test 1", "inh2o", "o", None),
    ("02", "52", "max", "Small leak, vacuum decay rate", "inh2o_s", "o", None),
    ("02", "60", "max", "Weak vacuum, fail test 1", "ixs", "o", None),
    ("02", "62", "max", "Engine-off natural vacuum, 0.020 in error", "slope", "o", None),
    ("02", "66", "max", "Excess vacuum, test 1", "inh2o", "o", None),
    ("02", "71", "max", "Purge leak, vacuum fail test", "inh2o", "o", None),
    ("02", "72", "max", "Engine-off natural vacuum, 0.040 in error", "slope", "o", None),
    ("03", "01", "max", "AIR, bank 1", "counts", "u", None),
    ("03", "02", "max", "AIR, bank 2", "counts", "u", None),
    ("03", "03", "max", "AIR pressure with pump on, bank 1, too high", "kpa", "o", None),
    ("03", "03", "min", "AIR pressure with pump on, bank 1, too low", "kpa", "o", None),
    ("03", "04", "min", "AIR pressure with valve shut, bank 1", "kpa", "o", None),
    ("03", "05", "max", "AIR pressure with pump off, bank 1", "kpa", "o", None),
    ("03", "13", "max", "AIR pressure with pump on, bank 2, too high", "kpa", "o", None),
    ("03", "13", "min", "AIR pressure with pump on, bank 2, too low", "kpa", "o", None),
    ("03", "14", "min", "AIR pressure with valve shut, bank 2", "kpa", "o", None),
    ("03", "15", "max", "AIR pressure with pump off, bank 2", "kpa", "o", None),
    ("03", "16", "max", "AIR pressure difference between banks, too high", "kpa", "o", None),
    ("03", "16", "min", "AIR pressure difference between banks, too low", "kpa", "o", None),
    ("04", "20", "max", "Steady-state catalyst, bank 1", "mv_cat", "s", 1),
    ("04", "30", "max", "Steady-state catalyst, bank 2", "mv_cat", "s", 1),
    ("04", "60", "max", "Steady-state catalyst, bank 1", "mv_cat", "o", None),
    ("04", "61", "max", "Catalyst, bank 1, fuel cut-off exit test", "counts", "u", 5),
    ("04", "70", "max", "Steady-state catalyst, bank 2", "mv_cat", "o", None),
    ("04", "71", "max", "Catalyst, bank 2, fuel cut-off exit test", "counts", "u", 5),
    ("05", "01", "max", "Rich-to-lean threshold voltage, B1S1", "mv", "u", None),
    ("05", "02", "max", "Lean-to-rich threshold voltage, B1S1", "mv", "u", None),
    ("05", "03", "max", "Low voltage used for switch time, B1S1", "mv", "u", None),
    ("05", "04", "max", "High voltage used for switch time, B1S1", "mv", "u", None),
    ("05", "05", "max", "Rich-to-lean switch time, B1S1, too slow", "ms1024", "u", None),
    ("05", "05", "min", "Rich-to-lean switch time, B1S1, too fast", "ms1024", "u", None),
    ("05", "06", "max", "Lean-to-rich switch time, B1S1, too slow", "ms1024", "u", None),
    ("05", "06", "min", "Lean-to-rich switch time, B1S1, too fast", "ms1024", "u", None),
    ("05", "07", "min", "Rich-to-lean switch count, B1S1", "switches", "u", None),
    ("05", "08", "min", "Lean-to-rich switch count, B1S1", "switches", "u", None),
    ("05", "09", "max", "Rich/lean response ratio, B1S1, too high", "ratio8", "u", None),
    ("05", "09", "min", "Rich/lean response ratio, B1S1, too low", "ratio8", "u", None),
    ("05", "0A", "max", "Rear sensor open circuit, B1S2", "samples", "u", 4),
    ("05", "0B", "min", "Rear sensor reaches rich voltage, B1S2", "mv", "u", None),
    ("05", "0C", "max", "Rear sensor reaches lean voltage, B1S2", "mv", "u", None),
    ("05", "0D", "max", "Rich vs lean response difference, B1S1, too high", "ms", "o", 2),
    ("05", "0D", "min", "Rich vs lean response difference, B1S1, too low", "ms", "o", 2),
    ("05", "13", "max", "Low voltage used for half period, B1S1", "mv", "u", None),
    ("05", "14", "max", "High voltage used for half period, B1S1", "mv", "u", None),
    ("05", "15", "max", "Rich-to-lean half period, B1S1", "ms2048", "u", None),
    ("05", "16", "max", "Lean-to-rich half period, B1S1", "ms2048", "u", None),
    ("05", "17", "max", "Sum of both half periods, B1S1", "ms2048", "u", None),
    ("05", "1A", "max", "Rear sensor open circuit, B1S3", "samples", "u", None),
    ("05", "1B", "min", "Rear sensor reaches rich voltage, B1S3", "mv", "u", None),
    ("05", "1C", "max", "Rear sensor reaches lean voltage, B1S3", "mv", "u", None),
    ("05", "41", "max", "Rich-to-lean threshold voltage, B2S1", "mv", "u", None),
    ("05", "42", "max", "Lean-to-rich threshold voltage, B2S1", "mv", "u", None),
    ("05", "43", "max", "Low voltage used for switch time, B2S1", "mv", "u", 3),
    ("05", "44", "max", "High voltage used for switch time, B2S1", "mv", "u", 3),
    ("05", "45", "max", "Rich-to-lean switch time, B2S1, too slow", "ms1024", "u", None),
    ("05", "45", "min", "Rich-to-lean switch time, B2S1, too fast", "ms1024", "u", None),
    ("05", "46", "max", "Lean-to-rich switch time, B2S1, too slow", "ms1024", "u", None),
    ("05", "46", "min", "Lean-to-rich switch time, B2S1, too fast", "ms1024", "u", None),
    ("05", "47", "min", "Rich-to-lean switch count, B2S1", "switches", "u", None),
    ("05", "48", "min", "Lean-to-rich switch count, B2S1", "switches", "u", None),
    ("05", "49", "max", "Rich/lean response ratio, B2S1, too high", "ratio8", "u", None),
    ("05", "49", "min", "Rich/lean response ratio, B2S1, too low", "ratio8", "u", None),
    ("05", "4A", "max", "Rear sensor open circuit, B2S2", "samples", "u", None),
    ("05", "4B", "min", "Rear sensor reaches rich voltage, B2S2", "mv", "u", None),
    ("05", "4C", "max", "Rear sensor reaches lean voltage, B2S2", "mv", "u", None),
    ("05", "4D", "max", "Rich vs lean response difference, B2S1, too high", "ms", "o", None),
    ("05", "4D", "min", "Rich vs lean response difference, B2S1, too low", "ms", "o", None),
    ("05", "53", "max", "Low voltage used for half period, B2S1", "mv", "u", None),
    ("05", "54", "max", "High voltage used for half period, B2S1", "mv", "u", None),
    ("05", "55", "max", "Rich-to-lean half period, B2S1", "ms2048", "u", None),
    ("05", "56", "max", "Lean-to-rich half period, B2S1", "ms2048", "u", None),
    ("05", "57", "max", "Sum of both half periods, B2S1", "ms2048", "u", None),
    ("05", "5A", "max", "Rear sensor open circuit, B2S3", "samples", "u", None),
    *[("06", c, "max", f"Heater warm-up time, {s}", "sec", "u", None)
      for c, s in (("35", "B1S1"), ("41", "B1S2"), ("47", "B1S3"), ("55", "B2S1"), ("61", "B2S2"), ("67", "B2S3"))],
    ("07", "01", "min", "EGR flow range seen by the MAF", "gcyl", "u", None),
    ("07", "02", "max", "Lowest exhaust pressure in the EGR test", "kpa_half", "u", None),
    ("07", "03", "max", "Airflow below expected, EGR off, idle test", "gcyl", "u", None),
    ("07", "04", "max", "Airflow below expected, EGR off, off-idle test", "gcyl", "u", None),
    ("07", "05", "max", "Airflow below expected, full EGR, idle test", "gcyl", "u", None),
    ("07", "06", "max", "Airflow too high, EGR off, idle test", "gcyl", "u", None),
    ("07", "07", "max", "Airflow too high, EGR off, off-idle test", "gcyl", "u", None),
    ("07", "08", "max", "Largest airflow error in the EGR test", "gcyl", "u", None),
    ("07", "09", "max", "EGR vacuum regulator stuck open, idle test", "kpa_half", "u", None),
    ("07", "0A", "max", "EGR vent solenoid stuck closed, idle test", "kpa_half", "u", None),
    ("07", "0B", "max", "Airflow too high, EGR off, idle test (2)", "gcyl", "u", None),
    ("07", "0B", "min", "Airflow too low, EGR off, idle test", "gcyl", "u", None),
    ("07", "0C", "max", "Airflow too high, EGR off, off-idle test (2)", "gcyl", "u", None),
    ("07", "0C", "min", "Airflow too low, EGR off, off-idle test", "gcyl", "u", None),
    ("07", "0D", "max", "EGR deceleration test", "kpa_egr", "s", 1),
    ("07", "0D", "min", "Airflow too low, full EGR, idle test", "gcyl", "u", None),
    ("07", "4C", "max", "EGR cruise test", "kpa_egr", "o", None),
    ("07", "4D", "max", "EGR flow, deceleration service test", "kpa_egr", "o", None),
    ("07", "4F", "max", "EGR flow, quick test", "kpa_egr", "o", None),
    ("0A", "01", "max", "Canister vent restriction, test 1", "s10", "u", 6),
    ("0A", "03", "max", "Vacuum decay, weak vacuum test", "s10", "u", None),
    ("0A", "04", "min", "Vacuum decay, weak vacuum follow-up", "s10", "u", None),
    ("0A", "05", "max", "Leak test, 0.040 in", "in", "u", None),
    ("0A", "06", "max", "Leak test, 0.020 in", "in", "u", None),
    ("0A", "07", "min", "Vacuum decay, purge pass test", "s10", "u", None),
    ("0A", "09", "max", "Engine-off natural vacuum, 0.020 in (older software)", "ratio4", "u", None),
    ("0A", "0A", "max", "Engine-off natural vacuum, 0.020 in (newer software)", "ratio256", "u", 9),
    ("0A", "0B", "max", "Engine-off natural vacuum, re-zero test", "ratio256", "u", 8),
    ("0A", "0C", "max", "Engine-off natural vacuum, fuel level check", "counts", "u", 7),
    ("0A", "0D", "max", "Engine-off natural vacuum, vacuum check", "counts", "u", 7),
    ("0A", "13", "max", "Weak vacuum test", "liters", "u", None),
    ("0A", "42", "max", "Canister vent restriction, test 2, too high", "inh2o", "o", None),
    ("0A", "42", "min", "Canister vent restriction, test 2, too low", "liters", "u", None),
    ("0A", "48", "max", "Vacuum decay, purge vacuum fail test", "inh2o", "o", None),
    ("0C", "20", "max", "Idle catalyst efficiency, bank 1", "s_cat", "s", 1),
    ("0C", "30", "max", "Idle catalyst efficiency, bank 2", "s_cat", "s", 1),
    ("0C", "60", "max", "Catalyst oxygen storage, bank 1", "s_cat", "o", None),
    ("0C", "61", "min", "Catalyst oxygen storage, bank 1, normalized", "norm", "u", None),
    ("0C", "70", "max", "Catalyst oxygen storage, bank 2", "s_cat", "o", None),
    ("0C", "71", "min", "Catalyst oxygen storage, bank 2, normalized", "norm", "u", None),
    *[("0E", c, "max", f"Heater current check samples, {s}", "samples", "u", 4 if c == "12" else None)
      for c, s in (("11", "B1S1"), ("12", "B1S2"), ("13", "B1S3"), ("21", "B2S1"), ("22", "B2S2"), ("23", "B2S3"))],
    *[r for c, s in (("35", "B1S1"), ("41", "B1S2"), ("47", "B1S3"), ("55", "B2S1"), ("61", "B2S2"), ("67", "B2S3"))
      for r in (("0E", c, "max", f"Heater current, {s}, too high", "amps", "u", None),
                ("0E", c, "min", f"Heater current, {s}, too low", "amps", "u", None))],
    *[r for c, s in (("11", "B1S1"), ("12", "B1S2"), ("13", "B1S3"), ("21", "B2S1"), ("22", "B2S2"), ("23", "B2S3"))
      for r in (("16", c, "max", f"Heater resistance error, {s}, too high", "ohms", "o", None),
                ("16", c, "min", f"Heater resistance error, {s}, too low", "ohms", "o", None))],
]

TESTS: dict[tuple[str, str, str], tuple[str, str, str, int | None]] = {}
for _t, _c, _l, _n, _u, _m, _f in _ROWS:
    TESTS.setdefault((_t, _c, _l), (_n, _u, _m, _f))

# GM's world manufacturer identifiers start 1G, 2G or 3G (also 5G for Hummer): general knowledge, unverified.
_GM_WMI = ("1G", "2G", "3G", "5G")


def is_gm(key: str | None) -> bool:
    return bool(key) and key[:2] in _GM_WMI


def help_key(tid: str, component: str, limit_type: str) -> str:
    return f"gm:{tid}:{component}:{limit_type}"


def scale(raw: int, unit: str, mode: str) -> float | None:
    """A raw 16-bit value in GM's unit, or None where GM's range gives no scaling we can apply."""
    factor = _UNITS[unit][1]
    if factor is None:
        return None
    n = raw - 32768 if mode == "o" else (raw - 65536 if mode == "s" and raw >= 32768 else raw)
    return round(n * factor, 4)


def annotate(row: dict) -> dict:
    """A legacy Mode 06 row (tid, component, value, limit, limit_type) plus GM's test name, monitor, unit and the
    scaled value and limit, when GM's table lists it. The raw numbers are kept unchanged."""
    hit = TESTS.get((row["tid"], row["component"], row["limit_type"]))
    if hit is None:
        return row
    name, unit, mode, _ = hit
    return {**row, "name": name, "monitor": MONITORS[row["tid"]][0], "unit": _UNITS[unit][0],
            "value_s": scale(row["value"], unit, mode), "limit_s": scale(row["limit"], unit, mode),
            "help": help_key(row["tid"], row["component"], row["limit_type"])}


def _help(tid: str, comp: str, lim: str, name: str, unit: str, mode: str, note: int | None) -> dict:
    title, measures, use = MONITORS[tid]
    label, factor = _UNITS[unit]
    dirn = ("a low limit: the value must reach it (at or above passes)" if lim == "min" else
            "a high limit: the value must stay at or below it")
    how = (f"Shown in {label}" + (", scaled by us from GM's stated range" if factor not in (None, 1) or mode != "u" else "")
           if label and factor is not None else "GM gives no scaling we can apply, so the raw number is shown")
    lines = [f"GM marks this limit as {dirn}.", how + ".", *use]
    if note:
        lines.append(_NOTES[note])
    lines.append(f"TID {tid}, component {comp}. Source: {SOURCE}.")
    return {"title": name, "measures": f"{title}. {measures}", "use": lines,
            "typical": "At or above its limit." if lim == "min" else "At or below its limit.",
            "status": ["model_drafted", "unreviewed"]}


HELP: dict[str, dict] = {help_key(t, c, lim): _help(t, c, lim, n, u, m, f) for (t, c, lim), (n, u, m, f) in TESTS.items()}
