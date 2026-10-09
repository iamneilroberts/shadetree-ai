"""Bus capture files (captures/<id>.jsonl, local and gitignored: payloads may hold the VIN) and their payload-free summary."""
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterator

SCHEMA = 1
_HEX = re.compile(r"[0-9A-F]{2,3}")


class CaptureWriter:
    """One JSON object per line, flushed as written, so a crash leaves every written line readable."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "x", encoding="utf-8")  # never overwrite a capture
        self.frames, self.gaps, self.gap_seconds = 0, 0, 0.0

    def _put(self, rec: dict) -> None:
        self._fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self._fh.flush()

    def header(self, **fields) -> None:
        self._put({"type": "header", "schema": SCHEMA, **fields})

    def frame(self, t: float, raw: str) -> None:
        self.frames += 1
        self._put({"type": "frame", "t": round(t, 4), "raw": raw})

    def step(self, t: float, step: str, phase: str) -> None:
        self._put({"type": "step", "t": round(t, 4), "step": step, "phase": phase})

    def gap(self, t: float, reason: str, seconds: float) -> None:
        self.gaps, self.gap_seconds = self.gaps + 1, self.gap_seconds + seconds
        self._put({"type": "gap", "t": round(t, 4), "gap": reason, "seconds": round(seconds, 4)})

    def end(self, t: float, reason: str) -> None:
        self._put({"type": "end", "t": round(t, 4), "reason": reason, "frames": self.frames, "gaps": self.gaps,
                   "gap_seconds": round(self.gap_seconds, 4)})

    def close(self) -> None:
        self._fh.close()


def read_records(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                return  # a truncated last line (the run died mid-write)
            if not isinstance(rec, dict):
                return
            yield rec


def id_tokens_for(protocol: str) -> int:
    """How many leading tokens of a headers-on line are the message id, from the ATDPN protocol number."""
    num = str(protocol).upper().lstrip("A")
    return 4 if num in ("7", "9") else 3 if num in ("1", "2", "3", "4", "5") else 1


def split_frame(raw: str, id_tokens: int) -> tuple[str, list[str]] | None:
    toks = raw.split()
    if not toks or not all(_HEX.fullmatch(t) for t in toks):
        return None
    n = 1 if len(toks[0]) == 3 else id_tokens  # a 3-digit first token is an 11-bit CAN id
    return (" ".join(toks[:n]), toks[n:]) if len(toks) > n else None


class _IdStats:
    """Running totals for one message id, so a capture never has to fit in memory."""

    def __init__(self, first: list[str]):
        self.n, self.first, self.prev = 0, first, None
        self.lengths, self.changed, self.per_step = Counter(), set(), Counter()


def summarize(path: Path) -> str:
    path = Path(path)
    head, end, last_t, n_gaps, gap_s = {}, None, 0.0, 0, 0.0
    windows, opened = [], {}
    for r in read_records(path):  # pass 1: header, end, step windows, gaps, duration
        last_t = max(last_t, r.get("t", 0.0))
        kind = r.get("type")
        if kind == "header" and not head:
            head = r
        elif kind == "end" and end is None:
            end = r
        elif kind == "gap":
            n_gaps, gap_s = n_gaps + 1, gap_s + r["seconds"]
        elif kind == "step":
            if r["phase"] == "start":
                opened[r["step"]] = r["t"]
            elif r["step"] in opened:
                windows.append((r["step"], opened.pop(r["step"]), r["t"]))
    n_id = id_tokens_for(head.get("protocol", ""))
    stats, other = {}, 0
    for r in read_records(path):  # pass 2: frames into per-id totals
        if r.get("type") != "frame":
            continue
        sf = split_frame(r["raw"], n_id)
        if not sf:
            other += 1
            continue
        fid, d = sf
        st = stats.get(fid)
        if st is None:
            st = stats[fid] = _IdStats(d)
        st.n += 1
        st.lengths[len(d)] += 1
        st.changed.update(i for i, byte in enumerate(d) if i >= len(st.first) or byte != st.first[i])
        if st.prev is not None and d != st.prev:
            st.per_step.update(s for s, a, b in windows if a <= r["t"] <= b)
        st.prev = d
    out = [f"# Bus capture {path.stem}", "",
           f"- protocol: {head.get('protocol_name') or head.get('protocol') or 'unknown'}; monitor: {head.get('monitor_command', '?')}",
           f"- vehicle key: {head.get('vehicle_key') or 'not read'}",
           f"- ended: {end['reason'] if end else 'no end record (the run stopped early)'}; {last_t:.1f} s",
           f"- frames: {sum(st.n for st in stats.values())}; other lines: {other}; gaps: {n_gaps} ({gap_s:.1f} s)", ""]
    if not stats:
        return "\n".join(out + ["No frames were received: the bus was silent at this port, or the adapter did not pass them on.", ""])
    out += ["| ID | frames | Hz | bytes | changing bytes | most change in |", "|---|---|---|---|---|---|"]
    for fid in sorted(stats):
        st = stats[fid]
        top = ", ".join(s for s, _ in st.per_step.most_common(3)) or "\u2014"
        hz = st.n / last_t if last_t > 0 else 0.0
        out.append(f"| {fid} | {st.n} | {hz:.1f} | {st.lengths.most_common(1)[0][0]} | {len(st.changed)} | {top} |")
    return "\n".join(out + [""])


def summarize_file(path: Path) -> Path:
    md = Path(path).with_suffix(".md")
    md.write_text(summarize(path), encoding="utf-8")
    return md
