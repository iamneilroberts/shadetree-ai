"""Local, per-class-of-car memory of what past runs learned. A hint, never a source of truth:
anything unreadable or malformed loads as 'no profile'."""
import json
import os
import re
from pathlib import Path

KEY_RE = re.compile(r"[A-HJ-NPR-Z0-9]{8}-[A-HJ-NPR-Z0-9]")
_PID_RE = re.compile(r"[0-9A-F]{2}")
_LISTS = ("supported_pids", "unsupported", "extras")


def _pids(v) -> list[str] | None:
    if not isinstance(v, list):
        return None
    return [p for p in v if isinstance(p, str) and _PID_RE.fullmatch(p)]


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
        return {"schema": 1, "key": key, "updated": str(d.get("updated", "")), "runs": d["runs"],
                "protocol": d.get("protocol") if isinstance(d.get("protocol"), str) else None, **lists}

    def save(self, key: str, profile: dict) -> None:
        path = self._path(key)
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        os.replace(tmp, path)
