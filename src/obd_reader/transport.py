"""The only module allowed to import `serial`. Every write goes through the gate."""
import json
import time
from pathlib import Path
from typing import Callable, Protocol

from obd_reader.allowlist import ForbiddenCommand, check_command


class Port(Protocol):
    def write(self, data: bytes) -> None: ...
    def read_until_prompt(self, timeout: float) -> str: ...
    def close(self) -> None: ...


class TranscriptRecorder:
    def __init__(self, path: Path):
        self._fh = open(path, "x", encoding="utf-8")  # never overwrite a real capture

    def record(self, t: float, tx: str, rx: list[str]) -> None:
        self._fh.write(json.dumps({"t": round(t, 3), "tx": tx, "rx": rx}) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class Transport:
    def __init__(
        self,
        port: Port,
        recorder: TranscriptRecorder | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._port = port
        self._recorder = recorder
        self._clock = clock
        self._t0 = clock()

    def send(self, cmd: str, timeout: float = 5.0) -> list[str]:
        canon = check_command(cmd)  # raises before anything touches the port
        self._port.write(canon.encode("ascii") + b"\r")
        raw = self._port.read_until_prompt(timeout)
        lines = [ln.strip() for ln in raw.replace("\r", "\n").split("\n") if ln.strip()]
        if self._recorder is not None:
            self._recorder.record(self._clock() - self._t0, canon, lines)
        return lines

    def close(self) -> None:
        self._port.close()
        if self._recorder is not None:
            self._recorder.close()


class SerialPort:
    """pyserial-backed Port (USB serial, rfcomm, socket://, loop:// for tests)."""

    def __init__(self, url: str, baudrate: int = 115200):
        import serial

        self._ser = serial.serial_for_url(url, baudrate=baudrate, timeout=0.1)

    def write(self, data: bytes) -> None:
        # Second gate: SerialPort is public, so it refuses anything that is not
        # exactly one canonical allowlisted command plus a single CR.
        if not data.endswith(b"\r") or not data[:-1].isascii():
            raise ForbiddenCommand(f"not one CR-terminated ASCII command: {data!r}")
        body = data[:-1].decode("ascii")
        if check_command(body) != body:
            raise ForbiddenCommand(f"not a canonical command: {data!r}")
        self._ser.write(data)

    def read_until_prompt(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._ser.read(64)
            if chunk:
                buf += chunk
                if b">" in buf:
                    break
        return buf.decode("ascii", errors="replace").split(">", 1)[0]

    def close(self) -> None:
        self._ser.close()
