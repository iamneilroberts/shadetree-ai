"""Plain-language help for each reading the console shows: what it measures, how to use it, typical values.
Wording is ours (model-drafted, unreviewed) and rules of thumb only; `watch` sets the tile color and never
claims a limit for one particular car. A `null` bound is open-ended."""

_STATUS = ["model_drafted", "unreviewed"]


def _e(title, measures, use, typical, watch=None, watch_engine_off=None):
    d = {"title": title, "measures": measures, "use": use, "typical": typical, "status": list(_STATUS)}
    if watch is not None:
        d["watch"] = watch
    if watch_engine_off is not None:
        d["watch_engine_off"] = watch_engine_off
    return d


_TRIM = {"ok": [-10, 10], "out": [-20, 20]}
_TRIM_TYPICAL = "Within about +/-10 %. Worry if steady beyond +/-10 %; beyond +/-20 % is out of range here."
_SHORT_USE = ["Near 0 on both banks means the mix is on target.",
              "Positive on both banks at idle: look for a vacuum leak, weak fuel pressure or a dirty airflow sensor.",
              "Numbers that differ between banks point at one side, such as an injector or an exhaust leak."]
_LONG_USE = ["Long-term trim is the better clue for a steady fault, because it remembers.",
             "A value that keeps climbing toward +15 % or more means the computer is running out of correction room.",
             "After a repair, expect it to drift back toward 0 over some driving."]


def _short(bank):
    return _e(f"Short-term fuel trim, bank {bank}",
              f"The fuel the computer adds (+) or removes (-) right now to hold the air-fuel mix on target, for engine bank {bank}. "
              "A V engine has two banks; an inline engine has only bank 1.",
              _SHORT_USE, _TRIM_TYPICAL, _TRIM)


def _long(bank):
    return _e(f"Long-term fuel trim, bank {bank}",
              f"The learned, slower fuel correction for bank {bank}; it absorbs what the short-term trim keeps asking for.",
              _LONG_USE, _TRIM_TYPICAL, _TRIM)


_O2_LAMBDA_USE = ["It should hover around 1.00 and swing slightly as the computer adjusts.",
                  "Stuck lean or rich while the trims try to correct it points to the sensor or a real mixture fault.",
                  "Compare it with the commanded equivalence ratio; they should track each other."]
_O2_DOWN_USE = ["A healthy converter keeps this fairly steady, roughly 0.4-0.8 V.",
                "If it swings as fast as the upstream sensor, the converter may be worn out.",
                "Stuck near 0 V or 1 V suggests a sensor or wiring fault."]

HELP = {
    "0C": _e("Engine speed", "How fast the crankshaft turns, in revolutions per minute.",
             ["A warm idle should sit steady, often 600-900 rpm.",
              "Hunting up and down at idle points to an air leak, a sticking idle valve or a fuel problem.",
              "A rough idle with normal trims is more likely ignition or mechanical."],
             "600-900 rpm at warm idle (varies by car)."),
    "05": _e("Coolant temperature", "Engine coolant temperature near the thermostat.",
             ["It should climb and then hold steady once the engine is warm.",
              "Stuck cold after ten minutes of driving suggests a stuck-open thermostat or a bad sensor.",
              "A sensor that reads colder than the engine really is makes the computer run rich."],
             "85-100 C once warm. Worry above 105 C; above 112 C is out of range here.",
             {"ok": [None, 105], "out": [None, 112]}),
    "06": _short(1), "07": _long(1), "08": _short(2), "09": _long(2),
    "0B": _e("Manifold pressure (MAP)",
             "Air pressure inside the intake manifold. Low means strong vacuum; near outside pressure means the throttle is wide open or the engine is off.",
             ["Warm idle shows a steady low value, often 25-40 kPa at sea level.",
              "Key on, engine off, it should read close to the barometric pressure reading.",
              "A high or unsteady reading at idle points to a vacuum leak or a valve problem."],
             "25-40 kPa at warm idle; near outside pressure (about 100 kPa) with the engine off."),
    "42": _e("Battery voltage", "Voltage at the engine computer, a stand-in for battery and charging-system health.",
             ["Engine off, about 12.4-12.7 V is a healthy battery.",
              "Engine running, 13.5-14.8 V means the alternator is charging.",
              "Running below about 13 V points to the alternator, its belt or a wiring drop."],
             "13.5-14.8 V running; 12.4-12.7 V engine off (charging while the engine is off, as on a hybrid, is normal).",
             {"ok": [13.2, 14.8], "out": [11.5, 15.5]}, {"ok": [12.2, None], "out": [11.5, None]}),
    "04": _e("Engine load", "How hard the engine is working, as a percentage of the most air it could take in at that speed.",
             ["Idle is usually 15-30 % and rises with throttle.",
              "High load at idle hints at an air leak or a dragging accessory.",
              "Compare with throttle position: load should follow the pedal."],
             "15-30 % at warm idle."),
    "11": _e("Throttle position", "How far the throttle plate is open, from closed to wide open.",
             ["Idle often reads 10-20 % on drive-by-wire cars, not 0.",
              "It should rise smoothly as you press the pedal, with no jumps or dropouts."],
             "About 10-20 % at idle; wide open usually 70-100 %."),
    "0D": _e("Vehicle speed", "Road speed the computer is using, in km/h (multiply by 0.62 for mph).",
             ["Compare it with the speedometer; a big difference points to a wrong tire size or a speedometer error.",
              "It should read 0 when stopped."],
             "Matches the speedometer within a few percent."),
    "0E": _e("Timing advance", "How many degrees before top dead center the spark fires.",
             ["It rises with rpm and falls under load.",
              "A sudden drop while accelerating can mean the computer is pulling timing because of knock."],
             "Roughly 5-20 degrees at warm idle."),
    "43": _e("Absolute load", "Air per intake stroke compared with a fixed reference, so it reads the same at any altitude.",
             ["Idle is usually 10-30 %; wide open reaches 80 % or more on many engines.",
              "Use it with engine load to spot a sensor that disagrees."],
             "10-30 % at warm idle."),
    "44": _e("Commanded equivalence ratio",
             "The air-fuel mix the computer is asking for, as lambda: 1.00 is the chemically ideal mix, below 1 is rich, above 1 is lean.",
             ["About 1.00 when the engine is warm and running in closed loop.",
              "Below 1 when cold or under hard load is normal enrichment.",
              "Well above 1 while coasting is normal: fuel is cut off."],
             "About 1.00 at warm idle."),
    "0F": _e("Intake air temperature", "Temperature of the air going into the engine.",
             ["It should be near outside temperature when cold and somewhat above it when warm.",
              "A reading far above outside temperature on a cold engine points to a bad sensor.",
              "Hot intake air lowers power and can raise knock."],
             "Outside temperature up to about 20 C above it when warm."),
    "5C": _e("Oil temperature", "Engine oil temperature.",
             ["It lags coolant and keeps rising after coolant levels off.",
              "Sustained readings above about 130 C are hard on the oil."],
             "90-110 C when fully warm."),
    "46": _e("Ambient air temperature", "Outside air temperature as measured by the car.",
             ["Use it to sanity-check intake air temperature on a cold start.",
              "It can read high after the car sits in sun or in traffic."],
             "Matches the outside temperature."),
    "33": _e("Barometric pressure", "Outside air pressure as measured when the key goes on.",
             ["About 101 kPa at sea level, falling about 1 kPa per 100 m of altitude.",
              "With the engine off, manifold pressure should read about the same."],
             "About 101 kPa at sea level, lower at altitude."),
    "2F": _e("Fuel level", "Fuel tank level as a percentage.",
             ["Compare with the dash gauge; a large mismatch points to the sender or the gauge.",
              "It can jump around a little when the tank sloshes."],
             "Matches the dash gauge."),
    "24": _e("Upstream O2 sensor, bank 1 (lambda)",
             "What the wide-range oxygen sensor before the catalyst reads, as lambda: 1.00 is the ideal mix, below 1 rich, above 1 lean.",
             _O2_LAMBDA_USE, "Hovers near 1.00 at warm idle."),
    "28": _e("Upstream O2 sensor, bank 2 (lambda)",
             "What the wide-range oxygen sensor before the catalyst on bank 2 reads, as lambda: 1.00 is the ideal mix, below 1 rich, above 1 lean.",
             _O2_LAMBDA_USE, "Hovers near 1.00 at warm idle."),
    "15": _e("Downstream O2 sensor, bank 1 (voltage)", "Voltage of the oxygen sensor after the catalytic converter on bank 1.",
             _O2_DOWN_USE, "Steady, about 0.4-0.8 V when warm."),
    "19": _e("Downstream O2 sensor, bank 2 (voltage)", "Voltage of the oxygen sensor after the catalytic converter on bank 2.",
             _O2_DOWN_USE, "Steady, about 0.4-0.8 V when warm."),
    "3C": _e("Catalyst temperature, bank 1 sensor 1", "Temperature of the catalytic converter, as measured or estimated by the computer.",
             ["It should climb after a cold start and then hold, often 300-800 C.",
              "A converter that never warms up is not doing its job.",
              "Very high readings can mean a misfire is dumping fuel into the exhaust."],
             "300-800 C once warm."),
}

MODE06 = {
    "o2_sensor": _e("Oxygen sensor monitor", "Tests how quickly and how far the oxygen sensors switch.",
                    ["A result near its limit means the sensor is getting slow or weak.",
                     "Compare each result with its own minimum and maximum, not with other tests."],
                    "Within its limits."),
    "o2_heater": _e("Oxygen sensor heater monitor", "Checks the electrical heater that brings the sensor up to working temperature.",
                    ["An out-of-limit result usually means a failed heater or its wiring.",
                     "A slow warm-up shows up as a long delay before the engine enters closed loop."],
                    "Within its limits."),
    "catalyst": _e("Catalyst monitor", "Estimates how well the catalytic converter stores oxygen.",
                   ["A result close to its limit means the converter is wearing out.",
                    "Fix misfires and mixture faults first; they damage converters."],
                   "Within its limits."),
    "egr_vvt": _e("EGR and variable valve timing monitor", "Checks exhaust-gas recirculation flow and how well the cam phasers follow commands.",
                  ["A result near its limit points at a clogged EGR path or a sluggish phaser.",
                   "Oil level and condition matter for phasers: check them first."],
                  "Within its limits."),
    "evap": _e("EVAP system monitor", "Tests the fuel vapor system for leaks and for purge flow.",
               ["A loose or bad fuel cap is the most common cause of a failed leak test.",
                "These tests often run only after the car has sat overnight, so a missing result is normal."],
               "Within its limits."),
    "misfire": _e("Misfire monitor", "Counts misfires per cylinder over a longer window than the live misfire check.",
                  ["A count above zero on one cylinder points at that cylinder's spark, injector or compression.",
                   "Counts on every cylinder at once point to fuel or air supply."],
                  "Zero or near it, within its limit."),
    "fuel_system": _e("Fuel system monitor", "Checks that the fuel trims stay within the range the computer can correct.",
                      ["A result near its limit matches trims that are pinned high or low.",
                       "Read it together with long-term trim."],
                      "Within its limits."),
    "other": _e("On-board test", "A test the computer runs on itself; the monitor ID says which one.",
                ["Compare the value with its own minimum and maximum.",
                 "The car maker's service information says exactly what a manufacturer-specific test checks."],
                "Within its limits."),
}
