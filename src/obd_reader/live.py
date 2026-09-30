"""Bounded live-data sampling over the gated transport (Mode 01 only)."""
import re
import time
from typing import Callable

from obd_reader.elm import parse_all
from obd_reader.pids import PIDS
from obd_reader.snapshot import LiveSample, Series
from obd_reader.transport import Transport

MAX_PIDS = 8
MAX_SECONDS = 120.0
MAX_HZ = 10.0
MAX_POINTS = 120
_PID_RE = re.compile(r"[0-9A-Fa-f]{2}")


class LiveLimitError(ValueError):
    """A live-data request outside the safety limits or with a bad PID."""


def validate_pids(pids: list[str]) -> list[str]:
    if not pids or len(pids) > MAX_PIDS:
        raise LiveLimitError(f"give between 1 and {MAX_PIDS} PIDs")
    out: list[str] = []
    for p in pids:
        if not isinstance(p, str) or not _PID_RE.fullmatch(p):
            raise LiveLimitError(f"not a 2-digit hex PID: {p!r}")
        p = p.upper()
        if p not in PIDS:
            raise LiveLimitError(f"PID {p} is not in the decoder table")
        if p in out:
            raise LiveLimitError(f"duplicate PID {p}")
        out.append(p)
    return out


def sample(
    transport: Transport,
    pids: list[str],
    seconds: float,
    *,
    hz: float = 2.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> LiveSample:
    pids = validate_pids(pids)
    if not 0 < seconds <= MAX_SECONDS:
        raise LiveLimitError(f"seconds must be in (0, {MAX_SECONDS:g}]")
    if not 0 < hz <= MAX_HZ:
        raise LiveLimitError(f"hz must be in (0, {MAX_HZ:g}]")
    series = {p: Series(name=PIDS[p].name, unit=PIDS[p].unit) for p in pids}
    period, t0 = 1.0 / hz, clock()
    while True:
        t = clock() - t0
        if t > seconds:
            break
        for p in pids:
            d = PIDS[p]
            for payload in parse_all(transport.send(f"01{p}"), 0x41):
                if len(payload) >= 2 + d.nbytes and payload[1] == int(p, 16):
                    series[p].samples.append((round(t, 3), d.decode(payload[2 : 2 + d.nbytes])))
                    break
        sleep(max(0.0, period - (clock() - t0 - t)))
    return LiveSample(duration_s=seconds, rate_hz=hz, series=series)


def summarize(series: Series) -> dict:
    vals = [v for _, v in series.samples]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "min": min(vals), "max": max(vals), "mean": round(sum(vals) / len(vals), 3),
            "first": vals[0], "last": vals[-1], "delta": round(vals[-1] - vals[0], 3)}


def downsample(samples: list[tuple[float, float]], max_points: int = MAX_POINTS) -> list[tuple[float, float]]:
    if len(samples) <= max_points:
        return list(samples)
    step = (len(samples) - 1) / (max_points - 1)
    picked = [samples[round(i * step)] for i in range(max_points)]
    picked[-1] = samples[-1]
    return picked
