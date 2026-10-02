"""The only module allowed to import `serial`. Every write goes through the gate."""
import json
import time
from pathlib import Path
from typing import Callable, Protocol

from obd_reader.allowlist import ForbiddenCommand, check_command


class AdapterNotReady(RuntimeError):
    """The adapter never returned its '>' prompt, so it may still be busy; nothing more is sent."""


class Port(Protocol):
    def write(self, data: bytes) -> None: ...
    def read_until_prompt(self, timeout: float) -> str: ...
    def close(self) -> None: ...


class TranscriptRecorder:
    def __init__(self, path: Path):
        self.path = Path(path)
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
        default_timeout: float = 5.0,
    ):
        self._port = port
        self._recorder = recorder
        self._clock = clock
        self._t0 = clock()
        self._default_timeout = default_timeout

    @property
    def transcript_path(self) -> Path | None:
        return self._recorder.path if self._recorder is not None else None

    def send(self, cmd: str, timeout: float | None = None) -> list[str]:
        canon = check_command(cmd)  # raises before anything touches the port
        self._port.write(canon.encode("ascii") + b"\r")
        raw = self._port.read_until_prompt(self._default_timeout if timeout is None else timeout)
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
        self._prompt_seen = True  # nothing outstanding yet
        self.recovery_s = 2.0     # how long to wait for a missing prompt before refusing to write

    def _wait_for_prompt(self) -> None:
        """The last reply timed out without '>': the ELM may still be busy, and a new byte
        would interrupt it. Wait briefly for the prompt; never write into a busy adapter."""
        deadline = time.monotonic() + self.recovery_s
        while time.monotonic() < deadline:
            if b">" in self._ser.read(64):
                self._prompt_seen = True
                return
        raise AdapterNotReady("the adapter has not finished the previous command (no '>' prompt); nothing was sent")

    def write(self, data: bytes) -> None:
        # Second gate: SerialPort is public, so it refuses anything that is not
        # exactly one canonical allowlisted command plus a single CR.
        if not data.endswith(b"\r") or not data[:-1].isascii():
            raise ForbiddenCommand(f"not one CR-terminated ASCII command: {data!r}")
        body = data[:-1].decode("ascii")
        if check_command(body) != body:
            raise ForbiddenCommand(f"not a canonical command: {data!r}")
        if not self._prompt_seen:
            self._wait_for_prompt()
        self._ser.reset_input_buffer()  # drop any late reply to the previous command
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
        self._prompt_seen = b">" in buf
        return buf.decode("ascii", errors="replace").split(">", 1)[0]

    def close(self) -> None:
        self._ser.close()
