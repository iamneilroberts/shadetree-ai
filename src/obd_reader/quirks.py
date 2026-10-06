"""Quirks: what is known about how a class of car answers, keyed by vehicle key or WMI. Hints, never decisions.

`quirks/<vehicle key>.json`, falling back to `quirks/<WMI>.json`. Two folders are searched: `quirks-local/` under the
data home (gitignored, written only by `shadetree-ai quirks accept`) before the committed, reviewed `quirks/` at the
repo root. Anything missing, unreadable, malformed or VIN-bearing loads as "no quirks"; loading never raises."""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from obd_reader.live import MAX_HZ, MIN_HZ
from obd_reader.profiles import KEY_RE
from obd_reader.vin import find_vins

REPO_QUIRKS = Path(__file__).resolve().parents[2] / "quirks"  # the repo's committed folder (absent in a wheel install)
LOCAL_DIR = "quirks-local"
WMI_RE = re.compile(r"[A-HJ-NPR-Z0-9]{3}")
_PID_RE = re.compile(r"[0-9A-F]{2}")
HEADER_RE = re.compile(r"[0-9A-F]{2,8}")
ATSP_VALUES = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "A", "B", "C")  # 0 (automatic search) is not a pin


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Note(_Model):
    text: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=200)  # e.g. "probe <id>", a person, a service manual
    confidence: Literal["unverified", "low", "medium", "high"]
    verified: bool


class Quirks(_Model):
    key: str                                              # vehicle key (ABCDEFGH-P) or WMI (ABC); matches the file name
    example: bool = False                                 # a made-up file that shows the format
    protocol: str | None = None                           # ATSP value to try instead of automatic search
    max_hz: float | None = Field(None, ge=MIN_HZ, le=MAX_HZ)  # live sweep rate cap
    pids_lie: list[str] = Field(default_factory=list)     # Mode 01 PIDs advertised but always NO DATA
    ecus: dict[str, str] = Field(default_factory=dict)    # ECU header -> role
    notes: list[Note] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not (KEY_RE.fullmatch(v) or WMI_RE.fullmatch(v)):
            raise ValueError("key must be a vehicle key (ABCDEFGH-P) or a WMI (ABC)")
        return v

    @field_validator("protocol")
    @classmethod
    def _protocol(cls, v: str | None) -> str | None:
        if v is not None and v not in ATSP_VALUES:
            raise ValueError("protocol must be an ATSP value 1-9 or A-C")
        return v

    @field_validator("pids_lie")
    @classmethod
    def _pids(cls, v: list[str]) -> list[str]:
        if not all(_PID_RE.fullmatch(p) for p in v):
            raise ValueError("pids_lie holds two-digit upper-case hex PIDs")
        return v

    @field_validator("ecus")
    @classmethod
    def _ecus(cls, v: dict[str, str]) -> dict[str, str]:
        if not all(HEADER_RE.fullmatch(h) and 0 < len(r) <= 40 for h, r in v.items()):
            raise ValueError("ecus maps an upper-case hex header to a role of at most 40 characters")
        return v


def _read(path: Path, name: str) -> Quirks | None:
    try:
        text = path.read_text(encoding="utf-8")
        q = Quirks.model_validate(json.loads(text))
    except (OSError, ValueError):  # pydantic's ValidationError is a ValueError
        return None
    return q if q.key == name and not find_vins(text) else None


def applied(q: Quirks, path: Path) -> dict:
    """What the console state and the probe report show: the file (folder and name only, never the home path) and its hints."""
    return {"file": f"{path.parent.name}/{path.name}", "key": q.key, "example": q.example, "protocol": q.protocol,
            "max_hz": q.max_hz, "pids_lie": list(q.pids_lie), "ecus": dict(q.ecus), "notes": len(q.notes)}


class QuirkStore:
    def __init__(self, home: Path, committed: Path = REPO_QUIRKS):
        self._dirs = (Path(home) / LOCAL_DIR, Path(committed))

    def load(self, key: str | None) -> tuple[Quirks, Path] | None:
        """The most specific file first: <key>.json, then <WMI>.json, each in quirks-local/ before quirks/.
        A file that does not load is skipped, as if absent."""
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            return None
        for name in (key, key[:3]):
            for d in self._dirs:
                q = _read(d / f"{name}.json", name)
                if q is not None:
                    return q, d / f"{name}.json"
        return None


def accept(source: Path, home: Path) -> Path:
    """Write a reviewed proposal (a probe report's `quirks_proposal`, or a bare quirks object) to
    <home>/quirks-local/<key>.json. The only writer; refuses a VIN-looking token and never overwrites."""
    d = json.loads(Path(source).read_text(encoding="utf-8"))
    if isinstance(d, dict) and "quirks_proposal" in d:
        d = d["quirks_proposal"]
    if d is None:
        raise ValueError("the report has no quirks proposal (the probe did not read a vehicle key)")
    q = Quirks.model_validate(d)
    text = q.model_dump_json(indent=2) + "\n"
    if find_vins(text):
        raise ValueError("the proposal contains a VIN-looking token; nothing was written")
    out = Path(home) / LOCAL_DIR / f"{q.key}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8") as fh:  # FileExistsError: delete or edit the old file by hand
        fh.write(text)
    return out
