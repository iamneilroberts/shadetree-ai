"""A partial VIN that names a class of car (make, model, engine, year) and nothing about one physical car."""
from obd_reader.snapshot import VIN_RE

# World manufacturer identifiers (VIN positions 1-3) of Honda and Acura: general knowledge, unverified, except
# 5FP, which the committed Ridgeline fixture shows. A make not listed here gets only the generic code meanings.
_WMI_MAKE = {**dict.fromkeys(("1HG", "2HG", "2HJ", "2HK", "5FN", "5FP", "5J6", "19X", "JHM", "JHL", "SHH"), "Honda"),
             **dict.fromkeys(("19U", "JH4", "5J8", "2HN"), "Acura")}


def make_of(key: str | None) -> str | None:
    """'Honda' or 'Acura' for a vehicle key whose WMI is listed, else None."""
    return _WMI_MAKE.get(key[:3]) if key else None


def vehicle_key(vin: str) -> str | None:
    """Positions 1-8 (WMI + VDS) and 10 (model year), e.g. 'ABCDEFGH-P'. Never the check digit or serial."""
    if not isinstance(vin, str) or not VIN_RE.fullmatch(vin):
        return None
    return f"{vin[:8]}-{vin[9]}"
