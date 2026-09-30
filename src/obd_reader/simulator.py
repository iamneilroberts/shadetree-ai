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
    "10": lambda v: _u16(round(v * 100)),
    "42": lambda v: _u16(round(v * 1000)),
}
_KEY = {"0C": "rpm", "05": "ect", "06": "s1", "07": "l1", "08": "s2", "09": "l2", "10": "maf", "42": "volts"}


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
        maf = 3.2 + load * 42 + (1.6 if self.scenario == "rich" else 0) + self._rnd() * 0.5
        self._values = {"rpm": self._rpm, "ect": self._ect, "s1": s1, "l1": l1, "s2": s2, "l2": l2,
                        "maf": maf, "volts": 13.9 + self._rnd() * 0.12}

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        if cmd == "010C":
            self._advance()  # one model step per sweep
        if cmd.startswith("01") and len(cmd) == 4:
            pid = cmd[2:]
            if pid in ENCODERS:
                raw = ENCODERS[pid](self._values[_KEY[pid]])
                self._pending = f"41 {pid} " + " ".join(f"{b:02X}" for b in raw) + "\r"
            else:
                self._pending = "NO DATA\r"
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
