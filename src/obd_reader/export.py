"""Bundle the newest recorded console runs with their raw transcripts, plus a short text summary,
into one .tgz for moving to another machine. Files only: it never touches an adapter.

The summary is computed values (protocol, codes, per-channel stats), no VIN. The transcripts can
hold one, so the bundle must stay out of git (runs/ and transcripts/ are gitignored)."""
import io
import json
import re
import statistics
import tarfile
from pathlib import Path

from obd_reader.elm import decode_dtc_list, parse_all
from obd_reader.pids import decode_pid, pid_name


class ExportError(RuntimeError):
    pass


def _key(name: str) -> str:
    return name[:19]  # 2026-09-30T17-18-50: file names sort by time


def _load(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _num(v: float) -> str:
    return ("%.2f" % v).rstrip("0").rstrip(".")


def _first(rows: list[dict], tx: str) -> list[str] | None:
    return next((r["rx"] for r in rows if r.get("tx") == tx), None)


def summarize(run_name: str, transcript_name: str, rows: list[dict]) -> str:
    lines = [f"run file: {run_name}", f"transcript: {transcript_name}"]
    dp = _first(rows, "ATDP")
    lines.append(f"protocol: {dp[0].removeprefix('AUTO, ') if dp else 'unknown'}")
    codes = []
    for label, cmd, sid in (("stored", "03", 0x43), ("pending", "07", 0x47), ("permanent", "0A", 0x4A)):
        rx = _first(rows, cmd)
        found = [c for p in parse_all(rx, sid) for c in decode_dtc_list(p)] if rx else None
        codes.append(f"{label} {'not read' if found is None else ', '.join(found) or 'none'}")
    lines.append("codes: " + ", ".join(codes))
    rx = _first(rows, "0101")
    st = [p for p in parse_all(rx, 0x41) if len(p) >= 3 and p[1] == 0x01] if rx else []
    lines.append("MIL: " + ("unknown" if not st else "on" if any(p[2] & 0x80 for p in st) else "off"))
    mids = sorted({r["tx"][2:] for r in rows if re.fullmatch(r"06[0-9A-F]{2}", str(r.get("tx"))) and int(r["tx"][2:], 16) % 0x20})
    lines.append(f"Mode 06: {len(mids)} MIDs ({', '.join(mids)})" if mids else "Mode 06: not read")
    vals: dict[str, list[float]] = {}
    for r in rows:
        tx = str(r.get("tx"))
        if not re.fullmatch(r"01[0-9A-F]{2}", tx) or tx == "0101" or int(tx[2:], 16) % 0x20 == 0:
            continue
        pid = tx[2:]
        for p in parse_all(r.get("rx") or [], 0x41):
            if len(p) >= 2 and p[1] == int(pid, 16):
                d = decode_pid(pid, p[2:])
                if d is not None and isinstance(d.value, (int, float)):
                    vals.setdefault(pid, []).append(d.value)
                break
    lines.append("channels:")
    for pid in sorted(vals):
        v = vals[pid]
        lines.append(f"  {pid} {pid_name(pid)}: n={len(v)} min {_num(min(v))} mean {_num(statistics.fmean(v))} max {_num(max(v))}")
    return "\n".join(lines) + "\n"


def export_run(out_dir: Path, dest: Path, latest: int = 1) -> Path:
    runs = sorted((out_dir / "runs").glob("*.json"), key=lambda p: p.name)[-max(1, latest):]
    if not runs:
        raise ExportError(f"no run files in {out_dir / 'runs'} (press Save run in the console first)")
    consoles = sorted((out_dir / "transcripts").glob("*console.jsonl"), key=lambda p: p.name)
    chosen, summaries = [], []
    for run in runs:
        tr = [t for t in consoles if _key(t.name) <= _key(run.name)]
        pair = tr[-1] if tr else None
        chosen.append((run, pair))
        summaries.append(summarize(run.name, pair.name if pair else "none found", _load(pair) if pair else []))
    with tarfile.open(dest, "w:gz") as tar:
        for d in ("shadetree-share", "shadetree-share/runs", "shadetree-share/transcripts"):
            ti = tarfile.TarInfo(d)
            ti.type, ti.mode = tarfile.DIRTYPE, 0o755
            tar.addfile(ti)
        added: set[str] = set()
        for run, pair in chosen:
            tar.add(run, f"shadetree-share/runs/{run.name}")
            if pair is not None and pair.name not in added:
                added.add(pair.name)
                tar.add(pair, f"shadetree-share/transcripts/{pair.name}")
        data = ("\n".join(summaries)).encode("utf-8")
        ti = tarfile.TarInfo("shadetree-share/SUMMARY.txt")
        ti.size, ti.mode = len(data), 0o644
        tar.addfile(ti, io.BytesIO(data))
    return dest
