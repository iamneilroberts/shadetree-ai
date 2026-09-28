"""A Port that answers from a recorded transcript: no adapter, no car."""
import json
from collections import defaultdict, deque
from pathlib import Path


def load_transcript(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


class ReplayPort:
    def __init__(self, records: list[dict]):
        self._queues: dict[str, deque] = defaultdict(deque)
        for r in records:
            self._queues[r["tx"]].append(r["rx"])
        self.written: list[str] = []
        self.unmatched: list[str] = []
        self._pending = ""

    @classmethod
    def from_file(cls, path: Path) -> "ReplayPort":
        return cls(load_transcript(path))

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        self.written.append(cmd)
        queue = self._queues.get(cmd)
        if queue:
            rx = queue.popleft()
        else:
            self.unmatched.append(cmd)
            rx = ["?"]  # what a real ELM answers to an unknown command
        self._pending = "\r".join(rx) + "\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def close(self) -> None:
        pass
