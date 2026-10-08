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
    decode: Callable[[bytes], float | int | None]  # None: the reply says this reading is not present
    labels: dict[int, str] | None = None  # enumerated PIDs: value -> meaning (curated, unverified against J1979)


def _u16(d: bytes) -> int:
    return d[0] * 256 + d[1]


def _pct255(d: bytes) -> float:
    return round(d[0] * 100 / 255, 1)


def _trim(d: bytes) -> float:
    return round((d[0] - 128) * 100 / 128, 1)


def _temp(d: bytes) -> int:
    return d[0] - 40


def _torque_pct(d: bytes) -> int:
    return d[0] - 125


def _cat_temp(d: bytes) -> float:
    return round(_u16(d) / 10 - 40, 1)


def _u32(d: bytes) -> int:
    return int.from_bytes(d[:4], "big")


# Multi-sensor PIDs (J1979 layout [general knowledge, unverified]): byte A says which sensors are present (bit 0 is
# sensor 1 / A), then each sensor's value. Only sensor 1 is decoded; a reply that marks it absent gives no value.
# nbytes is what sensor 1 needs, not the whole reply, so a reply shorter than the full layout still reads.
def _sensor1(scale: Callable[[bytes], float | int]) -> Callable[[bytes], float | int | None]:
    return lambda d: scale(d[1:]) if d[0] & 1 else None


_FUEL_SYSTEM = {1: "Open loop, engine cold", 2: "Closed loop", 4: "Open loop, load or decel",
                8: "Open loop, system fault", 16: "Closed loop, sensor fault"}
_OBD_STD = {1: "OBD-II (CARB)", 2: "OBD (EPA)", 3: "OBD and OBD-II", 4: "OBD-I", 5: "Not OBD compliant",
            6: "EOBD (Europe)"}
_FUEL_TYPE = {1: "Gasoline", 2: "Methanol", 3: "Ethanol", 4: "Diesel", 5: "LPG", 6: "CNG", 7: "Propane",
              8: "Electric"}

_DEFS = [
    PidDef("03", "fuel_system_status", None, 2, lambda d: d[0], _FUEL_SYSTEM),
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
    PidDef("13", "o2_sensors_present", None, 1, lambda d: d[0]),   # bit mask: sensors present (2 banks x 4)
    PidDef("1C", "obd_standard", None, 1, lambda d: d[0], _OBD_STD),
    PidDef("1E", "pto_active", None, 1, lambda d: d[0] & 1),
    PidDef("1F", "run_time", "s", 2, _u16),
    PidDef("21", "distance_with_mil", "km", 2, _u16),
    PidDef("23", "fuel_rail_gauge_pressure", "kPa", 2, lambda d: _u16(d) * 10),
    PidDef("24", "o2_b1s1_lambda", "ratio", 4, lambda d: round(_u16(d) * 2 / 65536, 3)),
    PidDef("28", "o2_b2s1_lambda", "ratio", 4, lambda d: round(_u16(d) * 2 / 65536, 3)),
    # wide-range (current-type) O2 sensors: AB equivalence ratio, CD current (not exposed); sensor numbering as 14-1B
    *[
        PidDef(f"{0x34 + i:02X}", f"o2_b{i // 4 + 1}s{i % 4 + 1}_lambda_wr", "ratio", 4,
               lambda d: round(_u16(d) * 2 / 65536, 3))
        for i in range(8)
    ],
    PidDef("2C", "commanded_egr", "%", 1, _pct255),
    PidDef("2D", "egr_error", "%", 1, lambda d: round(d[0] * 100 / 128 - 100, 1)),
    PidDef("2E", "commanded_evap_purge", "%", 1, _pct255),
    PidDef("2F", "fuel_level", "%", 1, _pct255),
    PidDef("30", "warmups_since_clear", "count", 1, lambda d: d[0]),
    PidDef("31", "distance_since_clear", "km", 2, _u16),
    PidDef("33", "barometric_pressure", "kPa", 1, lambda d: d[0]),
    PidDef("3C", "catalyst_temp_b1s1", "C", 2, _cat_temp),
    PidDef("3D", "catalyst_temp_b2s1", "C", 2, _cat_temp),
    PidDef("3E", "catalyst_temp_b1s2", "C", 2, _cat_temp),
    PidDef("3F", "catalyst_temp_b2s2", "C", 2, _cat_temp),
    PidDef("42", "control_module_voltage", "V", 2, lambda d: _u16(d) / 1000),
    PidDef("43", "absolute_load", "%", 2, lambda d: round(_u16(d) * 100 / 255, 1)),
    PidDef("44", "commanded_equivalence_ratio", "ratio", 2, lambda d: round(_u16(d) * 2 / 65536, 3)),
    PidDef("45", "relative_throttle", "%", 1, _pct255),
    PidDef("46", "ambient_air_temp", "C", 1, _temp),
    PidDef("47", "absolute_throttle_b", "%", 1, _pct255),
    PidDef("49", "accelerator_pedal_d", "%", 1, _pct255),
    PidDef("4A", "accelerator_pedal_e", "%", 1, _pct255),
    PidDef("51", "fuel_type", None, 1, lambda d: d[0], _FUEL_TYPE),
    PidDef("55", "o2_trim_short_b1", "%", 1, _trim),
    PidDef("56", "o2_trim_long_b1", "%", 1, _trim),
    PidDef("57", "o2_trim_short_b2", "%", 1, _trim),
    PidDef("58", "o2_trim_long_b2", "%", 1, _trim),
    PidDef("5C", "oil_temp", "C", 1, _temp),
    PidDef("5E", "fuel_rate", "L/h", 2, lambda d: _u16(d) / 20),
    PidDef("62", "actual_engine_torque", "%", 1, _torque_pct),
    PidDef("63", "engine_reference_torque", "Nm", 2, _u16),
    PidDef("66", "maf_sensor_a", "g/s", 3, _sensor1(lambda d: round(_u16(d) / 32, 2))),
    PidDef("67", "coolant_temp_sensor_1", "C", 2, _sensor1(_temp)),
    PidDef("68", "intake_air_temp_sensor_1", "C", 2, _sensor1(_temp)),
    PidDef("77", "charge_air_cooler_temp_b1s1", "C", 2, _sensor1(_temp)),
    PidDef("87", "intake_manifold_pressure_sensor_a", "kPa", 3, _sensor1(lambda d: round(_u16(d) / 32, 2))),
    PidDef("8E", "engine_friction_torque", "%", 1, _torque_pct),
    PidDef("A6", "odometer", "km", 4, lambda d: _u32(d) / 10),
]

PIDS: dict[str, PidDef] = {d.pid: d for d in _DEFS}


def decode_pid(pid: str, data: bytes) -> PidValue | None:
    d = PIDS.get(pid)
    if d is None or len(data) < d.nbytes:
        return None
    raw = data[: d.nbytes]
    value = d.decode(raw)
    return None if value is None else PidValue(name=d.name, value=value, unit=d.unit, raw=raw.hex().upper())


def pid_label(pid: str, value: float | int | None) -> str | None:
    d = PIDS.get(pid)
    if d is None or d.labels is None or value is None:
        return None
    return d.labels.get(int(value))


def pid_name(pid: str) -> str:
    d = PIDS.get(pid)
    return d.name if d else "unknown"
