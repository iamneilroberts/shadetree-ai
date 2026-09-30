"""Mode 01 PID 01 (monitor status since DTCs cleared): 41 01 A B C D.

B bits 0-2 = misfire / fuel system / components supported, bits 4-6 = the same
three not complete, bit 3 = ignition type (0 spark, 1 compression).
C = which of 8 further monitors are supported, D = which of them are NOT complete
(same bit order). Bit names below are for spark ignition; compression engines use
a different list, reported here by bit number until verified.
"""
from obd_reader.snapshot import Monitor

SPARK = ["catalyst", "heated_catalyst", "evap", "secondary_air", "ac_refrigerant",
         "o2_sensor", "o2_sensor_heater", "egr"]
COMPRESSION = [f"compression_monitor_bit{i}" for i in range(8)]


def parse_readiness(payloads: list[bytes]) -> tuple[str | None, dict[str, Monitor]]:
    valid = [p for p in payloads if len(p) >= 6 and p[1] == 0x01]
    if not valid:
        return None, {}
    compression = bool(valid[0][3] & 0x08)
    names = COMPRESSION if compression else SPARK
    all_names = ["misfire", "fuel_system", "components", *names]
    monitors = {n: Monitor(supported=False) for n in all_names}
    for p in valid:
        b, c, d = p[3], p[4], p[5]
        entries = [("misfire", b & 0x01, b & 0x10), ("fuel_system", b & 0x02, b & 0x20),
                   ("components", b & 0x04, b & 0x40)]
        entries += [(names[i], (c >> i) & 1, (d >> i) & 1) for i in range(8)]
        for name, supported, incomplete in entries:
            if not supported:
                continue
            prev = monitors[name]
            complete = not incomplete
            monitors[name] = Monitor(
                supported=True,
                complete=complete if prev.complete is None else (prev.complete and complete),
            )
    return ("compression" if compression else "spark"), monitors
