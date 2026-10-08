"""Bundle the newest recorded console runs with their raw transcripts, plus a short text summary,
into one .tgz for moving to another machine. Files only: it never touches an adapter.

The summary is computed values (protocol, codes, per-channel stats), no VIN. The transcripts can
hold one, so the bundle must stay out of git (runs/ and transcripts/ are gitignored).

build_zip makes the version to share (console Download .zip, `export-run --zip`): the VIN's serial is masked and
checked, and a transcript that fails the check is left out."""
import io
import json
import re
import statistics
import subprocess
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from obd_reader.elm import ERROR_MARKERS, decode_dtc_list, parse_all, parse_vin_legacy
from obd_reader.pids import decode_pid, pid_name
from obd_reader.snapshot import VIN_RE
from obd_reader.vehicle import vehicle_key


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


def _transcript_for(out_dir: Path, run: Path) -> Path | None:
    try:
        named = json.loads(run.read_text(encoding="utf-8")).get("transcript")
    except (ValueError, AttributeError):
        named = None
    if isinstance(named, str):  # the run names its transcript (relative to the data home): trust only that
        p = (out_dir / named).resolve()
        return p if p.is_file() and p.is_relative_to(out_dir.resolve()) else None
    # older run files: the newest console transcript that started before the run was saved
    consoles = sorted((out_dir / "transcripts").glob("*console.jsonl"), key=lambda p: p.name)
    tr = [t for t in consoles if _key(t.name) <= _key(run.name)]
    return tr[-1] if tr else None


def newest_runs(out_dir: Path, latest: int = 1) -> list[Path]:
    return sorted((out_dir / "runs").glob("*.json"), key=lambda p: p.name)[-max(1, latest):]


def export_run(out_dir: Path, dest: Path, latest: int = 1) -> Path:
    runs = newest_runs(out_dir, latest)
    if not runs:
        raise ExportError(f"no run files in {out_dir / 'runs'} (press Save run in the console first)")
    chosen, summaries = [], []
    for run in runs:
        pair = _transcript_for(out_dir, run)
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


# ---- the shareable .zip: the VIN's serial (characters 12-17) masked to 000000, then verified; fail closed ----

ISSUES_URL = "https://github.com/iamneilroberts/shadetree-ai/issues"
MASK = "000000"
_VIN_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Za-z0-9])", re.I)
_PAIRS = re.compile(r"(?:[0-9A-F]{2} ?)+")
_LEN = re.compile(r"[0-9A-F]{3}")
_FRAME = re.compile(r"[0-9A-F]+: ((?:[0-9A-F]{2} ?)+)")
_HDR_ON = re.compile(r"([0-9A-F]{3}|18 D[AB] [0-9A-F]{2} [0-9A-F]{2}) ((?:[0-9A-F]{2} ?)+)")
_SEP = r'(?:\s|"|,|\\[nr]|[0-9A-F]{1,3}:)*'  # what may sit between reply bytes in the text: spaces, line breaks, frame numbers
_GAP = 8  # bytes allowed between two serial bytes in the per-reply scan: CAN headers and PCI, legacy "49 02 <n>", a CRC


def masked_vin(vin: str) -> str:
    return vin[:11] + MASK


def _cols(s: str, at: int) -> list[int]:
    """Column of each two-digit hex byte in s (pairs with optional single spaces), offset by at."""
    out, i = [], 0
    while i < len(s):
        if s[i] == " ":
            i += 1
            continue
        out.append(at + i)
        i += 2
    return out


def _messages(rx: list[str]) -> list[tuple[bytes, list, set, bool]]:
    """The 49-SID messages in one reply as (bytes, [(line, column)] per byte, lines used, headers_on).
    Reads what elm.parse_all reads (a single hex line; an ISO-TP "014" / "0: ..." block) and also headers-on CAN
    frames (11-bit "7E8 10 14 ...", 29-bit "18 DA F1 10 10 14 ..."), which parse_all does not. Status and error
    lines are skipped rather than discarding the reply, so masking reaches every VIN byte."""
    out, pend, i = [], {}, 0
    while i < len(rx):
        raw = rx[i]
        s = raw.strip().upper()
        lead = len(raw) - len(raw.lstrip())
        if not raw.isascii():
            i += 1
            continue
        if _LEN.fullmatch(s):
            total, data, slots, lines = int(s, 16), b"", [], {i}
            i += 1
            while i < len(rx) and rx[i].isascii() and (m := _FRAME.fullmatch(rx[i].strip().upper())):
                data += bytes.fromhex(m.group(1))
                slots += [(i, c) for c in _cols(m.group(1), len(rx[i]) - len(rx[i].lstrip()) + m.start(1))]
                lines.add(i)
                i += 1
            if total and len(data) >= total and data[:1] == b"\x49":
                out.append((data[:total], slots[:total], lines, False))
            continue
        if _PAIRS.fullmatch(s) and s[:2] == "49":
            out.append((bytes.fromhex(s), [(i, c) for c in _cols(s, lead)], {i}, False))
        elif m := _HDR_ON.fullmatch(s):
            b, slots = bytes.fromhex(m.group(2)), [(i, c) for c in _cols(m.group(2), lead + m.start(2))]
            kind, hdr = b[0] >> 4, m.group(1)
            if kind == 0 and b[0] & 0xF and b[1:2] == b"\x49":
                n = b[0] & 0xF
                out.append((b[1:1 + n], slots[1:1 + n], {i}, True))
            elif kind == 1 and len(b) >= 2:
                pend[hdr] = [((b[0] & 0xF) << 8) | b[1], b[2:], slots[2:], {i}]
            elif kind == 2 and hdr in pend:
                p = pend[hdr]
                p[1], p[2] = p[1] + b[1:], p[2] + slots[1:]
                p[3].add(i)
                if len(p[1]) >= p[0]:
                    del pend[hdr]
                    if p[1][:1] == b"\x49":
                        out.append((p[1][:p[0]], p[2][:p[0]], p[3], True))
        i += 1
    return out


def _locate(rx: list[str]) -> tuple[list[tuple[str, list, bool]], set]:
    """Every VIN in one reply as (17 characters, their 17 byte slots, headers_on), and the lines those messages used.
    CAN: 49 02 <count> then the 17 characters. Legacy (as elm.parse_vin_legacy): lines `49 02 <n> <4 bytes>`,
    numbered from 1 per ECU, joined in order with the leading zero pad removed."""
    found, used, legacy = [], set(), []
    for data, slots, lines, on in _messages(rx):
        if data[1:2] != b"\x02":
            continue
        if len(data) == 20:
            found.append((data[3:].decode("latin-1"), slots[3:], on))
            used |= lines
        elif len(data) >= 7 and not on:
            legacy.append((data, slots, lines))
    groups: list[dict] = []
    for data, slots, lines in legacy:
        if data[2] == 1 or not groups:
            groups.append({})
        groups[-1][data[2]] = (data[3:7], slots[3:7], lines)
    for g in groups:
        parts = [g[k] for k in sorted(g)]
        data, slots = b"".join(p[0] for p in parts), [s for p in parts for s in p[1]]
        pad = len(data) - len(data.lstrip(b"\x00"))
        if len(data) - pad == 17:
            found.append((data[pad:].decode("latin-1"), slots[pad:], False))
            for p in parts:
                used |= p[2]
    return found, used


def _status(line: str) -> bool:
    s = line.strip().upper()
    return (not s or s.startswith(("SEARCHING", "BUS INIT")) or any(m in s for m in ERROR_MARKERS)
            or s.split()[:2] == ["7F", "09"])


def _decoded(rx: list[str]) -> list[str]:
    """The VIN candidates the scanner's own decoders read from a reply (CAN and legacy layouts)."""
    return [p[3:20].decode("ascii", errors="replace") for p in parse_all(rx, 0x49) if p[1:2] == b"\x02"] + parse_vin_legacy(rx)


def _mask_row(row: dict) -> tuple[list[str], list[str], str | None]:
    """(masked rx, original VINs found, why the row cannot be trusted or None)."""
    rx = row["rx"]
    found, used = _locate(rx)
    out = list(rx)
    for _vin, slots, _on in found:
        for li, col in slots[11:]:
            out[li] = out[li][:col] + "30" + out[li][col + 2:]
    if not found and row.get("tx") != "0902":
        return out, [], None
    if row.get("tx") == "0902" and any(i not in used and not _status(ln) for i, ln in enumerate(rx)):
        return out, [v for v, _, _ in found], "a VIN reply in a layout that cannot be masked"
    again, _ = _locate(out)
    decoded = _decoded(out)
    ok = all(v[11:] == MASK for v, _, _ in again) and all(len(c) != 17 or c[11:] == MASK for c in decoded)
    for vin, _slots, on in found:  # headers-on replies are not read by the scanner's decoders: checked by _locate
        ok = ok and masked_vin(vin) in ([v for v, _, _ in again] if on else decoded)
    return out, [v for v, _, _ in found], None if ok else "masking did not verify"


def _mask_tokens(text: str, found: set) -> str:
    """Mask every VIN-shaped token (17 VIN characters with letters and digits) in plain text."""
    def sub(m):
        t = m.group()
        if not (any(c.isalpha() for c in t) and any(c.isdigit() for c in t)):
            return t
        found.add(t.upper())
        return masked_vin(t)
    return _VIN_TOKEN.sub(sub, text)


def _mask_transcript(text: str) -> tuple[str, list[dict], set, str | None, str | None]:
    """(masked text, masked rows, VINs found, why it must be left out or None, the first valid VIN read). Lines that
    are not readable records are dropped."""
    lines, rows, vins, problem, first = [], [], set(), None, None
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        rx = row.get("rx") if isinstance(row, dict) else None
        if not isinstance(rx, list) or not all(isinstance(x, str) for x in rx):
            continue
        out, found, why = _mask_row(row)
        vins.update(found)
        first = first or next((v for v in found if VIN_RE.fullmatch(v)), None)
        problem = problem or why
        if out != rx:
            row = {**row, "rx": out}
            line = json.dumps(row)
        lines.append(line)
        rows.append(row)
    body = "\n".join(lines) + ("\n" if lines else "")
    return _mask_tokens(body, vins), rows, vins, problem, first


def _hex_bytes(rx: list[str]) -> list[int]:
    """Every two-digit hex byte in a reply, in order, skipping frame numbers, 3-digit ids and words."""
    out = []
    for ln in rx:
        for tok in ln.split():
            if len(tok) % 2 == 0 and re.fullmatch(r"[0-9A-Fa-f]+", tok):
                out += bytes.fromhex(tok)
    return out


def _gapped(seq: list[int], want: bytes) -> bool:
    """True if want occurs in seq in order with at most _GAP other bytes between neighbours."""
    ends = [i for i, b in enumerate(seq) if b == want[0]]
    for w in want[1:]:
        ends = [j for j in range(len(seq)) if seq[j] == w and any(0 < j - i <= _GAP + 1 for i in ends)]
        if not ends:
            return False
    return True


def _leaks(text: str, vins: set[str], rows: list[dict] = ()) -> bool:
    """True if any original VIN, its serial as text, or the serial's bytes (as hex text, or spread over one reply's
    frames) is still present."""
    up = text.upper()
    for v in vins:
        serial = v[11:]
        if serial == MASK:
            continue
        sb = serial.encode("latin-1")
        if v.upper() in up or re.search(r"(?<![0-9.])" + re.escape(serial.upper()) + r"(?![0-9])", up):
            return True
        if re.search(_SEP.join("%02X" % b for b in sb), up):
            return True
        if any(_gapped(_hex_bytes(r.get("rx") or []), sb) for r in rows):
            return True
    return False


def _app_version() -> str:
    from obd_reader import __version__
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).parent, capture_output=True,
                             text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return f"shadetree-ai {__version__}" + (f" (commit {out})" if re.fullmatch(r"[0-9a-f]{4,40}", out) else "")


def _readme(runs: list[str], transcripts: list[str], left_out: list[str], when: str, vehicles: list[str]) -> str:
    lines = [
        "shadetree-ai: recorded runs to share",
        "",
        "What is inside",
        "  runs/          the saved runs (the live console's Save run files): " + (", ".join(runs) or "none"),
        "  transcripts/   the raw adapter conversation behind each run: " + (", ".join(transcripts) or "none"),
        "  SUMMARY.txt    a short computed summary per run: protocol, trouble codes, warning lamp, channel statistics",
        "  README.txt     this file",
        "",
        "The VIN",
        "  The VIN's serial number (its last six characters, 12-17) is replaced with 000000 everywhere in this file,",
        "  in the text and in the raw reply bytes. Characters 1-11 (maker, model, model year, plant) stay, so the",
        "  maintainer can tell what kind of car it is but not which car. Every transcript was checked after masking;",
        "  one that did not pass the check is left out. Lines of a transcript that are not readable records are dropped.",
    ]
    lines += ["", "Vehicles (VIN serial masked)"] + [f"  {x}" for x in vehicles]
    if left_out:
        lines += ["", "Left out"] + [f"  {x}" for x in left_out]
    lines += ["", f"Made by {_app_version()} on {when}.", "",
              "Send it", f"  Attach this .zip to a new issue at {ISSUES_URL} and say what the car is doing,",
              "  or email it to the maintainer. It is safe to attach to a public issue."]
    return "\n".join(lines) + "\n"


def build_zip(home, run_names) -> tuple[bytes, list[str]]:
    """A .zip of the named runs from home/runs, their transcripts, SUMMARY.txt and README.txt, with the VIN's
    serial masked everywhere. Returns (zip bytes, what was left out and why). Raises ValueError or FileNotFoundError
    for an empty selection or a name that is not one of the user's runs."""
    from obd_reader.replay_run import read_run_file

    home = Path(home)
    rdir, tdir = home / "runs", (home / "transcripts").resolve()
    names = list(dict.fromkeys(run_names))
    if not names:
        raise ValueError("pick at least one run")
    vins: set[str] = set()
    runs, txs = [], {}
    for n in names:
        read_run_file(rdir, n)  # the replay route's rules: a plain name, a regular file in runs/, readable JSON
        text = _mask_tokens((rdir / n).read_text(encoding="utf-8"), vins)
        tp = _transcript_for(home, rdir / n)
        if tp is not None and (tp.parent != tdir or tp.suffix != ".jsonl"):
            tp = None
        if tp is not None and tp.name not in txs:
            txs[tp.name] = _mask_transcript(tp.read_text(encoding="utf-8", errors="replace"))
            vins |= txs[tp.name][2]
        runs.append((n, text, tp.name if tp else None))
    left_out, withheld = [], {}
    for name, (text, rows, _v, problem, _f) in list(txs.items()):
        if problem or _leaks(text, vins, rows):
            left_out.append(f"transcripts/{name}: {problem or 'masking did not verify'}")
            withheld[name] = txs.pop(name)[4]
    kept, vehicles = [], {}
    for n, text, tx in runs:
        obj = json.loads(text)
        obj = obj if isinstance(obj, dict) else {}
        veh = obj.get("vehicle") if isinstance(obj.get("vehicle"), dict) else {}
        own = obj.get("vehicle_key") or veh.get("key")
        read = txs[tx][4] if tx in txs else withheld.get(tx)  # the first valid VIN the transcript's 0902 replies gave
        verified = read is not None and tx in txs  # its transcript passed: the scanner's decoder read the masked VIN
        key = vehicle_key(read) if read else own if isinstance(own, str) else None
        add = {"vin_masked": masked_vin(read)} if verified else {}
        if key:
            add["vehicle_key"] = key
        if any(obj.get(k) != v for k, v in add.items()):
            text = json.dumps({**obj, **add}, indent=2)
        why = ("its transcript was left out, so the masked VIN is not verified" if read else
               "no transcript" if tx is None else "the transcript has no VIN")
        vehicles[n] = f"vehicle key {key or 'unknown'}, " + (f"VIN {masked_vin(read)}" if verified else f"VIN not shown ({why})")
        if _leaks(n + "\n" + text, vins):
            left_out.append(f"runs/{n}: masking did not verify")
        else:
            kept.append((n, text, tx))
    summaries = [summarize(n, tx if tx in txs else ("left out (see README.txt)" if tx else "none found"),
                           txs[tx][1] if tx in txs else []) + f"vehicle: {vehicles[n]}\n" for n, _t, tx in kept]
    used = [tx for tx in dict.fromkeys(tx for _n, _t, tx in kept) if tx in txs]
    now = datetime.now(timezone.utc)
    members = {f"runs/{n}": text for n, text, _tx in kept}
    members.update({f"transcripts/{tx}": txs[tx][0] for tx in used})
    members["SUMMARY.txt"] = "\n".join(summaries)
    members["README.txt"] = _readme([n for n, _t, _x in kept], used, left_out, f"{now:%Y-%m-%d %H:%M} UTC",
                                    [f"runs/{n}: {vehicles[n]}" for n, _t, _x in kept])
    for name in ("SUMMARY.txt", "README.txt"):
        if _leaks(members[name], vins):
            raise ExportError(f"{name} did not pass the VIN check; nothing was written")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in members.items():
            info = zipfile.ZipInfo(name, date_time=now.timetuple()[:6])
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, text.encode("utf-8"))
    return buf.getvalue(), left_out
