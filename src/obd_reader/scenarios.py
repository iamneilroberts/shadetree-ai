"""Shared console scenarios: validate a --scenarios FILE (hex PIDs, at most 8 gauges, short names)."""
import json
import re
from pathlib import Path

MAX_BYTES = 32_768
MAX_SCENARIOS = 12
MAX_GAUGES = 8
FORMS = ("dial", "bar", "seven")
_ID = re.compile(r"[a-z][a-z0-9-]{0,23}\Z")
_PID = re.compile(r"[0-9A-Fa-f]{2}\Z")


def _reject_constant(name: str):
    raise ValueError(f"{name} is not allowed in a scenarios file")


def _gauge(g, where: str) -> dict:
    if not isinstance(g, dict) or not set(g) <= {"pid", "form"}:
        raise ValueError(f'{where}: a gauge is {{"pid": "0C", "form": "dial"}} and nothing else')
    pid = g.get("pid")
    if not isinstance(pid, str) or not _PID.match(pid):
        raise ValueError(f"{where}: pid must be two hex digits, got {pid!r}")
    form = g.get("form", "dial")
    if form not in FORMS:
        raise ValueError(f"{where}: form must be one of {', '.join(FORMS)}")
    return {"pid": pid.upper(), "form": form}


def parse_scenarios(text: str) -> list[dict]:
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from None
    if not isinstance(data, dict) or set(data) != {"scenarios"} or not isinstance(data["scenarios"], list):
        raise ValueError('expected {"scenarios": [...]}')
    if len(data["scenarios"]) > MAX_SCENARIOS:
        raise ValueError(f"at most {MAX_SCENARIOS} scenarios")
    out, ids = [], set()
    for i, s in enumerate(data["scenarios"]):
        where = f"scenario {i + 1}"
        if not isinstance(s, dict) or set(s) != {"id", "name", "gauges"}:
            raise ValueError(f"{where}: needs exactly id, name, gauges")
        if not isinstance(s["id"], str) or not _ID.match(s["id"]):
            raise ValueError(f"{where}: id must be lowercase letters, digits, dashes (max 24)")
        if s["id"] in ids:
            raise ValueError(f"{where}: duplicate id {s['id']!r}")
        ids.add(s["id"])
        name = s["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 24 or not name.isprintable():
            raise ValueError(f"{where}: name must be 1-24 printable characters")
        if not isinstance(s["gauges"], list) or not 1 <= len(s["gauges"]) <= MAX_GAUGES:
            raise ValueError(f"{where}: 1 to {MAX_GAUGES} gauges")
        out.append({"id": s["id"], "name": name, "gauges": [_gauge(g, where) for g in s["gauges"]]})
    return out


def load_scenarios(path: Path) -> list[dict]:
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"scenarios file too large (over {MAX_BYTES} bytes)")
    return parse_scenarios(path.read_text(encoding="utf-8"))
