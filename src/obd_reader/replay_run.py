"""Load a saved run for replay. A run file is untrusted input (it may be uploaded): every field is checked,
bounded and copied; nothing from it is executed or used as a path."""
import bisect
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from obd_reader.profiles import KEY_RE

MAX_SERIES, MAX_SAMPLES, MAX_DURATION, MAX_TEXT = 64, 600_000, 86_400.0, 80
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_LISTED = 50
_HEX2 = re.compile(r"[0-9A-F]{2}")
_NAME = re.compile(r"[A-Za-z0-9T:_.-]{1,100}\.json")
_CODE = re.compile(r"[PCBU][0-9A-F]{4}")
_VIN_RUN = re.compile(r"[A-HJ-NPR-Z0-9]{17}")   # any 17 VIN characters in a row, checked on the upper-cased label
_MON = re.compile(r"[a-z0-9_]{1,40}")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z")
_ADDR = re.compile(r"[0-9A-F]{2}|[0-9A-F]{3}|[0-9A-F]{8}")  # an ECU address: legacy source, CAN 11-bit or 29-bit id
MAX_ECUS = 32
META_TEXT = {"make": 40, "model": 40, "title": 80}
MIN_YEAR, MAX_YEAR = 1996, 2100


@dataclass(frozen=True)
class Run:
    duration: float
    rate_hz: float
    protocol: str | None
    names: dict
    sweeps: list
    codes: dict | None = None
    mode06: dict | None = None
    vehicle: dict | None = None
    times: list = field(default_factory=list)
    demo: bool = False  # recorded from the simulator, not a car
    readiness: dict | None = None
    freeze_frame: dict | None = None
    ecus: list = field(default_factory=list)          # ECU addresses that answered Mode 01 (headers on)
    channel_ecus: dict = field(default_factory=dict)  # channel -> the ECU it was read from

    def index_after(self, pos: float) -> int:
        return bisect.bisect_right(self.times, pos)

    def first_in_window(self, pos: float, span: float) -> int:
        return bisect.bisect_left(self.times, pos - span)


def _num(x) -> float:
    try:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise ValueError("samples must be finite numbers")
        return float(x)
    except OverflowError:
        raise ValueError("a number is out of range") from None


def _text(x, allow_none: bool = False):
    if x is None and allow_none:
        return None
    if not isinstance(x, str) or len(x) > MAX_TEXT:
        raise ValueError("a name or unit is missing or longer than 80 characters")
    return x


def _short(x) -> str:
    return x if isinstance(x, str) and len(x) <= 200 else ""


def _codes(c) -> dict | None:
    if not isinstance(c, dict):
        return None
    mil = c.get("mil") if isinstance(c.get("mil"), bool) else None  # null: the lamp bit was not answered
    if c.get("read") is not True:
        n = c.get("note")
        out = {"read": False, "note": n if isinstance(n, str) and len(n) <= 200 else None}
        if mil is not None:
            out["mil"] = mil
        return out
    out = {"read": True, "note": None}
    for k in ("stored", "pending", "permanent"):
        items = c.get(k)
        if not isinstance(items, list) or len(items) > 64:
            return None
        clean = []
        for it in items:
            if not (isinstance(it, dict) and isinstance(it.get("code"), str) and _CODE.fullmatch(it["code"])):
                return None
            clean.append({"code": it["code"], "desc": _short(it.get("desc")), "hint": _short(it.get("hint")), "known": it.get("known") is True})
        out[k] = clean
    out["mil"] = mil
    miss = c.get("unanswered")
    if isinstance(miss, list) and miss:
        out["unanswered"] = [k for k in ("stored", "pending", "permanent", "mil") if k in miss]
    return out


def _mode06(m) -> dict | None:
    if not isinstance(m, dict) or m.get("read") is not True:
        return None
    mids, res = m.get("mids"), m.get("results")
    if not (isinstance(mids, list) and isinstance(res, list)) or len(mids) > 64 or len(res) > 400:
        return None
    if m.get("layout") == "legacy":
        return _mode06_legacy(mids, res)
    out = []
    for r in res:
        if not isinstance(r, dict):
            return None
        ids = [r.get(k) for k in ("mid", "tid", "uasid")]
        nums = [r.get(k) for k in ("value", "minimum", "maximum")]
        if not all(isinstance(x, str) and _HEX2.fullmatch(x) for x in ids) or not all(type(x) is int for x in nums):
            return None
        wl = r.get("within_limits")
        out.append({"mid": ids[0], "tid": ids[1], "uasid": ids[2], "value": nums[0], "minimum": nums[1], "maximum": nums[2],
                    "within_limits": wl if isinstance(wl, bool) else None})
        if "raw" in r:  # a signed UAS row's words as received (None otherwise); files from before it have no key
            raw = r["raw"]
            ok = isinstance(raw, list) and len(raw) == 3 and all(type(x) is int and 0 <= x <= 0xFFFF for x in raw)
            out[-1]["raw"] = raw if ok else None
    return {"read": True, "note": None, "mids": [x for x in mids if isinstance(x, str) and _HEX2.fullmatch(x)], "results": out}


_GM_HELP_KEY = re.compile(r"gm:[0-9A-F]{2}:[0-9A-F]{2}:(?:min|max)")


def _mode06_legacy(tids: list, res: list) -> dict | None:
    out = []
    for r in res:
        if not isinstance(r, dict):
            return None
        ids, nums = [r.get("tid"), r.get("component")], [r.get("value"), r.get("limit")]
        if (not all(isinstance(x, str) and _HEX2.fullmatch(x) for x in ids) or not all(type(x) is int for x in nums)
                or r.get("limit_type") not in ("min", "max")):
            return None
        row = {"tid": ids[0], "component": ids[1], "value": nums[0], "limit": nums[1], "limit_type": r["limit_type"]}
        hk = r.get("help")
        if isinstance(hk, str) and _GM_HELP_KEY.fullmatch(hk):  # GM names: kept only as plain short text and numbers
            row.update(help=hk, name=_short(r.get("name")), monitor=_short(r.get("monitor")), unit=_short(r.get("unit")),
                       **{k: r[k] if type(r.get(k)) in (int, float) and math.isfinite(r[k]) else None
                          for k in ("value_s", "limit_s")})
        out.append(row)
    return {"read": True, "note": None, "layout": "legacy",
            "mids": [x for x in tids if isinstance(x, str) and _HEX2.fullmatch(x)], "results": out}


def _not_read(x) -> dict | None:
    """A block saved as not read keeps its short note (why), so a replay does not call it missing from the file."""
    n = x.get("note") if isinstance(x, dict) and x.get("read") is False else None
    return {"read": False, "note": n} if isinstance(n, str) and 0 < len(n) <= 200 else None


def _readiness(r) -> dict | None:
    """Mode 01 PID 01 as saved: lamp, code count, ignition and up to 16 monitors. Anything malformed: not stored."""
    if not isinstance(r, dict) or r.get("read") is not True:
        return _not_read(r)
    mons, n, ign = r.get("monitors"), r.get("dtc_count"), r.get("ignition")
    if not isinstance(mons, dict) or len(mons) > 16 or type(n) is not int or not 0 <= n <= 1000 or ign not in ("spark", "compression"):
        return None
    out = {}
    for k, m in mons.items():
        if not (isinstance(k, str) and _MON.fullmatch(k) and isinstance(m, dict) and isinstance(m.get("supported"), bool)
                and m.get("complete") in (True, False, None)):
            return None
        out[k] = {"supported": m["supported"], "complete": m.get("complete")}
    mil = r.get("mil") if isinstance(r.get("mil"), bool) else None
    return {"read": True, "note": None, "mil": mil, "dtc_count": n, "ignition": ign, "monitors": out}


def _freeze(f) -> dict | None:
    """Mode 02 frame 0 as saved: the code that set it (or none stored) and up to 64 decoded readings."""
    if not isinstance(f, dict) or f.get("read") is not True:
        return _not_read(f)
    dtc, pids = f.get("dtc"), f.get("pids")
    if not (dtc is None or isinstance(dtc, str) and _CODE.fullmatch(dtc)) or not isinstance(pids, dict) or len(pids) > 64:
        return None
    out = {}
    for pid, v in pids.items():
        if not (isinstance(pid, str) and _HEX2.fullmatch(pid) and isinstance(v, dict)):
            return None
        label = v.get("label")
        try:
            out[pid] = {"name": _text(v.get("name")), "unit": _text(v.get("unit"), allow_none=True), "value": _num(v.get("value")),
                        "label": label if isinstance(label, str) and len(label) <= MAX_TEXT else None}
        except ValueError:
            return None
    return {"read": True, "note": None, "dtc": dtc, "pids": out}


def _vehicle(v) -> dict | None:
    key = v.get("key") if isinstance(v, dict) else None
    if isinstance(key, str) and KEY_RE.fullmatch(key):
        return {"key": key, "known": False, "runs": 0, "note": None}
    return None


def _ecus(obj, names: dict) -> tuple[list, dict]:
    """The run's ECU addresses and which one each channel was read from; anything malformed is left out
    (runs from before headers-on sampling have neither)."""
    seen = obj.get("ecus")
    addrs = [e.get("addr") for e in seen[:MAX_ECUS] if isinstance(e, dict)] if isinstance(seen, list) else []
    addrs = list(dict.fromkeys(a for a in addrs if isinstance(a, str) and _ADDR.fullmatch(a)))
    ch = obj.get("channel_ecus")
    chan = {p: a for p, a in ch.items() if p in names and isinstance(a, str) and _ADDR.fullmatch(a)} if isinstance(ch, dict) else {}
    return addrs, chan


def load_run(obj) -> Run:
    if not isinstance(obj, dict) or obj.get("kind") != "live_run":
        raise ValueError("not a saved run (kind must be live_run)")
    ls = obj.get("live_sample")
    series = ls.get("series") if isinstance(ls, dict) else None
    if not isinstance(series, dict) or not 1 <= len(series) <= MAX_SERIES:
        raise ValueError(f"a run needs 1 to {MAX_SERIES} readings")
    names, by_t, total = {}, {}, 0
    for pid, s in series.items():
        if not (isinstance(pid, str) and _HEX2.fullmatch(pid)):
            raise ValueError("reading ids must be two hex digits")
        if not isinstance(s, dict) or not isinstance(s.get("samples"), list):
            raise ValueError("a reading has no samples list")
        names[pid] = (_text(s.get("name")), _text(s.get("unit"), allow_none=True))
        total += len(s["samples"])
        if total > MAX_SAMPLES:
            raise ValueError("too many samples")
        for pair in s["samples"]:
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                raise ValueError("a sample must be [time, value]")
            t, v = _num(pair[0]), _num(pair[1])
            if not 0 <= t <= MAX_DURATION:
                raise ValueError("a sample time is out of range")
            by_t.setdefault(t, {})[pid] = v
    if not by_t:
        raise ValueError("the run has no samples")
    sweeps = sorted(by_t.items())
    ad = obj.get("adapter")
    proto = ad.get("protocol") if isinstance(ad, dict) else None
    rate = ls.get("rate_hz")
    try:
        rate = float(rate) if isinstance(rate, (int, float)) and not isinstance(rate, bool) and math.isfinite(rate) and rate > 0 else 0.0
    except OverflowError:
        rate = 0.0
    ecus, chan = _ecus(obj, names)
    return Run(duration=max(sweeps[-1][0], 0.1),
               rate_hz=rate,
               protocol=proto if isinstance(proto, str) and len(proto) <= MAX_TEXT else None,
               names=names, sweeps=sweeps, codes=_codes(obj.get("codes")), mode06=_mode06(obj.get("mode06")),
               vehicle=_vehicle(obj.get("vehicle")), times=[t for t, _ in sweeps], demo=obj.get("demo") is True,
               readiness=_readiness(obj.get("readiness")), freeze_frame=_freeze(obj.get("freeze_frame")),
               ecus=ecus, channel_ecus=chan)


def clean_meta(m) -> dict:
    """The picker label of a run: {make, model, year, title}. Short plain text, an integer year, never a VIN."""
    if not isinstance(m, dict):
        raise ValueError("meta must be an object with make, model, year and title")
    out = {}
    for k, limit in META_TEXT.items():
        v = m.get(k)
        if not isinstance(v, str) or not 1 <= len(v) <= limit or not v.isprintable():
            raise ValueError(f"{k} must be 1 to {limit} printable characters")
        if _VIN_RUN.search(v.upper()):
            raise ValueError(f"{k} looks like it holds a VIN: labels are public, leave the VIN out")
        out[k] = v
    y = m.get("year")
    if type(y) is not int or not MIN_YEAR <= y <= MAX_YEAR:
        raise ValueError(f"year must be a whole number from {MIN_YEAR} to {MAX_YEAR}")
    return {"make": out["make"], "model": out["model"], "year": y, "title": out["title"]}


def label_run(path, *, make: str, model: str, year: int, title: str) -> dict:
    """Write the meta block into a saved run file (the file must already be a valid run)."""
    meta = clean_meta({"make": make.strip(), "model": model.strip(), "year": year, "title": title.strip()})
    p = Path(path)
    if p.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("file too large")
    obj = json.loads(p.read_text(encoding="utf-8"))
    load_run(obj)
    obj["meta"] = meta
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return meta


def _when(p: Path) -> datetime:
    """Run time: the UTC stamp a saved run's name starts with, else the file time."""
    m = _STAMP.match(p.name)
    if m:
        try:
            return datetime.strptime(m.group(), "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)


def read_run_file(runs_dir, name) -> dict:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("not a run file name")
    d = Path(runs_dir)
    p = d / name
    if p.is_symlink() or not p.is_file():
        raise FileNotFoundError(name)
    if p.resolve().parent != d.resolve():
        raise ValueError("not a run file name")
    if p.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("file too large")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError("file is not valid JSON") from e


def list_runs(runs_dir) -> list[dict]:
    d = Path(runs_dir)
    try:
        files = [(_when(p), p) for p in d.iterdir() if _NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
        files.sort(key=lambda w: (w[0], w[1].name), reverse=True)
    except OSError:
        return []
    out = []
    for when, p in files:
        if len(out) >= MAX_LISTED:
            break
        try:
            size = p.stat().st_size
            if size > MAX_FILE_BYTES:
                continue
            obj = json.loads(p.read_text(encoding="utf-8"))
            if obj.get("kind") != "live_run":
                continue
            dur = float(obj["live_sample"]["duration_s"])
            if not math.isfinite(dur) or dur < 0:
                continue
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError):
            continue
        try:
            meta = clean_meta(obj.get("meta"))
        except ValueError:
            meta = None
        out.append({"name": p.name, "size": size, "duration": dur, "time": f"{when:%Y-%m-%dT%H:%M:%SZ}", "meta": meta})
    return out
