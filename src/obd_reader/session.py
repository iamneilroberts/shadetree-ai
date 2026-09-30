"""Live-adapter session: config from the environment, one connection at a time,
every command recorded to a transcript."""
import math
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping

from obd_reader.adapter import init_adapter
from obd_reader.store import SnapshotStore
from obd_reader.transport import Port, SerialPort, TranscriptRecorder, Transport


class NoAdapterError(RuntimeError):
    """SHADETREE_PORT is not set, so live tools cannot reach an adapter."""


class AdapterBusy(RuntimeError):
    """Another tool call is using the adapter."""


@dataclass
class Config:
    port: str | None
    baud: int = 115200
    timeout: float = 10.0
    home: Path = field(default_factory=lambda: Path("."))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        timeout = float(env.get("SHADETREE_TIMEOUT", 10))
        if not math.isfinite(timeout) or timeout <= 0:  # nan would make every read return at once
            raise ValueError("SHADETREE_TIMEOUT must be a positive, finite number of seconds")
        return cls(
            port=env.get("SHADETREE_PORT") or None,
            baud=int(env.get("SHADETREE_BAUD", 115200)),
            timeout=timeout,
            home=Path(env.get("SHADETREE_HOME", ".")),
        )


class Session:
    def __init__(
        self,
        config: Config,
        port_factory: Callable[[], Port] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.store = SnapshotStore(config.home)
        self.clock, self.sleep = clock, sleep
        self._lock = threading.Lock()
        self._factory = port_factory or (lambda: SerialPort(config.port, baudrate=config.baud))

    def _acquire(self) -> None:
        if not self.config.port:
            raise NoAdapterError("SHADETREE_PORT is not set; live tools need the adapter's serial port")
        if not self._lock.acquire(blocking=False):
            raise AdapterBusy("the adapter is busy with another tool call; try again in a moment")

    @contextmanager
    def raw_port(self) -> Iterator[Port]:
        """A fresh port under the same lock, for callers (scan) that build their own Transport."""
        self._acquire()
        port = None
        try:
            port = self._factory()
            yield port
        finally:
            if port is not None:
                port.close()
            self._lock.release()

    @contextmanager
    def connection(self, label: str, protocol: str | None = "0") -> Iterator[Transport]:
        self._acquire()
        transport = None
        try:
            tdir = Path(self.config.home) / "transcripts"
            tdir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
            recorder = TranscriptRecorder(tdir / f"{stamp}-{label}.jsonl")
            transport = Transport(self._factory(), recorder=recorder, default_timeout=self.config.timeout)
            init_adapter(transport, protocol)
            yield transport
        finally:
            if transport is not None:
                transport.close()
            self._lock.release()
