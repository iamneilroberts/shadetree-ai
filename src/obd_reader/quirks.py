"""Quirks: what is known about how a class of car answers, keyed by vehicle key or WMI. Hints, never decisions.

`quirks/<vehicle key>.json`, falling back to `quirks/<WMI>.json`. Two folders are searched: `quirks-local/` under the
data home (gitignored, written only by `shadetree-ai quirks accept`) before the committed, reviewed `quirks/` at the
repo root. Anything missing, unreadable, malformed or VIN-bearing loads as "no quirks"; loading never raises."""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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


def _plain(err: dict) -> str:
    """A pydantic error in plain words: `notes[0].verified: missing (required)`."""
    where = ""
    for part in err["loc"]:
        where += f"[{part}]" if isinstance(part, int) else f".{part}" if where else str(part)
    if not where:
        return "the file must hold one JSON object ({ ... }), not a list or a single value"
    if err["type"] == "missing":
        return f"{where}: missing (required)"
    if err["type"] == "extra_forbidden":
        known = Note.model_fields if err["loc"][0] == "notes" else Quirks.model_fields
        return f"{where}: not a known field (known: {', '.join(known)})"
    return f"{where}: {err['msg'].removeprefix('Value error, ').removeprefix(f'{where} ')}"


def validate(text: str, name: str | None = None) -> tuple[Quirks | None, list[str]]:
    """The loader's rules, with reasons in plain words: (quirks, []) when `text` loads as `<name>.json`.
    name None skips the file-name check (a probe report's proposal). Never echoes a VIN-looking token."""
    q, why = None, []
    try:
        q = Quirks.model_validate(json.loads(text))
    except json.JSONDecodeError as e:
        why.append(f"not valid JSON: {e.msg} at line {e.lineno}, column {e.colno}")
    except ValidationError as e:
        why += [_plain(x) for x in e.errors()]
    if q is not None and name is not None and q.key != name and not q.example:  # an example is never looked up by name
        shown = "a VIN-looking name" if find_vins(name) else f"{name}.json"
        why.append(f"key is {q.key} but the file is named {shown}; it is only looked up as {q.key}.json")
    for v in find_vins(text):
        why.append(f"line {text.count(chr(10), 0, text.find(v)) + 1}: a VIN-looking token (not shown); "
                   "a quirks file must never carry a VIN")
    return q, why


def hints(q: Quirks) -> str:
    """The file's hints on one line, for `quirks check` and `quirks show`."""
    parts = [f"protocol {q.protocol}" if q.protocol else "", f"max_hz {q.max_hz:g}" if q.max_hz is not None else "",
             f"pids_lie {' '.join(q.pids_lie)}" if q.pids_lie else "",
             f"ecus {', '.join(f'{h}={r}' for h, r in q.ecus.items())}" if q.ecus else "",
             f"{len(q.notes)} note(s)" if q.notes else "", "example (made up)" if q.example else ""]
    return ", ".join(p for p in parts if p) or "none"


def check(path: Path) -> tuple[Quirks | None, list[str]]:
    """`shadetree-ai quirks check`: a quirks .json, or a probe report's quirks_proposal, against the loader's rules."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        d = json.loads(text)
    except ValueError:
        d = None
    if isinstance(d, dict) and "quirks_proposal" in d:
        if d["quirks_proposal"] is None:
            return None, ["the report has no quirks proposal (the probe did not read a vehicle key)"]
        q, why = validate(json.dumps(d["quirks_proposal"], indent=2))
        return q, [f"quirks_proposal: {w}" for w in why]
    return validate(text, Path(path).stem)


def applied(q: Quirks, path: Path) -> dict:
    """What the console state and the probe report show: the file (folder and name only, never the home path) and its hints."""
    return {"file": f"{path.parent.name}/{path.name}", "key": q.key, "example": q.example, "protocol": q.protocol,
            "max_hz": q.max_hz, "pids_lie": list(q.pids_lie), "ecus": dict(q.ecus), "notes": len(q.notes)}


class QuirkStore:
    def __init__(self, home: Path, committed: Path = REPO_QUIRKS):
        self._dirs = (Path(home) / LOCAL_DIR, Path(committed))

    def candidates(self, key: str):
        """Each file the loader tries for a vehicle key (or a WMI), in order: (path, quirks or None, why skipped)."""
        names = (key, key[:3]) if KEY_RE.fullmatch(key) else (key,) if WMI_RE.fullmatch(key) else ()
        for name in names:
            for d in self._dirs:
                try:
                    text = (d / f"{name}.json").read_text(encoding="utf-8")
                except FileNotFoundError:
                    yield d / f"{name}.json", None, ["missing"]
                    continue
                except (OSError, ValueError) as e:
                    yield d / f"{name}.json", None, [f"unreadable ({type(e).__name__})"]
                    continue
                q, why = validate(text, name)
                yield d / f"{name}.json", None if why else q, why

    def load(self, key: str | None) -> tuple[Quirks, Path] | None:
        """The most specific file first: <key>.json, then <WMI>.json, each in quirks-local/ before quirks/.
        A file that does not load is skipped, as if absent."""
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            return None
        return next(((q, p) for p, q, _ in self.candidates(key) if q is not None), None)


def accept(source: Path, home: Path, replace: bool = False) -> Path:
    """Write a reviewed proposal (a probe report's `quirks_proposal`, or a bare quirks object) to
    <home>/quirks-local/<key>.json. The only writer; refuses a VIN-looking token; overwrites only with replace."""
    d = json.loads(Path(source).read_text(encoding="utf-8"))
    if isinstance(d, dict) and "quirks_proposal" in d:
        d = d["quirks_proposal"]
    if d is None:
        raise ValueError("the report has no quirks proposal (the probe did not read a vehicle key)")
    q, why = validate(json.dumps(d, indent=2))  # plain-word reasons; never echoes the input (it could hold a VIN)
    if why:
        raise ValueError("nothing was written: " + "; ".join(why))
    text = q.model_dump_json(indent=2) + "\n"
    out = Path(home) / LOCAL_DIR / f"{q.key}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(out, "w" if replace else "x", encoding="utf-8") as fh:
            fh.write(text)
    except FileExistsError:
        raise ValueError(f"{LOCAL_DIR}/{out.name} already exists; nothing was written. "
                         "Use --replace to overwrite it, or edit that file by hand") from None
    return out
