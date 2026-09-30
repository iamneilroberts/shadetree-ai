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
from obd_reader.dtc_text import describe
from obd_reader.elm import decode_supported, parse_all
from obd_reader.live import MAX_HZ, MAX_PIDS, MIN_HZ, LiveLimitError, read_pid_value, summarize, validate_pids
from obd_reader.mode06 import read_all as read_mode06
from obd_reader.pids import PIDS
from obd_reader.profiles import ProfileStore
from obd_reader.scanner import _dtcs
from obd_reader.session import Session
from obd_reader.simulator import SimPort
from obd_reader.snapshot import VIN_RE, LiveSample, Series
from obd_reader.vehicle import vehicle_key

MAX_RUN_S = 1800.0
DEFAULT_PIDS = ["0C", "05", "06", "07", "08", "09", "0B", "42"]
# Readings added to a run, in order of usefulness, for whichever of them the car says it supports.
# The core channels are read every sweep; these rotate _EXTRAS_PER_SWEEP at a time so the fast ones stay fast.
EXTRA_PIDS = ["04", "11", "0D", "0E", "43", "44", "0F", "5C", "46", "33", "2F", "24", "28", "15", "19", "3C", "3D",
              "3E", "3F", "2C", "2D", "2E", "23", "47", "49", "4A", "62", "63", "8E", "55", "56", "57", "58", "03",
              "1C", "51", "1F", "30", "31", "21", "A6"]
_EXTRAS_PER_SWEEP = 4
_SILENT_SWEEPS = 3
_UNSUPPORTED_SWEEPS = 3  # a PID that gets no value in this many sweeps in a row while others answer is dropped
_LABEL_RE = re.compile(r"[a-z0-9-]{1,40}")


class HubBusy(RuntimeError):
    """The hub is already sampling."""


class LiveHub:
    def __init__(self, session: Session, *, sim: SimPort | None = None, max_buffer: int = 600,
                 clock: Callable[[], float] = time.monotonic):
        self._s, self._sim, self._max, self._clock = session, sim, max_buffer, clock
        self._lock = threading.Lock()       # serialises start()
        self._profiles = ProfileStore(session.config.home)
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
        self._codes: dict = {"read": False, "note": None}
        self._unsupported: list[str] = []
        self._missed: set[str] = set()
        self._extras: list[str] = []
        self._m06: dict = {"read": False, "note": None, "mids": [], "results": []}
        self._vehicle: dict | None = None
        self._key: str | None = None
        self._supported: set[str] = set()
        self._prior: dict | None = None

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
                active, misses = list(pids), dict.fromkeys(pids, 0)
                extras, rot = self._discover_extras(t, pids), 0
                while not self._stop.is_set():
                    now = self._clock() - t0
                    if now > seconds:
                        self.message = f"auto-stopped after {seconds:g} s"
                        break
                    batch = [extras[(rot + i) % len(extras)] for i in range(min(_EXTRAS_PER_SWEEP, len(extras)))]
                    rot = (rot + _EXTRAS_PER_SWEEP) % len(extras) if extras else 0
                    got = self._sweep(t, active + batch, now)
                    if self._stop.is_set():  # Stop pressed (possibly mid-sweep): end now, no "silent bus" message
                        break
                    if got:
                        silent = 0
                        for p in list(active):
                            misses[p] = misses[p] + 1 if p in self._missed else 0
                            if misses[p] >= _UNSUPPORTED_SWEEPS:
                                active.remove(p)
                                with self._data_lock:
                                    self._unsupported.append(p)
                        if self._adapter["protocol"] is None:
                            dp = (t.send("ATDP") or [None])[0]
                            self._adapter["protocol"] = dp.removeprefix("AUTO, ") if dp else None
                            self._read_codes(t)
                            if not self._stop.is_set():
                                prior = self._read_identity(t)
                                for p in (prior["unsupported"] if prior else []):
                                    if p in misses:
                                        misses[p] = _UNSUPPORTED_SWEEPS - 1
                            if not self._stop.is_set():
                                self._read_mode06(t)
                    else:
                        silent += 1
                        if silent >= _SILENT_SWEEPS:
                            self.message = "no data: the ECU did not answer any PID (car off or not connected?)"
                            break
                    self._stop.wait(max(0.0, period - (self._clock() - t0 - now)))
        except Exception as e:  # never let the thread die silently: report it and free the adapter
            self.status, self.message = "error", f"{type(e).__name__}: {e}"
        finally:
            self._save_profile()
            if self.status != "error":
                self.status = "stopped"

    def _discover_extras(self, t, core: list[str]) -> list[str]:
        """Ask the car which Mode 01 PIDs it supports and pick the extra readings it can give, up to the PID cap."""
        room = MAX_PIDS - len(core)
        if room <= 0:
            return []
        supported: set[str] = set()
        base = 0x00
        while base <= 0xC0 and not self._stop.is_set():
            found: set[str] = set()
            for p in parse_all(t.send(f"01{base:02X}"), 0x41):
                if len(p) >= 6 and p[1] == base:
                    found.update(decode_supported(base, p[2:6]))
            if not found:
                break
            supported |= found
            if f"{base + 0x20:02X}" not in found:
                break
            base += 0x20
        extras = [p for p in EXTRA_PIDS if p in supported and p in PIDS and p not in core][:room]
        with self._data_lock:
            self._extras, self._supported = extras, supported
            for p in extras:
                self._ch[p] = deque(maxlen=self._max)
        return extras

    def _read_identity(self, t) -> dict | None:
        """Name the class of car from a partial VIN, once per run (CAN only), and load what past runs learned.
        The VIN itself is never kept."""
        proto = self._adapter["protocol"] or ""
        if self._sim is None and "15765" not in proto:
            with self._data_lock:
                self._vehicle = {"key": None, "known": False, "runs": 0,
                                 "note": f"vehicle id not supported yet on {proto or 'this'} protocol"}
            return None
        cands = [p[3:20].decode("ascii", errors="replace") for p in parse_all(t.send("0902"), 0x49)]
        key = next((vehicle_key(c) for c in cands if VIN_RE.fullmatch(c)), None)
        if key is None:
            with self._data_lock:
                self._vehicle = {"key": None, "known": False, "runs": 0, "note": "the car did not report a VIN"}
            return None
        prior = self._profiles.load(key)
        with self._data_lock:
            self._key, self._prior = key, prior
            self._vehicle = {"key": key, "known": prior is not None, "runs": prior["runs"] if prior else 0, "note": None}
        return prior

    def _save_profile(self) -> None:
        if not self._key or self.seq == 0:
            return
        prior = self._prior
        profile = {"schema": 1, "key": self._key, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "runs": (prior["runs"] if prior else 0) + 1, "protocol": self._adapter["protocol"],
                   "supported_pids": sorted(self._supported), "unsupported": sorted(set(self._unsupported)),
                   "extras": list(self._extras)}
        try:
            self._profiles.save(self._key, profile)
        except OSError as e:
            self.message = self.message or f"could not save the car profile: {e}"

    def _read_mode06(self, t) -> None:
        """On-board test results, once per run (CAN only: the layout was verified on CAN)."""
        proto = self._adapter["protocol"] or ""
        if self._sim is None and "15765" not in proto:
            with self._data_lock:
                self._m06 = {"read": False, "note": f"Mode 06 not supported yet on {proto or 'this'} protocol",
                             "mids": [], "results": []}
            return
        mids, res = read_mode06(t, stop=self._stop.is_set)
        with self._data_lock:
            self._m06 = {"read": True, "note": None, "mids": mids, "results": [r.model_dump() for r in res]}

    def _read_codes(self, t) -> None:
        """Modes 03/07/0A and the lamp bit, once per run (CAN only: other layouts would decode wrongly)."""
        proto = self._adapter["protocol"] or ""
        if self._sim is None and "15765" not in proto:
            with self._data_lock:
                self._codes = {"read": False, "note": f"trouble codes not supported yet on {proto or 'this'} protocol"}
            return
        out = {}
        for k, cmd, sid in (("stored", "03", 0x43), ("pending", "07", 0x47), ("permanent", "0A", 0x4A)):
            if self._stop.is_set():  # Stop pressed: do not finish reading the lists
                return
            out[k] = [{"code": d.code, **describe(d.code)} for d in _dtcs(t, cmd, sid)]
        status = [p for p in parse_all(t.send("0101"), 0x41) if len(p) >= 3 and p[1] == 0x01]
        with self._data_lock:
            self._codes = {"read": True, "note": None, **out, "mil": any(p[2] & 0x80 for p in status)}

    def _sweep(self, t, pids: list[str], now: float) -> bool:
        """Read every PID once, then publish the whole sweep at once (a viewer never sees half of one)."""
        rows = []
        self._missed = set()
        for p in pids:
            if self._stop.is_set():  # a slow link must not delay Stop by a whole sweep
                return False
            v = read_pid_value(t, p)
            if v is not None:
                rows.append((p, v))
            else:
                self._missed.add(p)
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
            adapter, st, codes = dict(self._adapter), list(self._sweep_t), dict(self._codes)
            unsupported, extras, m06 = list(self._unsupported), list(self._extras), dict(self._m06)
            vehicle = None if self._vehicle is None else dict(self._vehicle)
            # only sweeps up to `seq`: anything newer is not complete yet
            channels = {
                p: {"name": PIDS[p].name, "unit": PIDS[p].unit,
                    "labels": None if PIDS[p].labels is None else {str(k): v for k, v in PIDS[p].labels.items()},
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
            "adapter": adapter, "codes": codes, "unsupported": unsupported,
            "extras": extras, "mode06": m06, "vehicle": vehicle,
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
