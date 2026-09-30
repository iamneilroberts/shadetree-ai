"""A partial VIN that names a class of car (make, model, engine, year) and nothing about one physical car."""
from obd_reader.snapshot import VIN_RE


def vehicle_key(vin: str) -> str | None:
    """Positions 1-8 (WMI + VDS) and 10 (model year), e.g. 'ABCDEFGH-P'. Never the check digit or serial."""
    if not isinstance(vin, str) or not VIN_RE.fullmatch(vin):
        return None
    return f"{vin[:8]}-{vin[9]}"
