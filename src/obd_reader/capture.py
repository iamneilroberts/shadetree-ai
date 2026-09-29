"""Run a scan on a Port and save the raw transcript and the parsed snapshot."""
import re
from datetime import datetime, timezone
from pathlib import Path

from obd_reader.scanner import scan
from obd_reader.snapshot import Snapshot
from obd_reader.transport import Port, TranscriptRecorder, Transport

_LABEL_RE = re.compile(r"[a-z0-9-]{1,40}")


def capture(
    port: Port,
    out_dir: Path,
    *,
    label: str,
    protocol: str = "0",
    timeout: float = 10.0,
    now: datetime | None = None,
) -> tuple[Snapshot, Path, Path]:
    if not _LABEL_RE.fullmatch(label):
        raise ValueError("label must be 1-40 chars of [a-z0-9-]")
    now = now or datetime.now(timezone.utc)
    snapshot_id = f"{now:%Y-%m-%dT%H-%M-%SZ}-{label}"
    transcripts, snapshots = Path(out_dir) / "transcripts", Path(out_dir) / "snapshots"
    transcripts.mkdir(parents=True, exist_ok=True)
    snapshots.mkdir(parents=True, exist_ok=True)
    t_path = transcripts / f"{snapshot_id}.jsonl"
    s_path = snapshots / f"{snapshot_id}.json"
    if s_path.exists() or t_path.exists():  # fail before anything is sent to the car
        raise FileExistsError(f"capture already exists: {snapshot_id}")

    transport = Transport(port, recorder=TranscriptRecorder(t_path), default_timeout=timeout)
    try:
        snap = scan(
            transport,
            snapshot_id=snapshot_id,
            captured_at=now,
            kind="live",
            protocol=protocol,
            transcript=str(t_path),
        )
    finally:
        transport.close()  # the transcript stays on disk even if the scan raised
    with open(s_path, "x", encoding="utf-8") as fh:
        fh.write(snap.model_dump_json(indent=2) + "\n")
    return snap, s_path, t_path
