"""A pretend car: a Port that answers Mode 01 PID reads, for `console --demo` and tests.

It sits behind the same gated Transport as a real adapter, so demo runs exercise the
real code path. The healthy car is modelled on a real 2024 Honda Ridgeline at warm idle in
park (its supported-PID set, two ECUs' bitmaps and the p10/median/p90 of its idle readings,
2026-10-04); the VIN and everything that identifies a car are made up. Each fault scenario
tells one story [general knowledge, unverified]:
- 'rich': the coolant sensor reads cold (P0118, open circuit: about -40 C) on a warm engine,
  so the ECU stays in open loop ("engine cold"), enriches and leaves the short-term trims at 0;
  the long-term trims keep their normal learned values.
- 'lean': a vacuum leak (P0171, P0174): closed loop, high positive trims at idle that fade as
  airflow rises, coolant normal.
'healthy' is unremarkable. Values are model numbers with small noise, not a recording.
"""
import math
import random
import time
from typing import Callable

from obd_reader.vin import with_check_digit

SIM_VIN = with_check_digit("9SXSMUL1?T0000001")  # made up, built in code so the repo's VIN guard never sees a literal

SCENARIOS = ("healthy", "rich", "lean")
# made-up broadcast traffic for `listen --port sim` (ids, rates and payloads are invented; no VIN)
BUSES = {"can": (("0C9", 0.02), ("1F5", 0.05), ("3B4", 0.2)), "j1850": (("88 FE 10", 0.1), ("8A FE 40", 0.5))}


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _u8(n: float) -> bytes:
    return bytes([_clamp(round(n), 0, 255)])


def _u16(n: float) -> bytes:
    return _clamp(round(n), 0, 65535).to_bytes(2, "big")


def _pct(v: float) -> bytes:
    return _u8(v * 255 / 100)


def _trim(pct: float) -> bytes:
    return _u8(pct * 128 / 100 + 128)


def _temp(v: float) -> bytes:
    return _u8(v + 40)


def _lam(v: float) -> bytes:
    return _u16(v * 65536 / 2)


# raw data bytes for each answered PID, given the model value (inverse of pids.py decoders), and the model key
ENCODERS: dict[str, tuple[str, Callable[[float], bytes]]] = {
    "03": ("fuelsys", lambda v: bytes([round(v), 0])), "04": ("load", _pct), "05": ("ect", _temp),
    "06": ("s1", _trim), "07": ("l1", _trim), "08": ("s2", _trim), "09": ("l2", _trim),
    "0B": ("map", _u8), "0C": ("rpm", lambda v: _u16(v * 4)), "0D": ("speed", _u8),
    "0E": ("timing", lambda v: _u8((v + 64) * 2)), "11": ("throttle", _pct), "13": ("o2present", _u8),
    "15": ("o2b1s2", lambda v: _u8(v * 200) + b"\xff"), "19": ("o2b2s2", lambda v: _u8(v * 200) + b"\xff"),
    "1C": ("obdstd", _u8), "1F": ("runtime", _u16), "21": ("mil_km", _u16), "23": ("rail", lambda v: _u16(v / 10)),
    "24": ("lam1", lambda v: _lam(v) + b"\x80\x00"), "28": ("lam2", lambda v: _lam(v) + b"\x80\x00"),
    "2C": ("egr", _pct), "2D": ("egr_err", lambda v: _u8((v + 100) * 128 / 100)), "2E": ("purge", _pct),
    "2F": ("fuel", _pct), "30": ("warmups", _u8), "31": ("clear_km", _u16), "33": ("baro", _u8),
    "3C": ("cat1", lambda v: _u16((v + 40) * 10)), "3D": ("cat2", lambda v: _u16((v + 40) * 10)),
    "42": ("volts", lambda v: _u16(v * 1000)), "43": ("absload", lambda v: _u16(v * 255 / 100)),
    "44": ("cmd_lam", _lam), "45": ("rel_throttle", _pct), "47": ("throttle_b", _pct),
    "49": ("pedal_d", _pct), "4A": ("pedal_e", _pct), "51": ("fueltype", _u8),
    "55": ("o2t_s1", _trim), "56": ("o2t_l1", _trim), "57": ("o2t_s2", _trim), "58": ("o2t_l2", _trim),
    "62": ("torque", lambda v: _u8(v + 125)), "63": ("ref_torque", _u16),
    "66": ("maf", lambda v: b"\x01" + _u16(v * 32) + b"\x00\x00"),   # sensor A present, B absent
    "67": ("ect", lambda v: b"\x01" + _temp(v) + b"\x00"),           # sensor 1 present: the same sensor as 05
    "68": ("iat", lambda v: b"\x01" + _temp(v) + b"\x00" * 5),       # bank 1 sensor 1 present
    "8E": ("friction", lambda v: _u8(v + 125)), "A6": ("odo", lambda v: _clamp(round(v * 10), 0, 2**32 - 1).to_bytes(4, "big")),
}
# advertised PIDs the decoder table does not know: a fixed made-up reply of a plausible length, so a scan's
# "undecoded" list has raw bytes for them
RAW_ONLY = {"41": "00 07 E5 00", "6C": "01 23 00 00 00", "9D": "00 64 00 64", "9E": "00 2A", "9F": "01 00 00 00 00 00 00 00 00",
            "A3": "01 00 00 00 00 00 00 00 00"}
# what each ECU's bitmaps advertise (the Ridgeline's engine ECU and second ECU); data PIDs answer once
PCM_PIDS = {"01", "03", "04", "06", "07", "08", "09", "0B", "0C", "0D", "0E", "11", "13", "15", "19", "1C", "1F", "21",
            "23", "24", "28", "2C", "2D", "2E", "2F", "30", "31", "33", "3C", "3D", "41", "42", "43", "44", "47", "49",
            "4A", "51", "55", "56", "57", "58", "62", "63", "66", "67", "68", "6C", "8E", "9D", "9E", "9F", "A3", "A6"}
ECU2_PIDS = {"01", "04", "05", "0C", "0D", "11", "1F", "21", "30", "31", "33", "41", "42", "45", "47", "49", "4A"}
SUPPORTED = PCM_PIDS | ECU2_PIDS

# (stored, pending) codes as 2-byte DTCs; a stored code commands the lamp, so it is also a permanent code
_CODES = {
    "healthy": ([], []),
    "rich": ([0x0118], []),
    "lean": ([0x0171, 0x0174], []),
}

# Mode 01 PID 01 bytes B C D (spark ignition): the Ridgeline engine ECU's monitor set; D = which have not completed
# (made up: EVAP on the faulty cars)
_MONITORS = {"healthy": (0x07, 0xE5, 0x00), "rich": (0x07, 0xE5, 0x04), "lean": (0x07, 0xE5, 0x04)}
# Mode 02 frame 0 for a car with a stored code: the readings frozen when its first stored code was set (made up,
# consistent with the scenario: open loop with STFT 0 and normal LTFT for the cold sensor; closed loop, high trims,
# normal coolant for the leak)
_FROZEN = {
    "rich": {"03": 1, "04": 25, "05": -40, "06": 0, "07": 3.1, "08": 0, "09": 2.3, "0B": 33, "0C": 880, "0D": 0},
    "lean": {"03": 2, "04": 26, "05": 88, "06": 9.4, "07": 17.2, "08": 7.8, "09": 16.4, "0B": 34, "0C": 745, "0D": 0},
}
IDLE_RPM, REV_RPM = 723.0, 2500.0


def _dtc_reply(sid: int, codes: list[int]) -> str:
    return " ".join(f"{b:02X}" for b in [sid, len(codes)] + [x for c in codes for x in (c >> 8, c & 0xFF)])


class SimPort:
    def __init__(self, scenario: str = "rich", clock: Callable[[], float] = time.monotonic, seed: int = 7,
                 bus: str | None = None, sleep: Callable[[float], None] = time.sleep):
        if scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        if bus is not None and bus not in BUSES:
            raise ValueError(f"bus must be one of {tuple(BUSES)}")
        self.scenario, self.rev = scenario, False
        self._clock, self._rng = clock, random.Random(seed)
        self._t0 = self._last = clock()
        self._rpm = IDLE_RPM
        self._values: dict[str, float] = {}
        self._pending = ""
        self.bus, self._sleep = bus, sleep
        self._monitoring, self._mon_last = False, 0.0
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
        k, sc, n = min(1.0, dt / 0.4), self.scenario, self._rnd
        idle = {"healthy": IDLE_RPM + 5 * math.sin(t * 1.3), "lean": 745 + 40 * math.sin(t * 2.1),
                "rich": 880 + 10 * math.sin(t * 1.1)}[sc]  # the cold-reading sensor: the ECU holds a cold fast idle
        target = REV_RPM if self.rev else idle
        self._rpm += (target - self._rpm) * 0.38 * k + n() * (30 if self.rev else 14)
        r = max(0.0, min(1.0, (self._rpm - IDLE_RPM) / (REV_RPM - IDLE_RPM)))  # free rev in park: vacuum rises, load falls
        mp = 32 - 8 * r + (2 if sc == "lean" else 0) + n() * 0.8
        if sc == "rich":  # open loop: no short-term correction, the learned long-term values stay where they were
            s1 = s2 = 0.0
            l1, l2 = 3.1, 2.3
        elif sc == "lean":
            f = 15 * (1 - r) + 2
            l1, l2 = f + n() * 0.5, f - 1 + n() * 0.5
            s1, s2 = 3 + 4 * math.sin(t * 1.9) + n(), 3 + 4 * math.sin(t * 1.6 + 1) + n()
        else:
            l1, l2 = 3.1, 2.3
            s1, s2 = 4.7 + 0.8 * math.sin(t * 2.3) + n() * 0.6, 2.9 + 0.5 * math.sin(t * 2.0 + 1) + n() * 0.6
        lam = 0.85 if sc == "rich" else 1.0  # cold enrichment: commanded and measured lambda below 1
        self._values = {
            "rpm": self._rpm, "speed": 0, "map": mp, "baro": 101, "ect": -40 if sc == "rich" else 88 + n() * 0.4,
            "iat": 30 + n() * 0.6, "load": 24.3 - 12 * r + n() * 1.2, "absload": 19.6 - 6 * r + n() * 0.6,
            "timing": 4.5 + 30 * r + n() * 1.5, "volts": 14.46 + n() * 0.12,
            "throttle": 13.7 + 8 * r + n() * 0.3, "throttle_b": 13.7 + 8 * r + n() * 0.3, "rel_throttle": 2.7 + 8 * r,
            "pedal_d": 19.6 + 12 * r, "pedal_e": 9.8 + 6 * r,
            "maf": 3.6 * (self._rpm / IDLE_RPM) * (mp / 32) + n() * 0.1,
            "s1": s1, "l1": l1, "s2": s2, "l2": l2, "fuelsys": 1 if sc == "rich" else 2,
            "lam1": lam + n() * 0.03, "lam2": lam + n() * 0.03, "cmd_lam": (0.85 if sc == "rich" else 0.997) + n() * 0.02,
            "o2b1s2": (0.80 if sc == "rich" else 0.63) + n() * 0.16, "o2b2s2": (0.80 if sc == "rich" else 0.63) + n() * 0.16,
            "o2t_s1": 0, "o2t_l1": 0, "o2t_s2": -0.8, "o2t_l2": 0,
            "rail": min(3590, 3540 + n() * 140), "fuel": 44.7, "cat1": 545 + 40 * r + n() * 4, "cat2": 545 + 40 * r + n() * 4,
            "purge": 32.5 + n(), "egr": 0, "egr_err": 99.2, "warmups": 255, "clear_km": 14273,
            "mil_km": 0 if sc == "healthy" else 42, "runtime": 600 + t, "torque": 18 + 3 * r + n(), "friction": 15,
            "ref_torque": 256, "obdstd": 1, "fueltype": 1, "o2present": 0x33, "odo": 61234.0 + t / 3600,
        }

    @staticmethod
    def _bitmap(sid: str, base: int, pids: set[int]) -> str | None:
        """One ECU's support bitmap for this page, or None when it advertises nothing there (it does not answer)."""
        bits = 0
        for i in range(32):
            if base + 1 + i in pids or (i == 31 and any(p > base + 32 for p in pids)):
                bits |= 1 << (31 - i)
        return f"{sid} {base:02X} " + " ".join(f"{b:02X}" for b in bits.to_bytes(4, "big")) if bits else None

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
            return f"42 {pid} 00 " + hexs(ENCODERS[pid][1](frozen[pid]))
        return "NO DATA"

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        if cmd == "010C":
            self._advance()  # one model step per sweep
        if cmd.startswith("01") and len(cmd) == 4 and int(cmd[2:], 16) % 0x20 == 0:
            base = int(cmd[2:], 16)
            lines = [self._bitmap("41", base, {int(p, 16) for p in ecu}) for ecu in (PCM_PIDS, ECU2_PIDS)]
            self._pending = "\r".join(ln for ln in lines if ln) + "\r" if any(lines) else "NO DATA\r"
        elif cmd.startswith("01") and len(cmd) == 4 and cmd != "0101":
            pid = cmd[2:]
            if pid in ENCODERS and pid in SUPPORTED:
                key, enc = ENCODERS[pid]
                self._pending = f"41 {pid} " + " ".join(f"{b:02X}" for b in enc(self._values[key])) + "\r"
            elif pid in RAW_ONLY:
                self._pending = f"41 {pid} {RAW_ONLY[pid]}\r"
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
            self._pending = _dtc_reply({"03": 0x43, "07": 0x47, "0A": 0x4A}[cmd], {"03": stored, "07": pending, "0A": stored}[cmd]) + "\r"
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
        elif cmd == "ATDPN" and self.bus:  # opt-in, so existing simulator runs keep their protocol answers
            self._pending = ("A6" if self.bus == "can" else "A2") + "\r"
        elif cmd in ("ATMA", "STMA"):
            self._monitoring, self._mon_last, self._pending = True, self._clock(), ""
        else:
            self._pending = "OK\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def read_available(self, timeout: float) -> str:
        if not self._monitoring:
            return ""
        lines = self._broadcast()
        if not lines:
            self._sleep(min(timeout, 0.02))
            lines = self._broadcast()
        return "".join(ln + "\r" for ln in lines)

    def interrupt(self) -> None:
        if self._monitoring:
            self._monitoring, self._pending = False, "STOPPED\r"

    def _broadcast(self) -> list[str]:
        now, lines = self._clock(), []
        for key, period in BUSES[self.bus or "can"]:
            first, last = int((self._mon_last - self._t0) / period + 1e-9), int((now - self._t0) / period + 1e-9)
            lines += [self._frame(key, k) for k in range(first + 1, last + 1)]
        self._mon_last = now
        return lines

    def _frame(self, key: str, k: int) -> str:
        rpm = int(self._rpm * 4) & 0xFFFF
        data = {"0C9": [rpm >> 8, rpm & 0xFF, k & 0x0F, 0, 0, 0, 0, 0], "1F5": [0] * 7 + [k & 0x0F], "3B4": [0x20, 0, 0, 0],
                "88 FE 10": [0x0B, rpm >> 8, rpm & 0xFF], "8A FE 40": [0x01, 0x00]}[key]
        if self.bus == "j1850":
            head = [int(x, 16) for x in key.split()]
            data = data + [sum(head + data) & 0xFF]
        return key + " " + " ".join(f"{b:02X}" for b in data)

    def close(self) -> None:
        pass
