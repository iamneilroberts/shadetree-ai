"""Mode 01 PID table: hand-written from public formulas (Wikipedia "OBD-II PIDs"),
confidence `curated`, to be checked against SAE J1979 before being called
authoritative. Only the common, well-documented PIDs are listed."""
from dataclasses import dataclass
from typing import Callable

from obd_reader.snapshot import PidValue


@dataclass(frozen=True)
class PidDef:
    pid: str
    name: str
    unit: str | None
    nbytes: int
    decode: Callable[[bytes], float | int]


def _u16(d: bytes) -> int:
    return d[0] * 256 + d[1]


def _pct255(d: bytes) -> float:
    return round(d[0] * 100 / 255, 1)


def _trim(d: bytes) -> float:
    return round((d[0] - 128) * 100 / 128, 1)


def _temp(d: bytes) -> int:
    return d[0] - 40


_DEFS = [
    PidDef("04", "calculated_engine_load", "%", 1, _pct255),
    PidDef("05", "coolant_temp", "C", 1, _temp),
    PidDef("06", "stft_b1", "%", 1, _trim),
    PidDef("07", "ltft_b1", "%", 1, _trim),
    PidDef("08", "stft_b2", "%", 1, _trim),
    PidDef("09", "ltft_b2", "%", 1, _trim),
    PidDef("0A", "fuel_pressure", "kPa", 1, lambda d: d[0] * 3),
    PidDef("0B", "intake_manifold_pressure", "kPa", 1, lambda d: d[0]),
    PidDef("0C", "engine_rpm", "rpm", 2, lambda d: _u16(d) / 4),
    PidDef("0D", "vehicle_speed", "km/h", 1, lambda d: d[0]),
    PidDef("0E", "timing_advance", "deg", 1, lambda d: d[0] / 2 - 64),
    PidDef("0F", "intake_air_temp", "C", 1, _temp),
    PidDef("10", "maf", "g/s", 2, lambda d: _u16(d) / 100),
    PidDef("11", "throttle_position", "%", 1, _pct255),
    *[
        PidDef(f"{0x14 + i:02X}", f"o2_b{i // 4 + 1}s{i % 4 + 1}_voltage", "V", 2, lambda d: d[0] / 200)
        for i in range(8)
    ],
    PidDef("1F", "run_time", "s", 2, _u16),
    PidDef("21", "distance_with_mil", "km", 2, _u16),
    PidDef("2C", "commanded_egr", "%", 1, _pct255),
    PidDef("2E", "commanded_evap_purge", "%", 1, _pct255),
    PidDef("2F", "fuel_level", "%", 1, _pct255),
    PidDef("30", "warmups_since_clear", "count", 1, lambda d: d[0]),
    PidDef("31", "distance_since_clear", "km", 2, _u16),
    PidDef("33", "barometric_pressure", "kPa", 1, lambda d: d[0]),
    PidDef("42", "control_module_voltage", "V", 2, lambda d: _u16(d) / 1000),
    PidDef("43", "absolute_load", "%", 2, lambda d: round(_u16(d) * 100 / 255, 1)),
    PidDef("44", "commanded_equivalence_ratio", "ratio", 2, lambda d: round(_u16(d) * 2 / 65536, 3)),
    PidDef("45", "relative_throttle", "%", 1, _pct255),
    PidDef("46", "ambient_air_temp", "C", 1, _temp),
    PidDef("5C", "oil_temp", "C", 1, _temp),
    PidDef("5E", "fuel_rate", "L/h", 2, lambda d: _u16(d) / 20),
]

PIDS: dict[str, PidDef] = {d.pid: d for d in _DEFS}


def decode_pid(pid: str, data: bytes) -> PidValue | None:
    d = PIDS.get(pid)
    if d is None or len(data) < d.nbytes:
        return None
    raw = data[: d.nbytes]
    return PidValue(name=d.name, value=d.decode(raw), unit=d.unit, raw=raw.hex().upper())


def pid_name(pid: str) -> str:
    d = PIDS.get(pid)
    return d.name if d else "unknown"
