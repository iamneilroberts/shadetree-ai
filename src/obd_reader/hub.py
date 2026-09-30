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
        self._lock = threading.Lock()       # serialises start()
        self._data_lock = threading.Lock()  # guards the buffers: the sampler writes, viewers read
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._run_id = 0                    # changes on every start, so viewers can tell runs apart
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
            with self._data_lock:
                self._reset()
                self._run_id += 1
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
                    got = self._sweep(t, pids, now)
                    if self._stop.is_set():  # Stop pressed (possibly mid-sweep): end now, no "silent bus" message
                        break
                    if got:
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
        """Read every PID once, then publish the whole sweep at once (a viewer never sees half of one)."""
        rows = []
        for p in pids:
            if self._stop.is_set():  # a slow link must not delay Stop by a whole sweep
                return False
            v = read_pid_value(t, p)
            if v is not None:
                rows.append((p, v))
        if not rows:
            return False
        with self._data_lock:
            seq = self.seq + 1
            for p, v in rows:
                self._ch[p].append((seq, round(now, 3), v))
            self.seq = seq
            self._last_at = self._clock()
            self._sweep_t.append(now)
        return True

    def state(self, after: int = 0) -> dict:
        with self._data_lock:
            seq, t0, deadline, last_at = self.seq, self._t0, self._deadline, self._last_at
            status, message, hz, run = self.status, self.message, self.hz, self._run_id
            adapter, st = dict(self._adapter), list(self._sweep_t)
            # only sweeps up to `seq`: anything newer is not complete yet
            channels = {
                p: {"name": PIDS[p].name, "unit": PIDS[p].unit,
                    "samples": [[s, tt, v] for s, tt, v in d if after < s <= seq]}
                for p, d in self._ch.items()
            }
        now = (self._clock() - t0) if t0 is not None else 0.0
        measured = (len(st) - 1) / (st[-1] - st[0]) if len(st) >= 2 and st[-1] > st[0] else None
        return {
            "status": status, "message": message, "demo": self._sim is not None, "run": run,
            "seq": seq, "now": round(now, 3),
            "since_last_sample": None if last_at is None else round(self._clock() - last_at, 2),
            "hz": hz, "hz_measured": None if measured is None else round(measured, 2),
            "seconds_left": (max(0.0, round(deadline - self._clock(), 1))
                             if status == "running" and deadline else None),
            "adapter": adapter,
            "channels": channels,
        }

    def recent(self, seconds: float) -> dict:
        out: dict[str, dict] = {}
        with self._data_lock:
            snap = {p: list(d) for p, d in self._ch.items()}
        for p, rows in snap.items():
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
        with self._data_lock:
            if self.seq == 0:
                raise ValueError("nothing sampled yet")
            series = {p: Series(name=PIDS[p].name, unit=PIDS[p].unit,
                                samples=[(tt, v) for s, tt, v in d if s <= self.seq])
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
