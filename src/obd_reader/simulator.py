"""A pretend car: a Port that answers Mode 01 PID reads, for `console --demo` and tests.

It sits behind the same gated Transport as a real adapter, so demo runs exercise the
real code path. Numbers follow the Suburban mock: 'rich' has a coolant sensor that
reads cold and trims near -20 %, 'lean' has a vacuum leak whose trims fade as airflow
rises, 'healthy' is unremarkable.
"""
import math
import random
import time
from typing import Callable

from obd_reader.vin import with_check_digit

SIM_VIN = with_check_digit("9SXSMUL1?T0000001")  # made up, built in code so the repo's VIN guard never sees a literal

SCENARIOS = ("healthy", "rich", "lean")


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _u16(n: int) -> bytes:
    return _clamp(n, 0, 65535).to_bytes(2, "big")


def _trim(pct: float) -> bytes:
    return bytes([_clamp(round(pct * 128 / 100 + 128), 0, 255)])


# raw data bytes for each supported PID, given the model value (inverse of pids.py decoders)
ENCODERS: dict[str, Callable[[float], bytes]] = {
    "0C": lambda v: _u16(round(v * 4)),
    "05": lambda v: bytes([_clamp(round(v + 40), 0, 255)]),
    "06": _trim, "07": _trim, "08": _trim, "09": _trim,
    "0B": lambda v: bytes([_clamp(round(v), 0, 255)]),
    "04": lambda v: bytes([_clamp(round(v * 255 / 100), 0, 255)]),
    "0D": lambda v: bytes([_clamp(round(v), 0, 255)]),
    "0E": lambda v: bytes([_clamp(round((v + 64) * 2), 0, 255)]),
    "11": lambda v: bytes([_clamp(round(v * 255 / 100), 0, 255)]),
    "3C": lambda v: _u16(round((v + 40) * 10)),
    "44": lambda v: _u16(round(v * 65536 / 2)),
    "42": lambda v: _u16(round(v * 1000)),
    # the rest of a typical 2000s gasoline car's list, so "Capture all supported" has ~30 readings (no MAF: speed density; no 0F, which tests use as a PID this car does not answer)
    "03": lambda v: bytes([round(v), 0]),
    "3E": lambda v: _u16(round((v + 40) * 10)), "46": lambda v: bytes([_clamp(round(v + 40), 0, 255)]),
    "5C": lambda v: bytes([_clamp(round(v + 40), 0, 255)]),
    "14": lambda v: bytes([_clamp(round(v * 200), 0, 255), 0xFF]), "15": lambda v: bytes([_clamp(round(v * 200), 0, 255), 0xFF]),
    "1C": lambda v: bytes([round(v)]), "30": lambda v: bytes([_clamp(round(v), 0, 255)]),
    "1F": lambda v: _u16(round(v)), "21": lambda v: _u16(round(v)), "31": lambda v: _u16(round(v)),
    "2F": lambda v: bytes([_clamp(round(v * 255 / 100), 0, 255)]), "49": lambda v: bytes([_clamp(round(v * 255 / 100), 0, 255)]),
    "4A": lambda v: bytes([_clamp(round(v * 255 / 100), 0, 255)]),
    "33": lambda v: bytes([_clamp(round(v), 0, 255)]),
    "43": lambda v: _u16(round(v * 255 / 100)),
}
_KEY = {"0C": "rpm", "05": "ect", "06": "s1", "07": "l1", "08": "s2", "09": "l2", "0B": "map", "04": "load", "0D": "speed", "0E": "timing", "11": "throttle", "3C": "cat", "44": "lam", "42": "volts",
        "03": "fuelsys", "3E": "cat2", "46": "ambient", "5C": "oil", "14": "o2s1", "15": "o2s2", "1C": "obdstd", "30": "warmups",
        "1F": "runtime", "21": "mil_km", "31": "clear_km", "2F": "fuel", "49": "pedal_d", "4A": "pedal_e", "33": "baro", "43": "absload"}


# (stored, pending) codes as 2-byte DTCs, and whether the lamp is on
_CODES = {
    "healthy": ([], []),
    "rich": ([0x0117, 0x0172], [0x0175]),
    "lean": ([0x0171, 0x0174], [0x0101]),
}


# Mode 01 PID 01 bytes B C D (spark ignition): misfire, fuel system and components supported; catalyst, EVAP,
# O2 sensor, O2 heater and EGR supported; D = which of those have not completed (made up: EVAP on the faulty cars)
_MONITORS = {"healthy": (0x07, 0xE5, 0x00), "rich": (0x07, 0xE5, 0x04), "lean": (0x07, 0xE5, 0x04)}
# Mode 02 frame 0 for a car with a stored code: the readings frozen when its first stored code was set (made up)
_FROZEN = {
    "rich": {"03": 1, "04": 24, "05": 38, "06": -9, "07": -21, "0B": 33, "0C": 1150, "0D": 0},
    "lean": {"03": 2, "04": 19, "05": 90, "06": 9, "07": 17, "0B": 34, "0C": 690, "0D": 0},
}


def _dtc_reply(sid: int, codes: list[int]) -> str:
    return " ".join(f"{b:02X}" for b in [sid, len(codes)] + [x for c in codes for x in (c >> 8, c & 0xFF)])


class SimPort:
    def __init__(self, scenario: str = "rich", clock: Callable[[], float] = time.monotonic, seed: int = 7):
        if scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        self.scenario, self.rev = scenario, False
        self._clock, self._rng = clock, random.Random(seed)
        self._t0 = self._last = clock()
        self._rpm, self._ect = 700.0, 88.0
        self._values: dict[str, float] = {}
        self._pending = ""
        self._advance()

    def set_scenario(self, name: str) -> None:
        if name not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        self.scenario = name

    def _rnd(self) -> float:
        return self._rng.random() - 0.5

    def _advance(self) -> None:
        now = self._clock()
        dt = min(2.0, max(0.05, now - self._last))
        self._last, t = now, now - self._t0
        k = min(1.0, dt / 0.4)
        target = 2500.0 if self.rev else 700 + (60 * math.sin(t * 2.1) if self.scenario == "lean" else 25 * math.sin(t * 1.3))
        self._rpm += (target - self._rpm) * 0.38 * k + self._rnd() * (30 if self.rev else 14)
        load = max(0.0, min(1.0, (self._rpm - 700) / 1800))
        if self.scenario == "rich":
            self._ect += (41 - self._ect) * 0.2 * k + self._rnd() * 0.3
        else:
            self._ect += (91 - self._ect) * 0.02 * k + self._rnd() * 0.2
        if self.scenario == "rich":
            l1, l2 = -21 + self._rnd() * 0.5, -19 + self._rnd() * 0.5
            s1, s2 = -12 + 4 * math.sin(t * 1.7) + self._rnd(), -10 + 4 * math.sin(t * 1.5 + 1) + self._rnd()
        elif self.scenario == "lean":
            f = 15 * (1 - load) + 2
            l1, l2 = f + self._rnd() * 0.5, f - 1 + self._rnd() * 0.5
            s1, s2 = 3 + 4 * math.sin(t * 1.9) + self._rnd(), 3 + 4 * math.sin(t * 1.6 + 1) + self._rnd()
        else:
            l1, l2 = 1.2 + self._rnd() * 0.4, 0.8 + self._rnd() * 0.4
            s1, s2 = 3 * math.sin(t * 2.3) + self._rnd(), 3 * math.sin(t * 2.0 + 1) + self._rnd()
        self._values = {"rpm": self._rpm, "ect": self._ect, "s1": s1, "l1": l1, "s2": s2, "l2": l2,
                        "map": 28 + load * 70 + (3 if self.scenario == "rich" else 0) + self._rnd() * 0.8, "volts": 13.9 + self._rnd() * 0.12,
                        "load": 18 + load * 62 + self._rnd() * 0.6, "speed": 0, "timing": 12 + load * 18 + self._rnd() * 0.4,
                        "throttle": 12 + load * 30 + self._rnd() * 0.3, "cat": 480 + load * 120 + self._rnd(),
                        "lam": 1.0 + self._rnd() * 0.004,
                        "fuelsys": 2, "cat2": 420 + load * 90 + self._rnd(), "ambient": 24, "oil": self._ect + 4, "o2s1": 0.45 + 0.4 * math.sin(t * 6.3),
                        "o2s2": 0.68 + self._rnd() * 0.02, "obdstd": 1, "warmups": 12, "runtime": t,
                        "mil_km": 0 if self.scenario == "healthy" else 42, "clear_km": 380, "fuel": 63 - t / 600,
                        "pedal_d": 15 + load * 30, "pedal_e": 7.5 + load * 15, "baro": 101, "absload": 20 + load * 60 + self._rnd()}

    @staticmethod
    def _bitmap(sid: str, base: int, pids: set[int]) -> str:
        bits = 0
        for i in range(32):
            if base + 1 + i in pids or (i == 31 and any(p > base + 32 for p in pids)):
                bits |= 1 << (31 - i)
        return f"{sid} {base:02X} " + " ".join(f"{b:02X}" for b in bits.to_bytes(4, "big"))

    def _mode02(self, pid: str) -> str:
        """Freeze frame 0: the support bitmap, the code that stored it (0000: none) and its frozen readings."""
        stored, frozen = _CODES[self.scenario][0], _FROZEN.get(self.scenario, {})
        hexs = lambda raw: " ".join(f"{x:02X}" for x in raw)  # noqa: E731
        if pid in ("00", "20", "40"):
            bits = 0
            for p in [2, *(int(k, 16) for k in frozen)] if stored else []:
                if int(pid, 16) < p <= int(pid, 16) + 32:
                    bits |= 1 << (31 - (p - int(pid, 16) - 1))
            return f"42 {pid} 00 " + hexs(bits.to_bytes(4, "big")) if bits else "NO DATA"
        if pid == "02":
            c = stored[0] if stored else 0
            return f"42 02 00 {c >> 8:02X} {c & 0xFF:02X}"
        if stored and pid in frozen:
            return f"42 {pid} 00 " + hexs(ENCODERS[pid](frozen[pid]))
        return "NO DATA"

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        if cmd == "010C":
            self._advance()  # one model step per sweep
        if cmd in ("0100", "0120", "0140"):
            self._pending = self._bitmap("41", int(cmd[2:], 16), {int(k, 16) for k in ENCODERS}) + "\r"
        elif cmd.startswith("01") and len(cmd) == 4 and cmd != "0101":
            pid = cmd[2:]
            if pid in ENCODERS:
                raw = ENCODERS[pid](self._values[_KEY[pid]])
                self._pending = f"41 {pid} " + " ".join(f"{b:02X}" for b in raw) + "\r"
            else:
                self._pending = "NO DATA\r"
        elif cmd in ("0600", "0620"):
            self._pending = "46 00 80 00 00 01\r" if cmd == "0600" else "46 20 80 00 00 00\r"
        elif cmd == "0601":
            self._pending = "46 01 80 14 00 C7 00 00 00 C8 01 87 14 00 9B 00 00 01 0E\r"
        elif cmd == "0621":
            self._pending = "46 21 A1 0B 00 00 00 00 0B B8\r"
        elif cmd in ("03", "07", "0A"):
            stored, pending = _CODES[self.scenario]
            self._pending = _dtc_reply({"03": 0x43, "07": 0x47, "0A": 0x4A}[cmd], {"03": stored, "07": pending, "0A": []}[cmd]) + "\r"
        elif cmd == "0101":
            stored, _ = _CODES[self.scenario]
            b, c, d = _MONITORS[self.scenario]
            self._pending = f"41 01 {(0x80 if stored else 0) | len(stored):02X} {b:02X} {c:02X} {d:02X}\r"
        elif cmd.startswith("02") and len(cmd) == 6 and cmd.endswith("00"):
            self._pending = self._mode02(cmd[2:4]) + "\r"
        elif cmd == "0902":
            b = [0x49, 0x02, 0x01] + list(SIM_VIN.encode("ascii"))
            fr = lambda chunk: " ".join(f"{x:02X}" for x in chunk)
            self._pending = "\r".join(["014", "0: " + fr(b[:6]), "1: " + fr(b[6:13]), "2: " + fr(b[13:20])]) + "\r"
        elif cmd == "ATI":
            self._pending = "SIM327 (simulated)\r"
        elif cmd == "STI":
            self._pending = "?\r"
        elif cmd == "ATDP":
            self._pending = "SIMULATED (no car)\r"
        else:
            self._pending = "OK\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def close(self) -> None:
        pass
