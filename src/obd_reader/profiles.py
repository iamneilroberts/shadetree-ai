"""Local, per-class-of-car memory of what past runs learned. A hint, never a source of truth:
anything unreadable or malformed loads as 'no profile'."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

KEY_RE = re.compile(r"[A-HJ-NPR-Z0-9]{8}-[A-HJ-NPR-Z0-9]")
_PID_RE = re.compile(r"[0-9A-F]{2}")
_LISTS = ("supported_pids", "unsupported", "extras")


def _pids(v) -> list[str] | None:
    if not isinstance(v, list):
        return None
    return [p for p in v if isinstance(p, str) and _PID_RE.fullmatch(p)]


def clean_name(make, model, year) -> dict:
    """The car's name the user saved: {make, model, year} under the run label's rules (replay_run.clean_meta)."""
    from obd_reader.replay_run import clean_meta  # replay_run imports this module

    s = lambda v: v.strip() if isinstance(v, str) else v  # noqa: E731
    m = clean_meta({"make": s(make), "model": s(model), "year": year, "title": "-"})
    return {"make": m["make"], "model": m["model"], "year": m["year"]}


class ProfileStore:
    def __init__(self, home: Path):
        self._dir = Path(home) / "profiles"

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            raise ValueError("not a vehicle key")
        return self._dir / f"{key}.json"

    def load(self, key: str) -> dict | None:
        try:
            d = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        if not isinstance(d, dict) or d.get("schema") != 1 or d.get("key") != key or not isinstance(d.get("runs"), int):
            return None
        lists = {k: _pids(d.get(k)) for k in _LISTS}
        if any(v is None for v in lists.values()):
            return None
        try:  # a saved name is kept only if it is still valid; a bad one loads as no name
            name = clean_name(d["make"], d["model"], d["year"]) if "make" in d else {}
        except (ValueError, KeyError):
            name = {}
        return {"schema": 1, "key": key, "updated": str(d.get("updated", "")), "runs": d["runs"],
                "protocol": d.get("protocol") if isinstance(d.get("protocol"), str) else None, **lists, **name}

    def set_name(self, key: str, make, model, year) -> dict:
        """Store the car's make, model and year in its profile (a new profile with no runs if there is none)."""
        name = clean_name(make, model, year)
        prof = self.load(key) or {"schema": 1, "key": key, "runs": 0, "protocol": None,
                                  "supported_pids": [], "unsupported": [], "extras": []}
        prof.update(name, updated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.save(key, prof)
        return name

    def save(self, key: str, profile: dict) -> None:
        path = self._path(key)
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        os.replace(tmp, path)
