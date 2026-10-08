"""One sampler, many viewers: a background thread reads a fixed set of Mode 01 PIDs
through the Session (lock + gated transport + transcript) into ring buffers that the
console page and Claude's tools both read."""
import bisect
import json
import math
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from obd_reader.adapter import fallback_search, identify
from obd_reader.dtc_text import describe
from obd_reader.elm import classify, decode_dtc_list, decode_supported, is_legacy, parse_all, parse_vin_legacy
from obd_reader.live import MAX_HZ, MAX_PIDS, MIN_HZ, LiveLimitError, read_pid_value, summarize, validate_pids
from obd_reader.mode06 import read_all as read_mode06, read_all_legacy as read_mode06_legacy
from obd_reader.pids import PIDS, pid_label
from obd_reader.profiles import ProfileStore
from obd_reader.quirks import QuirkStore, applied as quirks_applied
from obd_reader.readiness import parse_readiness
from obd_reader.replay_run import Run
from obd_reader.scanner import read_freeze_frame
from obd_reader.session import Session
from obd_reader.simulator import SimPort
from obd_reader.snapshot import VIN_RE, LiveSample, Series
from obd_reader.vehicle import make_of, vehicle_key
from obd_reader import vin_decode

MAX_RUN_S = 1800.0
DEFAULT_PIDS = ["0C", "05", "06", "07", "08", "09", "0B", "42"]
# Readings added to a run, in order of usefulness, for whichever of them the car says it supports.
# The core channels are read every sweep; these rotate _EXTRAS_PER_SWEEP at a time so the fast ones stay fast.
EXTRA_PIDS = ["04", "11", "0D", "0E", "43", "44", "0F", "10", "5C", "46", "33", "2F", "24", "28", "15", "19", "14",
              "18", "3C", "3D", "3E", "3F", "2C", "2D", "2E", "23", "47", "49", "4A", "62", "63", "8E", "55", "56", "57",
              "58", "03", "1C", "51", "1F", "30", "31", "21", "A6", "66", "67", "68"]
# A car that lacks coolant (05), intake air (0F) or MAF (10) may report the same reading as sensor 1 of the
# multi-sensor PIDs: a core, focus or extra PID the car's bitmap does not list is replaced by its fallback here.
FALLBACK_PIDS = {"05": "67", "0F": "68", "10": "66"}
_EXTRAS_PER_SWEEP = 4
# Capture level max (was "Capture all supported"): every decodable Mode 01 PID the car reports, in two tiers. The fast tier is read every
# sweep (the run's rate, 2.5 Hz from the page); the rest rotate, enough per sweep for about SLOW_HZ each, at most
# SLOW_MAX_PER_SWEEP so the fast tier keeps its cadence. Real-adapter throughput is unverified.
FAST_PIDS = ["0C", "0D", "04", "11"]
SLOW_HZ = 0.25
SLOW_MAX_PER_SWEEP = 4
# Capture level: min = core PIDs + the scenario's supported PIDs, no rotating extras; std = core + rotating extras
# (the normal run); max = every decodable PID the car reports. "all" is an alias for max.
CAPTURE_MODES = ("min", "std", "max", "all")
_SILENT_SWEEPS = 3
_UNSUPPORTED_SWEEPS = 3  # a PID that gets no value in this many sweeps in a row while others answer is dropped
_SPEEDS = (0.5, 1.0, 2.0, 4.0, 8.0)
_REPLAY_TICK = 0.05
_REPLAY_WINDOW_S = 60.0
_LABEL_RE = re.compile(r"[a-z0-9-]{1,40}")
_PID_RE = re.compile(r"[0-9A-Fa-f]{2}")
MAX_FOCUS = 8  # a scenario's gauges


def slow_per_sweep(n_slow: int, hz: float) -> int:
    """How many slow-tier PIDs to read each sweep so each comes round at about SLOW_HZ, within the cap."""
    return 0 if n_slow <= 0 else min(SLOW_MAX_PER_SWEEP, max(1, math.ceil(n_slow * SLOW_HZ / hz)))


class HubBusy(RuntimeError):
    """The hub is already sampling."""


class LiveHub:
    def __init__(self, session: Session, *, sim: SimPort | None = None, max_buffer: int = 600,
                 clock: Callable[[], float] = time.monotonic, autosave: bool | None = None):
        self._s, self._sim, self._max, self._clock = session, sim, max_buffer, clock
        self._autosave = sim is None if autosave is None else autosave  # a demo run is not worth a file
        self._unsaved = False               # the last run ended with samples that could not be saved
        self._lock = threading.Lock()       # serialises start()
        self._profiles = ProfileStore(session.config.home)
        self._quirk_store = QuirkStore(session.config.home)
        self._last_key: str | None = None   # the car the last run named; kept across runs for the quirks protocol hint
        self._data_lock = threading.Lock()  # guards the buffers: the sampler writes, viewers read
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._run_id = 0                    # changes on every start, so viewers can tell runs apart
        self._focus: list[str] = []         # the PIDs of the scenario the page shows: read first among the extras
        self._focus_ver = 0                 # bumped on every change, so the sampler re-plans its extras
        self._reset()

    def _reset(self) -> None:
        self.status, self.message, self.seq, self.hz = "idle", None, 0, None
        self._ch: dict[str, deque] = {}      # the newest max_buffer samples per channel: what the page and tools read
        self._full: dict[str, list] = {}     # every sample of the run: what a saved run is written from
        self._stats: dict[str, list] = {}    # [n, mean, m2, min, max, t_min, t_max, t_last] per channel over the run (a replay: the whole file)
        self._ptimes: dict[str, list] = {}   # a replay: every sample time per channel, for the last-seen age at the replay clock
        self._sweep_t: deque = deque(maxlen=12)
        self._t0 = self._last_at = self._deadline = None
        self._adapter: dict = {"chip": None, "ati": None, "protocol": None}
        self._codes: dict = {"read": False, "note": None}
        self._ready: dict = {"read": False, "note": None}   # Mode 01 PID 01: lamp, code count, monitors (read with the codes)
        self._ff: dict = {"read": False, "note": None}      # Mode 02 frame 0 (read after the codes, only with a stored code)
        self._unsupported: list[str] = []
        self._missed: set[str] = set()
        self._extras: list[str] = []
        self._fallbacks: dict[str, str] = {}  # core or focus PID the car lacks -> the fallback PID read in its place
        self._capture: str | None = None   # the last started run's level (min | std | max); None before any run
        self._tiers: dict | None = None      # capture-all runs: {"fast", "slow", "slow_per_sweep"}
        self._m06: dict = {"read": False, "note": None, "mids": [], "results": []}
        self._vehicle: dict | None = None
        self._key: str | None = None
        self._name: dict | None = None       # the make, model and year saved in this car's profile, if any
        self._supported: set[str] = set()
        self._prior: dict | None = None
        self._quirks: dict | None = None     # the quirks file applied to this run (quirks.applied + protocol_pinned, hz_capped)
        self._lie: set[str] = set()          # its pids_lie: left out of the extras
        self._saved: tuple[Path, int] | None = None  # (file, seq) of the last save of this run
        self._transcript: str | None = None  # this run's raw transcript, relative to home
        self._replay: dict | None = None     # while a saved run is loaded: name, run, pos, speed, playing, ended, i

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def runs_dir(self) -> Path:
        return Path(self._s.config.home) / "runs"

    def _meta(self, p: str):
        d = PIDS.get(p)
        if d is not None:
            return d.name, d.unit, None if d.labels is None else {str(k): v for k, v in d.labels.items()}
        name, unit = (self._replay["run"].names.get(p) if self._replay else None) or (p, None)
        return name, unit, None

    def start(self, pids: list[str], hz: float = 2.5, seconds: float = 600.0, capture: str = "std") -> None:
        pids = validate_pids(pids)
        if not isinstance(capture, str) or capture not in CAPTURE_MODES:
            raise LiveLimitError("capture must be min, std or max")
        if not (isinstance(hz, (int, float)) and math.isfinite(hz) and MIN_HZ <= hz <= MAX_HZ):
            raise LiveLimitError(f"hz must be between {MIN_HZ:g} and {MAX_HZ:g}")
        if not (isinstance(seconds, (int, float)) and math.isfinite(seconds) and 0 < seconds <= MAX_RUN_S):
            raise LiveLimitError(f"seconds must be in (0, {MAX_RUN_S:g}]")
        with self._lock:
            if self._replay is not None:
                raise HubBusy("a replay is loaded: exit it to sample live")
            if self.running:
                raise HubBusy("the console is already sampling; stop it first")
            if self._unsaved:  # starting clears the last run: say so once, then let the person decide
                self._unsaved = False
                raise HubBusy("the last run could not be saved and starting clears it: press Save run, "
                              "or press Start again to discard it")
            with self._data_lock:
                self._reset()
                self._run_id += 1
                self.hz, self.status = float(hz), "running"
                self._capture = "max" if capture == "all" else capture
                self._ch = {p: deque(maxlen=self._max) for p in pids}
                self._full = {p: [] for p in pids}
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, args=(pids, float(hz), float(seconds), self._capture), daemon=True)
            self._thread.start()

    def set_focus(self, pids) -> None:
        """The page's scenario PIDs (up to 8 two-hex-digit ids). Only the ones the car's support bitmap lists and the
        decoder table knows are ever read, as Mode 01 extras through the same gated path; the rest are just reported."""
        if not isinstance(pids, list) or len(pids) > MAX_FOCUS or not all(isinstance(p, str) and _PID_RE.fullmatch(p) for p in pids):
            raise LiveLimitError(f"focus is a list of at most {MAX_FOCUS} two-digit hex PIDs")
        with self._data_lock:
            self._focus = list(dict.fromkeys(p.upper() for p in pids))
            self._focus_ver += 1

    def stop(self, timeout: float = 5.0) -> None:
        if self._replay is not None:
            return self.exit_replay()
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout)

    def start_replay(self, run: Run, name: str, playing: bool = True) -> None:
        with self._lock:
            if self._replay is None and self.running:
                raise HubBusy("the console is already sampling; stop it first")
            if self._unsaved:
                self._unsaved = False
                raise HubBusy("the last run could not be saved and loading a replay clears it: press Save run, "
                              "or load again to discard it")
            if self._replay is not None:
                self._join_player()
            with self._data_lock:
                self._reset()
                self._run_id += 1
                self.status, self.hz = "running", (run.rate_hz or None)
                self._adapter = {"chip": None, "ati": "replay", "protocol": run.protocol}
                self._codes = run.codes or {"read": False, "note": "not stored in this run"}
                self._m06 = run.mode06 or {"read": False, "note": "not stored in this run", "mids": [], "results": []}
                self._ready = run.readiness or {"read": False, "note": "not in this recording"}
                self._ff = run.freeze_frame or {"read": False, "note": "not in this recording"}
                self._vehicle = run.vehicle
                self._ch = {p: deque(maxlen=self._max) for p in run.names}
                for t, vals in run.sweeps:
                    for p, v in vals.items():
                        self._add_stat(p, v, t)
                        self._ptimes.setdefault(p, []).append(t)
                self._replay = {"name": name, "run": run, "pos": 0.0, "speed": 1.0, "playing": bool(playing), "ended": False, "i": 0}
            self._stop.clear()
            self._thread = threading.Thread(target=self._replay_loop, daemon=True)
            self._thread.start()

    def _join_player(self) -> None:
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(5.0)

    def exit_replay(self) -> None:
        with self._lock:
            if self._replay is None:
                return
            self._join_player()
            with self._data_lock:
                self._reset()
                self._run_id += 1
            self._stop.clear()

    def _replay_loop(self) -> None:
        last = self._clock()
        while not self._stop.is_set():
            now = self._clock()
            dt, last = now - last, now
            with self._data_lock:
                rp = self._replay
                playing = rp is not None and rp["playing"]
            if playing:
                self._replay_advance(dt)
            self._stop.wait(_REPLAY_TICK)

    def _replay_advance(self, dt: float) -> None:
        with self._data_lock:
            rp = self._replay
            if rp is None:
                return
            run = rp["run"]
            rp["pos"] = min(run.duration, rp["pos"] + dt * rp["speed"])
            self._publish_until(rp)
            if rp["pos"] >= run.duration:
                rp["playing"], rp["ended"] = False, True

    def _publish_until(self, rp: dict) -> None:
        """Publish every sweep up to the replay position (the caller holds the data lock)."""
        run, i = rp["run"], rp["i"]
        while i < len(run.sweeps) and run.sweeps[i][0] <= rp["pos"]:
            t, vals = run.sweeps[i]
            i += 1
            self.seq += 1
            for p, v in vals.items():
                self._ch[p].append((self.seq, t, v))
            self._sweep_t.append(t)
            self._last_at = self._clock()
        rp["i"] = i

    def _seek_locked(self, rp: dict, pos: float) -> None:
        run = rp["run"]
        self._ch = {p: deque(maxlen=self._max) for p in run.names}
        self._sweep_t.clear()
        self.seq = 0
        self._run_id += 1
        rp["pos"], rp["ended"] = pos, False
        rp["i"] = run.first_in_window(pos, _REPLAY_WINDOW_S)
        self._publish_until(rp)
        if pos >= run.duration:
            rp["playing"], rp["ended"] = False, True

    def replay_control(self, action: str, pos: float | None = None, speed: float | None = None) -> None:
        try:
            self._replay_control(action, pos, speed)
        except OverflowError:
            raise ValueError("a number is out of range") from None

    def _replay_control(self, action: str, pos, speed) -> None:
        with self._data_lock:
            rp = self._replay
            if rp is None:
                raise ValueError("no replay is loaded")
            run = rp["run"]
            if action == "pause":
                rp["playing"] = False
            elif action == "play":
                if rp["ended"]:
                    self._seek_locked(rp, 0.0)
                rp["playing"] = True
            elif action == "restart":
                self._seek_locked(rp, 0.0)
                rp["playing"] = True
            elif action == "seek":
                if isinstance(pos, bool) or not isinstance(pos, (int, float)) or not math.isfinite(pos):
                    raise ValueError("pos must be a number")
                self._seek_locked(rp, min(max(float(pos), 0.0), run.duration))
            elif action == "speed":
                if isinstance(speed, bool) or not isinstance(speed, (int, float)) or float(speed) not in _SPEEDS:
                    raise ValueError("speed must be one of 0.5, 1, 2, 4, 8")
                rp["speed"] = float(speed)
            else:
                raise ValueError("unknown replay action")

    def _run(self, pids: list[str], hz: float, seconds: float, level: str = "std") -> None:
        try:
            # the car the last run named: its quirks protocol is tried instead of automatic search (the fallback
            # search still runs if that finds nothing, so a different car is not locked out)
            pin = self._quirk_store.load(self._last_key)
            pinned = pin is not None and bool(pin[0].protocol) and self._s.config.protocol == "0"
            if pinned:
                with self._data_lock:
                    self._quirks = {**quirks_applied(*pin), "protocol_pinned": True, "hz_capped": False}
            with self._s.connection("console", **({"quirks": pin[0]} if pinned else {})) as t:
                if t.transcript_path is not None:  # relative, so a shared run file does not carry the home path
                    self._transcript = t.transcript_path.relative_to(self._s.config.home).as_posix()
                a = identify(t)
                self._adapter.update(chip=a.chip, ati=a.ati)
                t0 = self._clock()
                self._t0, self._deadline = t0, t0 + seconds
                silent, period = 0, 1.0 / hz
                fv = self._focus_ver
                plan = self._capture_plan(t, hz) if level == "max" else None
                if plan:
                    active, extras, per = plan
                else:
                    active, extras, per = list(pids), self._discover_extras(t, pids, level == "min"), MAX_PIDS if level == "min" else _EXTRAS_PER_SWEEP
                misses, rot = dict.fromkeys(active, 0), 0
                while not self._stop.is_set():
                    now = self._clock() - t0
                    if now > seconds:
                        self.message = f"auto-stopped after {seconds:g} s"
                        break
                    if not plan and fv != self._focus_ver:  # another scenario on the page: its supported PIDs lead the extras
                        fv, extras, rot = self._focus_ver, self._plan_extras(pids, level == "min"), 0
                    batch = [extras[(rot + i) % len(extras)] for i in range(min(per, len(extras)))]
                    rot = (rot + per) % len(extras) if extras else 0
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
                            prior = self._read_identity(t)  # first: the car's make picks which code meanings apply
                            lie, cap = self._apply_quirks()
                            for p in (prior["unsupported"] if prior else []) + lie:
                                if p in misses:
                                    misses[p] = _UNSUPPORTED_SWEEPS - 1
                            if cap is not None:
                                period = 1.0 / cap
                            if lie and not plan:
                                fv = -1  # re-plan the extras without them
                            if not self._stop.is_set():
                                self._read_codes(t)
                            if not self._stop.is_set():
                                self._read_freeze_frame(t)
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
            self._autosave_run()
            if self.status != "error":
                self.status = "stopped"

    def _discover_extras(self, t, core: list[str], focus_only: bool = False) -> list[str]:
        """Ask the car which Mode 01 PIDs it supports and pick the extra readings it can give, up to the PID cap."""
        if MAX_PIDS - len(core) <= 0:
            return []
        supported = self._discover_supported(t)
        with self._data_lock:
            self._supported = supported
        return self._plan_extras(core, focus_only)

    def _plan_extras(self, core: list[str], focus_only: bool = False) -> list[str]:
        """The scenario's supported PIDs first, then EXTRA_PIDS in order, up to the PID cap. A channel no longer read
        keeps its samples (it goes stale on the page). focus_only (capture level min): no EXTRA_PIDS; a live run's channels are decoder-table PIDs, at most 59 < 64."""
        with self._data_lock:
            ok = lambda p: p in self._supported and p in PIDS and p not in core and p not in self._lie  # noqa: E731
            fb = lambda p: FALLBACK_PIDS[p] if p in FALLBACK_PIDS and p not in self._supported else p  # noqa: E731
            lead = [fb(p) for p in core if fb(p) != p] + [fb(p) for p in self._focus]
            extras = list(dict.fromkeys([p for p in lead if ok(p)] + ([] if focus_only else [fb(p) for p in EXTRA_PIDS if ok(fb(p))])))[:MAX_PIDS - len(core)]
            self._extras = extras
            self._fallbacks = {p: fb(p) for p in [*core, *self._focus] if fb(p) != p and fb(p) in extras}
            for p in extras:
                if p not in self._ch:
                    self._ch[p], self._full[p] = deque(maxlen=self._max), []
        return extras

    def _capture_plan(self, t, hz: float) -> tuple[list[str], list[str], int] | None:
        """Capture level max: the fast tier and every other decodable PID the car reports, as the run's channels.
        None when the car gives no support bitmap (the run then reads the PIDs it was started with)."""
        supported = self._discover_supported(t)
        fast = [p for p in FAST_PIDS if p in supported]
        slow = sorted(p for p in supported if p in PIDS and p not in fast)
        if not fast and not slow:
            return None
        per = slow_per_sweep(len(slow), hz)
        with self._data_lock:
            self._extras, self._supported = slow, supported
            self._tiers = {"fast": fast, "slow": slow, "slow_per_sweep": per}
            self._ch = {p: deque(maxlen=self._max) for p in fast + slow}
            self._full = {p: [] for p in fast + slow}
        return fast, slow, per

    def _discover_supported(self, t, retry: bool = True) -> set[str]:
        """The Mode 01 PIDs the car says it supports, from the 0100/0120/... bitmaps."""
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
        if not supported and retry and self._sim is None and self._s.config.protocol == "0" and not self._stop.is_set():
            # automatic search can miss a bus that answers when pinned (a J1850 VPW truck did)
            if fallback_search(t):
                return self._discover_supported(t, retry=False)
        return supported

    @staticmethod
    def _decodable(proto: str) -> bool:
        """CAN or a named legacy bus: the protocols whose code and VIN layouts are decoded."""
        return "15765" in proto or is_legacy(proto)

    def _read_identity(self, t) -> dict | None:
        """Name the class of car from a partial VIN, once per run (CAN or a legacy bus), and load what past runs
        learned. The VIN itself is never kept."""
        proto = self._adapter["protocol"] or ""
        if self._sim is None and not self._decodable(proto):
            with self._data_lock:
                self._vehicle = {"key": None, "known": False, "runs": 0,
                                 "note": f"vehicle id not supported yet on {proto or 'this'} protocol"}
            return None
        if is_legacy(proto):
            cands = parse_vin_legacy(t.send("0902"))
        else:
            cands = [p[3:20].decode("ascii", errors="replace") for p in parse_all(t.send("0902"), 0x49)]
        key = next((vehicle_key(c) for c in cands if VIN_RE.fullmatch(c)), None)
        if key is None:
            with self._data_lock:
                self._vehicle = {"key": None, "known": False, "runs": 0, "note": "the car did not report a VIN"}
            return None
        prior = self._profiles.load(key)
        with self._data_lock:
            self._key, self._prior, self._last_key = key, prior, key
            self._name = {k: prior[k] for k in ("make", "model", "year")} if prior and "make" in prior else None
            self._vehicle = {"key": key, "known": bool(prior and prior["runs"]), "runs": prior["runs"] if prior else 0, "note": None}
        return prior

    def _apply_quirks(self) -> tuple[list[str], float | None]:
        """The quirks file for the car just named (key before WMI, quirks-local/ before quirks/). Hints, never decisions:
        its pids_lie leave the extras and get one silent sweep, not three, before they are dropped (one that answers
        stays); its max_hz caps the sweep rate. Returns (pids_lie, the cap if it lowered the rate)."""
        found = self._quirk_store.load(self._key)
        if found is None:
            return [], None
        q, path = found
        info = quirks_applied(q, path)
        cap = q.max_hz if q.max_hz is not None and self.hz and q.max_hz < self.hz else None
        with self._data_lock:
            prev = self._quirks
            self._lie = set(q.pids_lie)
            if cap is not None:
                self.hz = cap
            self._quirks = {**info, "protocol_pinned": bool(prev and prev["protocol_pinned"] and prev["file"] == info["file"]),
                            "hz_capped": cap is not None}
        return list(q.pids_lie), cap

    def _save_profile(self) -> None:
        if not self._key or self.seq == 0:
            return
        prior = self._prior
        profile = {"schema": 1, "key": self._key, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "runs": (prior["runs"] if prior else 0) + 1, "protocol": self._adapter["protocol"],
                   "supported_pids": sorted(self._supported), "unsupported": sorted(set(self._unsupported)),
                   "extras": list(self._extras), **(self._name or {})}
        try:
            self._profiles.save(self._key, profile)
        except OSError as e:
            self.message = self.message or f"could not save the car profile: {e}"

    def _read_mode06(self, t) -> None:
        """On-board test results, once per run: the CAN layout, or the one-limit legacy layout (`layout: "legacy"`,
        rows never judged pass or fail) on J1850, ISO 9141 and KWP."""
        proto = self._adapter["protocol"] or ""
        if self._sim is None and is_legacy(proto):
            tids, lres = read_mode06_legacy(t, stop=self._stop.is_set)
            with self._data_lock:
                self._m06 = ({"read": True, "note": None, "layout": "legacy", "mids": tids,
                              "results": [r.model_dump() for r in lres]} if tids else
                             {"read": False, "note": "the car did not answer Mode 06 (no supported tests reported)",
                              "mids": [], "results": []})
            return
        if self._sim is None and "15765" not in proto:
            with self._data_lock:
                self._m06 = {"read": False, "note": f"Mode 06 not supported yet on {proto or 'this'} protocol",
                             "mids": [], "results": []}
            return
        mids, res = read_mode06(t, stop=self._stop.is_set)
        with self._data_lock:
            self._m06 = ({"read": True, "note": None, "mids": mids, "results": [r.model_dump() for r in res]} if mids else
                         {"read": False, "note": "the car did not answer Mode 06 (no supported monitors reported)", "mids": [], "results": []})

    def _read_codes(self, t) -> None:
        """Modes 03/07/0A and the lamp bit, once per run (CAN or a legacy bus; an unknown protocol's layout would
        decode wrongly). A legacy bus has no Mode 0A, so permanent codes are listed as unanswered, never asked."""
        proto = self._adapter["protocol"] or ""
        legacy = is_legacy(proto)
        if self._sim is None and not self._decodable(proto):
            with self._data_lock:
                self._codes = {"read": False, "note": f"trouble codes not supported yet on {proto or 'this'} protocol"}
                self._ready = {"read": False, "note": f"readiness not supported yet on {proto or 'this'} protocol"}
                self._ff = {"read": False, "note": f"freeze frame not supported yet on {proto or 'this'} protocol"}
            return
        # An answer with no codes is an empty list; no answer (NO DATA, a negative or garbled reply) is named in
        # `unanswered`, so the page never turns silence into "no codes" or "lamp off".
        out, missed = {}, []
        asked = (("stored", "03", 0x43), ("pending", "07", 0x47)) + (() if legacy else (("permanent", "0A", 0x4A),))
        stored_no_data = False
        if legacy:
            out["permanent"], missed = [], ["permanent"]
        for k, cmd, sid in asked:
            if self._stop.is_set():  # Stop pressed: do not finish reading the lists
                return
            lines = t.send(cmd)
            payloads = parse_all(lines, sid)
            if not payloads:
                missed.append(k)
                if k == "stored" and legacy and classify(lines, sid) == "no_data":
                    stored_no_data = True
            codes: list[str] = []
            for p in payloads:
                codes += [c for c in decode_dtc_list(p, legacy) if c not in codes]
            out[k] = [{"code": c, **describe(c, make_of(self._key))} for c in codes]
        status = [p for p in parse_all(t.send("0101"), 0x41) if len(p) >= 3 and p[1] == 0x01]
        mil = any(p[2] & 0x80 for p in status) if status else None
        if mil is None:
            missed.append("mil")
        elif stored_no_data and sum(p[2] & 0x7F for p in status) == 0:
            missed.remove("stored")  # a legacy ECU can answer Mode 03 NO DATA when none are stored: 0101 says zero
        read = len([k for k in missed if k != "mil"]) < 3
        ignition, monitors = parse_readiness(status)  # the same 0101 answer: each ECU counts its own codes
        ready = ({"read": True, "note": None, "mil": mil, "dtc_count": sum(p[2] & 0x7F for p in status), "ignition": ignition,
                  "monitors": {k: m.model_dump() for k, m in monitors.items()}} if ignition else
                 {"read": False, "note": "the car did not answer the readiness request (Mode 01 PID 01)"})
        with self._data_lock:
            self._ready = ready
            self._codes = ({"read": True, "note": None, **out, "mil": mil, "unanswered": missed} if read else
                           {"read": False, "note": "the car did not answer the trouble-code requests", "mil": mil})

    def _read_freeze_frame(self, t) -> None:
        """Mode 02 frame 0, once per run, only when a stored code was read (as scan() does). CAN or legacy, as the codes."""
        if self._sim is None and not self._decodable(self._adapter["protocol"] or ""):
            return  # unknown protocol: _read_codes already said why
        with self._data_lock:
            codes = dict(self._codes)
        if not codes.get("read"):
            ff = {"read": False, "note": "not requested: the trouble codes were not read"}
        elif not codes.get("stored"):
            ff = {"read": False, "note": "not requested: no stored code" if "stored" not in codes.get("unanswered", [])
                  else "not requested: the stored-code list did not answer"}
        else:
            answered, frame = read_freeze_frame(t)
            if not answered:
                ff = {"read": False, "note": "the car did not answer the freeze-frame request"}
            elif frame is None:
                ff = {"read": True, "note": None, "dtc": None, "pids": {}}  # answered: no frame stored
            else:
                ff = {"read": True, "note": None, "dtc": frame.dtc,
                      "pids": {p: {"name": v.name, "unit": v.unit, "value": v.value, "label": pid_label(p, v.value)}
                               for p, v in frame.pids.items()}}
        with self._data_lock:
            self._ff = ff

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
                self._full[p].append((seq, round(now, 3), v))
                self._add_stat(p, v, round(now, 3))
            self.seq = seq
            self._last_at = self._clock()
            self._sweep_t.append(now)
        return True

    def _add_stat(self, p: str, v: float, t: float) -> None:
        """Welford's running mean and sum of squared deviations (stable on large values), extremes and when they first happened."""
        a = self._stats.get(p)
        if a is None:
            self._stats[p] = [1, float(v), 0.0, v, v, t, t, t]
            return
        n, mean = a[0] + 1, a[1] + (v - a[1]) / (a[0] + 1)
        a[2] += (v - a[1]) * (v - mean)
        a[0], a[1], a[7] = n, mean, t
        if v < a[3]:
            a[3], a[5] = v, t
        if v > a[4]:
            a[4], a[6] = v, t

    def state(self, after: int = 0) -> dict:
        with self._data_lock:
            seq, t0, deadline, last_at = self.seq, self._t0, self._deadline, self._last_at
            status, message, hz, run = self.status, self.message, self.hz, self._run_id
            adapter, st, codes = dict(self._adapter), list(self._sweep_t), dict(self._codes)
            unsupported, extras, m06 = list(self._unsupported), list(self._extras), dict(self._m06)
            fallbacks = dict(self._fallbacks)
            ready, ff = dict(self._ready), dict(self._ff)
            supported, focus = sorted(self._supported), list(self._focus)
            tiers = None if self._tiers is None else dict(self._tiers)
            capture = self._capture  # the level of the last started run (min | std | max); null before any run; kept in a replay
            vehicle = None if self._vehicle is None else dict(self._vehicle)
            quirks = None if self._quirks is None else dict(self._quirks)  # "quirks applied": null when none
            key, name = (None, None) if self._replay else (self._key, self._name)
            # only sweeps up to `seq`: anything newer is not complete yet
            channels = {
                p: {"name": self._meta(p)[0], "unit": self._meta(p)[1], "labels": self._meta(p)[2],
                    "samples": [[s, tt, v] for s, tt, v in d if after < s <= seq]}
                for p, d in self._ch.items()
            }
            stats = {p: {"n": n, "min": lo, "max": hi, "avg": round(mean, 4), "std": round((m2 / (n - 1)) ** 0.5, 4) if n > 1 else 0.0,
                         "min_t": tlo, "max_t": thi, "age": tlast}
                     for p, (n, mean, m2, lo, hi, tlo, thi, tlast) in self._stats.items()}
            ptimes = self._ptimes
            rp = self._replay
            replay = None if rp is None else {"name": rp["name"], "duration": rp["run"].duration, "pos": round(rp["pos"], 3),
                                              "speed": rp["speed"], "playing": rp["playing"], "ended": rp["ended"], "demo": rp["run"].demo}
        now = replay["pos"] if replay else (self._clock() - t0) if t0 is not None else 0.0
        for p, sp in stats.items():  # last-seen age: a replay looks up the newest sample at or before the replay clock
            last = sp["age"]
            if replay:
                ts = ptimes.get(p, [])
                i = bisect.bisect_right(ts, now)
                last = ts[i - 1] if i else None
            sp["age"] = None if last is None else round(max(0.0, now - last), 2)
        measured = (len(st) - 1) / (st[-1] - st[0]) if len(st) >= 2 and st[-1] > st[0] else None
        return {
            "status": status, "message": message, "demo": self._sim is not None and replay is None, "run": run,
            "seq": seq, "now": round(now, 3),
            "since_last_sample": None if last_at is None else round(self._clock() - last_at, 2),
            "hz": hz, "hz_measured": None if measured is None else round(measured, 2),
            "seconds_left": (max(0.0, round(deadline - self._clock(), 1))
                             if status == "running" and deadline else None),
            "adapter": adapter, "codes": codes, "unsupported": unsupported,
            "extras": extras, "tiers": tiers, "capture": capture, "mode06": m06, "readiness": ready, "freeze_frame": ff, "vehicle": vehicle, "replay": replay,
            "supported": supported, "focus": focus, "fallbacks": fallbacks, "quirks": quirks, "car": self._car(key, name),
            "channels": channels, "stats": stats,
        }

    @staticmethod
    def _car(key: str | None, name: dict | None) -> dict | None:
        """The live or simulated car's name: the one saved in its profile, else the offline suggestion (no model)."""
        if key is None:
            return None
        if name:
            return {"key": key, **name, "source": "saved", "saved": True}
        off = vin_decode.offline(key)
        return {"key": key, "make": off["make"] or "", "model": "", "year": off["year"], "source": "offline", "saved": False}

    def _car_key(self) -> str:
        with self._data_lock:
            if self._replay is not None or self._key is None:
                raise ValueError("no car identified yet: start sampling first")
            return self._key

    def set_car_name(self, make, model, year) -> dict:
        """Save the car's make, model and year in its profile; new saved runs of this car carry them as their label."""
        key = self._car_key()
        name = self._profiles.set_name(key, make, model, year)
        with self._data_lock:
            if self._key == key:
                self._name = name
        return name

    def car_lookup(self) -> dict:
        """NHTSA vPIC's make, model, year and trim for the current car, asked with the vehicle key only."""
        return vin_decode.lookup(self._car_key(), self._s.config.home)

    def recent(self, seconds: float) -> dict:
        out: dict[str, dict] = {}
        with self._data_lock:
            snap = {p: list(d) for p, d in self._ch.items()}
        for p, rows in snap.items():
            name, unit, _ = self._meta(p)
            if not rows:
                out[p] = {"name": name, "unit": unit, "stats": {"n": 0}, "latest": None}
                continue
            cut = rows[-1][1] - seconds
            win = [(tt, v) for _, tt, v in rows if tt >= cut]
            out[p] = {"name": name, "unit": unit,
                      "stats": summarize(Series(name=name, unit=unit, samples=win)),
                      "latest": rows[-1][2]}
        return out

    def save_run(self, label: str) -> Path:
        if self._replay is not None:
            raise ValueError("a replay cannot be saved")
        if not _LABEL_RE.fullmatch(label):
            raise ValueError("label must be 1-40 chars of [a-z0-9-]")
        with self._data_lock:
            if self.seq == 0:
                raise ValueError("nothing sampled yet")
            if self._saved is not None and self._saved[1] == self.seq:  # already on disk (autosaved): no duplicate
                return self._saved[0]
        path = self._write_run(label)
        self._unsaved = False
        return path

    def _write_run(self, label: str) -> Path:
        with self._data_lock:
            seq = self.seq
            series = {p: Series(name=PIDS[p].name, unit=PIDS[p].unit,
                                samples=[(tt, v) for s, tt, v in d if s <= seq])
                      for p, d in self._full.items()}
            codes, m06, key, tr, name = dict(self._codes), dict(self._m06), self._key, self._transcript, self._name
            ready, ff = dict(self._ready), dict(self._ff)
        ls = LiveSample(duration_s=self.state()["now"], rate_hz=self.hz or 0.0, series=series)
        rdir = Path(self._s.config.home) / "runs"
        rdir.mkdir(parents=True, exist_ok=True)
        path = rdir / f"{datetime.now(timezone.utc):%Y-%m-%dT%H-%M-%SZ}-{label}.json"
        with open(path, "x", encoding="utf-8") as fh:
            json.dump({"kind": "live_run", "demo": self._sim is not None, "adapter": self._adapter,
                       "live_sample": ls.model_dump(mode="json"), "codes": codes, "mode06": m06, "readiness": ready, "freeze_frame": ff,
                       "vehicle": {"key": key} if key else None, "vehicle_key": key, "transcript": tr,  # the key, never the VIN
                       **({"meta": {**name, "title": "auto-saved" if label == "auto" else label}} if name else {})}, fh, indent=2)
        with self._data_lock:
            self._saved = (path, seq)
        return path

    def _autosave_run(self) -> None:
        """Every run that took samples is written when it ends, so a later Start cannot lose it."""
        if not self._autosave or self.seq == 0:
            return
        try:
            path = self._write_run("auto")
        except Exception as e:
            self._unsaved = True
            self.message = (self.message + " \u00b7 " if self.message else "") + f"could not save the run automatically ({e}): press Save run"
            return
        self.message = (self.message + " \u00b7 " if self.message else "") + f"run saved as {path.name}"

    def set_sim(self, scenario: str | None = None, rev: bool | None = None) -> None:
        if self._sim is None:
            raise ValueError("simulator controls exist only in demo mode")
        if scenario is not None:
            self._sim.set_scenario(scenario)
        if rev is not None:
            self._sim.rev = bool(rev)
