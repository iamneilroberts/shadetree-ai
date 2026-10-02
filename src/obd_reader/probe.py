"""`shadetree-ai probe`: what a car supports and how it answers, as a report that is safe to share.

The report comes from a scan() snapshot taken with the Mode 06 bitmap pass on. It keeps the vehicle key
(WMI + VDS + model-year character), protocol, adapter, ECU headers, Mode 09 identity items (calibration
versions, shared by every car with that software), the supported-PID bitmaps, every reply class with its
latency, and the raw bytes of undecoded PIDs. It never carries the VIN, the VIN serial or the transcript,
and write_probe refuses to write a report that has a VIN-looking token in it."""
import json
import statistics
from collections import Counter
from pathlib import Path

from obd_reader.snapshot import Snapshot
from obd_reader.vehicle import vehicle_key
from obd_reader.vin import find_vins


def report(snap: Snapshot) -> dict:
    return {
        "probe_id": snap.snapshot_id,
        "captured_at": snap.captured_at.isoformat(),
        "source": snap.source.kind,
        "tool_version": snap.source.tool_version,
        "vehicle_key": vehicle_key(snap.vehicle.vin),
        "protocol": snap.protocol.model_dump(),
        "adapter": snap.source.adapter.model_dump(),
        "ecus": [e.header for e in snap.ecus],
        "mode09": snap.mode09.model_dump(),
        "supported_pids": snap.supported_pids,
        "replies": [r.model_dump() for r in snap.replies],
        "undecoded": [u.model_dump() for u in snap.undecoded],
        # a VIN warning can quote the VIN (or an invalid one): keep only its lead-in
        "warnings": [w.split(":", 1)[0] if "VIN" in w else w for w in snap.warnings],
    }


def markdown(rep: dict) -> str:
    j = lambda xs, none="none": ", ".join(xs) or none  # noqa: E731
    a, m9, sp, rs = rep["adapter"], rep["mode09"], rep["supported_pids"], rep["replies"]
    ms = [r["ms"] for r in rs if r["ms"] is not None]
    counts = Counter(r["reply"] for r in rs)
    lines = [
        f"# Probe {rep['probe_id']}", "",
        "No VIN, VIN serial or transcript in this report.", "",
        f"- vehicle key: {rep['vehicle_key'] or 'not read'}",
        f"- protocol: {rep['protocol']['name'] or 'unknown'}",
        f"- adapter: {a['ati'] or 'unknown'} / {a['sti'] or 'not STN'}" + (f" / {a['device']}" if a["device"] else ""),
        f"- ECUs: {j(rep['ecus'])}",
        f"- ECU names: {j(m9['ecu_names'])}; CAL IDs: {j(m9['cal_ids'])}; CVNs: {j(m9['cvns'])}",
        *(f"- Mode {m} supported: {j(sp.get(m, []), 'not advertised or not read')}" for m in ("01", "09", "06")),
        f"- replies: {len(rs)} ({j([f'{k} {n}' for k, n in sorted(counts.items())])})"
        + (f"; latency median {statistics.median(ms):g} ms, max {max(ms):g} ms" if ms else ""),
        "- not ok: " + j([r["cmd"] + " " + r["reply"] for r in rs if r["reply"] != "ok"]),
        "- undecoded PIDs: " + j([u["pid"] + " " + u["reply"] + " [" + " ".join(u["raw"]) + "]" for u in rep["undecoded"]]),
        *(f"- warning: {w}" for w in rep["warnings"]),
    ]
    return "\n".join(lines) + "\n"


def write_probe(snap: Snapshot, out_dir: Path) -> tuple[Path, Path]:
    """Write probes/<snapshot_id>.json and .md under out_dir. Never overwrites."""
    rep = report(snap)
    text, md = json.dumps(rep, indent=2) + "\n", markdown(rep)
    if find_vins(text + md):
        raise RuntimeError("the probe report contains a VIN-looking token; nothing was written")
    d = Path(out_dir) / "probes"
    d.mkdir(parents=True, exist_ok=True)
    j_path, m_path = d / f"{snap.snapshot_id}.json", d / f"{snap.snapshot_id}.md"
    if j_path.exists() or m_path.exists():
        raise FileExistsError(f"probe already exists: {snap.snapshot_id}")
    for path, body in ((j_path, text), (m_path, md)):
        with open(path, "x", encoding="utf-8") as fh:
            fh.write(body)
    return j_path, m_path
