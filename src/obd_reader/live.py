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
MIN_HZ = 0.1  # at most a 10 s pause between sweeps, so the adapter lock is never held for hours
MAX_POINTS = 120
_SILENT_SWEEPS = 2  # give up after this many sweeps in which no PID answered at all
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


def read_pid_value(transport: Transport, pid: str) -> float | int | None:
    """One Mode 01 request for an already-validated PID; None if no ECU answered it."""
    d = PIDS[pid]
    for payload in parse_all(transport.send(f"01{pid}"), 0x41):
        if len(payload) >= 2 + d.nbytes and payload[1] == int(pid, 16):
            return d.decode(payload[2 : 2 + d.nbytes])
    return None


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
    if not MIN_HZ <= hz <= MAX_HZ:
        raise LiveLimitError(f"hz must be between {MIN_HZ:g} and {MAX_HZ:g}")
    series = {p: Series(name=PIDS[p].name, unit=PIDS[p].unit) for p in pids}
    period, t0, silent = 1.0 / hz, clock(), 0
    while True:
        t = clock() - t0
        if t > seconds:
            break
        for p in pids:
            v = read_pid_value(transport, p)
            if v is not None:
                series[p].samples.append((round(t, 3), v))
        if any(s.samples for s in series.values()):
            silent = 0
        else:
            silent += 1
            if silent >= _SILENT_SWEEPS:  # car off or not answering: do not hold the adapter for the whole run
                break
        if t + period > seconds:  # the next sweep would start after the deadline
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
