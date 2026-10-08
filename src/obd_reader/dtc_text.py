"""Plain-words meanings for common generic trouble codes.

Own wording (no copied tables), drafted by the model and unreviewed: tagged
`model_drafted` in the project's provenance scheme. `hint` is general knowledge, unverified.
Codes not listed get a category line and no hint.
"""

_T = {
    "P0101": ("Mass air flow sensor signal out of range", "Dirty or failed MAF sensor, or an intake leak near it"),
    "P0102": ("Mass air flow circuit low input", "Check the MAF connector and wiring first"),
    "P0113": ("Intake air temperature circuit high input", "Open circuit or failed IAT sensor"),
    "P0117": ("Engine coolant temperature circuit low input", "Low sensor voltage reads hot: a shorted sensor or a signal wire shorted to ground"),
    "P0118": ("Engine coolant temperature circuit high input",
              "High sensor voltage reads cold (often an open circuit or failed sensor), so the ECU adds fuel"),
    "P0128": ("Coolant temperature below thermostat regulating temperature", "Thermostat stuck open is the usual cause"),
    "P0171": ("System too lean (bank 1)", "Unmetered air or low fuel: smoke-test the intake"),
    "P0172": ("System too rich (bank 1)", "Trim is pulling fuel: check the coolant sensor first"),
    "P0174": ("System too lean (bank 2)", "Both banks lean points upstream of the split"),
    "P0175": ("System too rich (bank 2)", "Trim is pulling fuel on bank 2"),
    "P0300": ("Random or multiple cylinder misfire detected", "Check plugs, coils, and fuel trims before parts"),
    "P0301": ("Cylinder 1 misfire detected", "Swap the coil with a neighbour to see if the misfire follows"),
    "P0302": ("Cylinder 2 misfire detected", "Swap the coil with a neighbour to see if the misfire follows"),
    "P0303": ("Cylinder 3 misfire detected", "Swap the coil with a neighbour to see if the misfire follows"),
    "P0304": ("Cylinder 4 misfire detected", "Swap the coil with a neighbour to see if the misfire follows"),
    "P0305": ("Cylinder 5 misfire detected", "Swap the coil with a neighbour to see if the misfire follows"),
    "P0306": ("Cylinder 6 misfire detected", "Swap the coil with a neighbour to see if the misfire follows"),
    "P0307": ("Cylinder 7 misfire detected", "Swap the coil with a neighbour to see if the misfire follows"),
    "P0308": ("Cylinder 8 misfire detected", "Swap the coil with a neighbour to see if the misfire follows"),
    "P0335": ("Crankshaft position sensor circuit", "Sensor, wiring, or reluctor ring damage"),
    "P0420": ("Catalyst efficiency below threshold (bank 1)", "Rule out exhaust leaks and misfires before the converter"),
    "P0430": ("Catalyst efficiency below threshold (bank 2)", "Rule out exhaust leaks and misfires before the converter"),
    "P0440": ("Evaporative emission control system malfunction", "Start with the fuel cap and its seal"),
    "P0442": ("Evaporative system small leak detected", "Fuel cap, then hoses and the purge valve"),
    "P0455": ("Evaporative system large leak detected", "Loose or missing fuel cap is common"),
    "P0456": ("Evaporative system very small leak detected", "Fuel cap seal, then hoses"),
    "P0507": ("Idle speed higher than expected", "Vacuum leak or dirty throttle body"),
    "P0562": ("System voltage low", "Weak battery or charging fault: test the alternator"),
    "P0563": ("System voltage high", "Charging system overcharging: test the regulator"),
    "U0100": ("Lost communication with the engine control module", "Check power and ground at the ECM and the CAN wiring"),
}

# Make-specific meanings, checked before the generic table. Same provenance as above: own wording from
# general knowledge (no OBDb, no paid or proprietary source), a hint that says so where the exact meaning is unsure.
MAKE_SOURCE = {"source": "model general knowledge", "confidence": "model_drafted", "review_status": "unreviewed",
               "license": "MIT (own wording)"}
_HONDA = {
    "P1456": ("Honda/Acura: EVAP leak, fuel tank side", "Fuel cap and its seal first, then the tank-side vapor lines"),
    "P1457": ("Honda/Acura: EVAP leak, canister side", "Canister vent valve and canister hoses are common suspects"),
    "P2646": ("Rocker arm (VTEC) oil pressure switch A: performance or stuck off, bank 1",
              "Oil level and condition first. Exact Honda wording unconfirmed: check the service manual"),
    "P2647": ("Rocker arm (VTEC) oil pressure switch A: stuck on, bank 1",
              "Oil level and condition first. Exact Honda wording unconfirmed: check the service manual"),
    "P3400": ("Cylinder deactivation (VCM) system, bank 1",
              "Oil level and condition first; bank numbering varies by engine"),
    "P3497": ("Cylinder deactivation (VCM) system, bank 2",
              "Oil level and condition first. Exact Honda wording unconfirmed: check the service manual"),
}
_MAKE = {"Honda": _HONDA, "Acura": _HONDA}

_CAT = {"P": "powertrain", "B": "body", "C": "chassis", "U": "network"}


def describe(code: str, make: str | None = None) -> dict:
    """{desc, hint, known} for a code such as 'P0171'; `make` (e.g. 'Honda') picks make-specific meanings first."""
    t = _MAKE.get(make, {})
    if code in t or code in _T:
        d, h = t.get(code) or _T[code]
        return {"desc": d, "hint": h, "known": True}
    kind = _CAT.get(code[:1], "unknown")
    scope = "generic" if code[1:2] == "0" else "manufacturer-specific"
    return {"desc": f"{kind.capitalize()} code ({scope}), no plain-words description bundled", "hint": "", "known": False}
