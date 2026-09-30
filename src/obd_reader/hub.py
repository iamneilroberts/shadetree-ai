"""One sampler, many viewers: a background thread reads a fixed set of Mode 01 PIDs
through the Session (lock + gated transport + transcript) into ring buffers that the
console page and Claude's tools both read."""
import json
import math
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from obd_reader.adapter import identify
from obd_reader.live import MAX_HZ, MIN_HZ, LiveLimitError, read_pid_value, summarize, validate_pids
from obd_reader.pids import PIDS
from obd_reader.session import Session
from obd_reader.simulator import SimPort
from obd_reader.snapshot import LiveSample, Series

MAX_RUN_S = 1800.0
DEFAULT_PIDS = ["0C", "05", "06", "07", "08", "09", "10", "42"]
_SILENT_SWEEPS = 3
_LABEL_RE = re.compile(r"[a-z0-9-]{1,40}")


class HubBusy(RuntimeError):
    """The hub is already sampling."""


class LiveHub:
    def __init__(self, session: Session, *, sim: SimPort | None = None, max_buffer: int = 600,
                 clock: Callable[[], float] = time.monotonic):
        self._s, self._sim, self._max, self._clock = session, sim, max_buffer, clock
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reset()

    def _reset(self) -> None:
        self.status, self.message, self.seq, self.hz = "idle", None, 0, None
        self._ch: dict[str, deque] = {}
        self._sweep_t: deque = deque(maxlen=12)
        self._t0 = self._last_at = self._deadline = None
        self._adapter: dict = {"chip": None, "ati": None, "protocol": None}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, pids: list[str], hz: float = 2.5, seconds: float = 600.0) -> None:
        pids = validate_pids(pids)
        if not (isinstance(hz, (int, float)) and math.isfinite(hz) and MIN_HZ <= hz <= MAX_HZ):
            raise LiveLimitError(f"hz must be between {MIN_HZ:g} and {MAX_HZ:g}")
        if not (isinstance(seconds, (int, float)) and math.isfinite(seconds) and 0 < seconds <= MAX_RUN_S):
            raise LiveLimitError(f"seconds must be in (0, {MAX_RUN_S:g}]")
        with self._lock:
            if self.running:
                raise HubBusy("the console is already sampling; stop it first")
            self._reset()
            self.hz, self.status = float(hz), "running"
            self._ch = {p: deque(maxlen=self._max) for p in pids}
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, args=(pids, float(hz), float(seconds)), daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout)

    def _run(self, pids: list[str], hz: float, seconds: float) -> None:
        try:
            with self._s.connection("console") as t:
                a = identify(t)
                self._adapter.update(chip=a.chip, ati=a.ati)
                t0 = self._clock()
                self._t0, self._deadline = t0, t0 + seconds
                silent, period = 0, 1.0 / hz
                while not self._stop.is_set():
                    now = self._clock() - t0
                    if now > seconds:
                        self.message = f"auto-stopped after {seconds:g} s"
                        break
                    if self._sweep(t, pids, now):
                        silent = 0
                        if self._adapter["protocol"] is None:
                            dp = (t.send("ATDP") or [None])[0]
                            self._adapter["protocol"] = dp.removeprefix("AUTO, ") if dp else None
                    else:
                        silent += 1
                        if silent >= _SILENT_SWEEPS:
                            self.message = "no data: the ECU did not answer any PID (car off or not connected?)"
                            break
                    self._stop.wait(max(0.0, period - (self._clock() - t0 - now)))
        except Exception as e:  # never let the thread die silently: report it and free the adapter
            self.status, self.message = "error", f"{type(e).__name__}: {e}"
        finally:
            if self.status != "error":
                self.status = "stopped"

    def _sweep(self, t, pids: list[str], now: float) -> bool:
        seq, got = self.seq + 1, False
        for p in pids:
            v = read_pid_value(t, p)
            if v is not None:
                self._ch[p].append((seq, round(now, 3), v))
                got = True
        if got:
            self.seq = seq
            self._last_at = self._clock()
            self._sweep_t.append(now)
        return got

    def state(self, after: int = 0) -> dict:
        now = (self._clock() - self._t0) if self._t0 is not None else 0.0
        st = list(self._sweep_t)
        measured = (len(st) - 1) / (st[-1] - st[0]) if len(st) >= 2 and st[-1] > st[0] else None
        return {
            "status": self.status, "message": self.message, "demo": self._sim is not None,
            "seq": self.seq, "now": round(now, 3),
            "since_last_sample": None if self._last_at is None else round(self._clock() - self._last_at, 2),
            "hz": self.hz, "hz_measured": None if measured is None else round(measured, 2),
            "seconds_left": (max(0.0, round(self._deadline - self._clock(), 1))
                             if self.status == "running" and self._deadline else None),
            "adapter": dict(self._adapter),
            "channels": {
                p: {"name": PIDS[p].name, "unit": PIDS[p].unit,
                    "samples": [[s, tt, v] for s, tt, v in list(d) if s > after]}
                for p, d in self._ch.items()
            },
        }

    def recent(self, seconds: float) -> dict:
        out: dict[str, dict] = {}
        for p, d in self._ch.items():
            rows = list(d)
            if not rows:
                out[p] = {"name": PIDS[p].name, "unit": PIDS[p].unit, "stats": {"n": 0}, "latest": None}
                continue
            cut = rows[-1][1] - seconds
            win = [(tt, v) for _, tt, v in rows if tt >= cut]
            out[p] = {"name": PIDS[p].name, "unit": PIDS[p].unit,
                      "stats": summarize(Series(name=PIDS[p].name, unit=PIDS[p].unit, samples=win)),
                      "latest": rows[-1][2]}
        return out

    def save_run(self, label: str) -> Path:
        if not _LABEL_RE.fullmatch(label):
            raise ValueError("label must be 1-40 chars of [a-z0-9-]")
        if self.seq == 0:
            raise ValueError("nothing sampled yet")
        series = {p: Series(name=PIDS[p].name, unit=PIDS[p].unit, samples=[(tt, v) for _, tt, v in d])
                  for p, d in self._ch.items()}
        ls = LiveSample(duration_s=self.state()["now"], rate_hz=self.hz or 0.0, series=series)
        rdir = Path(self._s.config.home) / "runs"
        rdir.mkdir(parents=True, exist_ok=True)
        path = rdir / f"{datetime.now(timezone.utc):%Y-%m-%dT%H-%M-%SZ}-{label}.json"
        with open(path, "x", encoding="utf-8") as fh:
            json.dump({"kind": "live_run", "demo": self._sim is not None, "adapter": self._adapter,
                       "live_sample": ls.model_dump(mode="json")}, fh, indent=2)
        return path

    def set_sim(self, scenario: str | None = None, rev: bool | None = None) -> None:
        if self._sim is None:
            raise ValueError("simulator controls exist only in demo mode")
        if scenario is not None:
            self._sim.set_scenario(scenario)
        if rev is not None:
            self._sim.rev = bool(rev)
