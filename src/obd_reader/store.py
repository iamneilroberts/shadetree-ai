"""Path-safe snapshot storage under <home>/snapshots/."""
import json
import re
from pathlib import Path

from pydantic import ValidationError

from obd_reader.snapshot import Snapshot

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")


class InvalidSnapshotId(ValueError):
    pass


class SnapshotStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.dir = self.root / "snapshots"

    def path(self, snapshot_id: str) -> Path:
        if not isinstance(snapshot_id, str) or not _ID_RE.fullmatch(snapshot_id) or ".." in snapshot_id:
            raise InvalidSnapshotId("snapshot ids are 1-80 chars of letters, digits, '.', '_' and '-'")
        return self.dir / f"{snapshot_id}.json"

    def save(self, snap: Snapshot) -> Path:
        path = self.path(snap.snapshot_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8") as fh:
            fh.write(snap.model_dump_json(indent=2) + "\n")
        return path

    def load(self, snapshot_id: str) -> Snapshot:
        path = self.path(snapshot_id)
        if not path.is_file():
            raise FileNotFoundError(f"no snapshot named {snapshot_id!r}")
        return Snapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        rows = []
        for path in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            try:
                s = Snapshot.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValidationError, ValueError):
                continue
            rows.append({"snapshot_id": s.snapshot_id, "captured_at": s.captured_at.isoformat(),
                         "protocol": s.protocol.name, "stored_dtcs": len(s.dtcs.stored)})
        return sorted(rows, key=lambda r: r["captured_at"])

    def import_file(self, path: Path) -> Snapshot:
        src = Path(path).resolve()
        if src.suffix != ".json" or not src.is_file() or not src.is_relative_to(self.root):
            raise ValueError("import only reads .json files inside the data directory")
        try:
            snap = Snapshot.model_validate(json.loads(src.read_text(encoding="utf-8")))
        except (ValidationError, ValueError):
            raise ValueError("file is not a valid snapshot") from None  # never echo the content
        self.save(snap)
        return snap
