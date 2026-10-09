"""The only module allowed to import `serial`. Every write goes through the gate."""
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

from obd_reader.allowlist import MONITOR_COMMANDS, RAW_ON, ForbiddenCommand, check_command


class AdapterNotReady(RuntimeError):
    """The adapter never returned its '>' prompt, so it may still be busy; nothing more is sent."""


class SilentModeUnsupported(RuntimeError):
    """The adapter did not accept ATCSM1, so it might ACK frames on a CAN bus; nothing was monitored."""


MAX_MONITOR_S = 900.0
ADAPTER_STOPS = frozenset({"BUFFER FULL", "CAN ERROR", "BUS ERROR", "STOPPED", "?"})  # the adapter's reasons for leaving a monitor


@dataclass(frozen=True)
class MonitorEvent:
    kind: str  # "frame" (text = the raw line), "gap" (text = what stopped the stream) or "idle" (a read with nothing in it)
    t: float  # seconds since the transport opened
    text: str = ""
    seconds: float = 0.0  # gap: until frames resumed, or the monitor ended


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
        self._raw = False  # ATCAF0 on (inside monitor() only)
        self._monitoring = False  # a stream is open: any send() would transmit mid-listen or eat its prompt

    @property
    def transcript_path(self) -> Path | None:
        return self._recorder.path if self._recorder is not None else None

    @property
    def now(self) -> float:
        return self._clock() - self._t0

    def send(self, cmd: str, timeout: float | None = None) -> list[str]:
        canon = check_command(cmd)  # raises before anything touches the port
        if canon in MONITOR_COMMANDS:
            raise ForbiddenCommand(f"{canon} streams until stopped: only Transport.monitor() sends it")
        if self._raw and canon[:2] not in ("AT", "ST"):
            raise ForbiddenCommand(f"raw CAN mode (ATCAF0) is on: {canon!r} is refused")
        if self._monitoring:
            raise ForbiddenCommand(f"a monitor stream is open: {canon!r} is refused until it is closed")
        return self._exchange(canon, timeout)

    def _exchange(self, canon: str, timeout: float | None = None) -> list[str]:
        self._port.write(canon.encode("ascii") + b"\r")
        raw = self._port.read_until_prompt(self._default_timeout if timeout is None else timeout)
        lines = [ln.strip() for ln in raw.replace("\r", "\n").split("\n") if ln.strip()]
        if self._recorder is not None:
            self._recorder.record(self._clock() - self._t0, canon, lines)
        return lines

    def monitor(self, cmd: str, seconds: float, *, can: bool) -> Iterator[MonitorEvent]:
        """Listen only: stream every bus frame for up to `seconds`. Nothing is transmitted between the monitor
        command and the returning prompt; closing the iterator stops the adapter and restores ATCAF1."""
        canon = check_command(cmd)
        if canon not in MONITOR_COMMANDS:
            raise ForbiddenCommand(f"not a monitor command: {cmd!r}")
        if not (isinstance(seconds, (int, float)) and math.isfinite(seconds) and 0 < seconds <= MAX_MONITOR_S):
            raise ValueError(f"seconds must be in (0, {MAX_MONITOR_S:g}]")
        if not (hasattr(self._port, "read_available") and hasattr(self._port, "interrupt")):
            raise ValueError("this port cannot monitor (no streaming read)")
        if can:
            reply = self.send("ATCSM1")
            if "OK" not in reply:
                raise SilentModeUnsupported(f"the adapter answered {reply!r} to ATCSM1 (silent CAN monitoring); nothing was monitored")
        return self._stream(canon, seconds, can)

    def _stream(self, canon: str, seconds: float, can: bool) -> Iterator[MonitorEvent]:
        port, prompt = self._port, True
        try:
            self._monitoring = True
            if can:
                self._raw = True  # the port treats ATCAF0 as on once written, so restore even if it is refused
                self._exchange(RAW_ON)
            end = self._clock() + seconds
            self._start(canon)
            prompt = False
            buf, gap = "", None
            while self._clock() < end:
                chunk = port.read_available(0.1)
                now = self.now
                if not chunk:
                    yield MonitorEvent("idle", now)
                    continue
                if ">" in chunk:
                    chunk, prompt = chunk.split(">", 1)[0], True  # back at the prompt: the stream ended
                *lines, buf = (buf + chunk).replace("\r", "\n").split("\n")
                if prompt:
                    lines, buf = lines + [buf], ""
                for ln in (x.strip() for x in lines):
                    if not ln:
                        continue
                    if ln in ADAPTER_STOPS:
                        gap = gap or (now, ln)
                        continue
                    if gap:
                        yield MonitorEvent("gap", gap[0], gap[1], now - gap[0])
                        gap = None
                    yield MonitorEvent("frame", now, ln)
                if prompt:
                    gap = gap or (now, "prompt")
                    if self._clock() < end:
                        self._start(canon)
                        prompt = False
            if gap:
                yield MonitorEvent("gap", gap[0], gap[1], self.now - gap[0])
        finally:
            if not prompt:
                port.interrupt()
                port.read_until_prompt(self._default_timeout)  # drains "STOPPED" and the prompt
            try:
                if self._raw:
                    for _ in range(2):  # a stray CR can restart the monitor and swallow the first ATCAF1
                        if "OK" in self._exchange("ATCAF1"):
                            self._raw = False
                            break
            finally:
                self._monitoring = False

    def _start(self, canon: str) -> None:
        self._port.write(canon.encode("ascii") + b"\r")  # no read_until_prompt: the reply is the stream
        if self._recorder is not None:
            self._recorder.record(self.now, canon, ["(monitor stream: see the capture file)"])

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
        self._raw = False  # ATCAF0 sent and not undone: only AT/ST commands may follow

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
        # exactly one canonical allowlisted command (or the monitor's ATCAF0) plus a single CR.
        if not data.endswith(b"\r") or not data[:-1].isascii():
            raise ForbiddenCommand(f"not one CR-terminated ASCII command: {data!r}")
        body = data[:-1].decode("ascii")
        if body != RAW_ON and check_command(body) != body:
            raise ForbiddenCommand(f"not a canonical command: {data!r}")
        if self._raw and body[:2] not in ("AT", "ST"):
            raise ForbiddenCommand(f"raw CAN mode (ATCAF0) is on: {body!r} is refused")
        if not self._prompt_seen:
            self._wait_for_prompt()
        self._ser.reset_input_buffer()  # drop any late reply to the previous command
        self._ser.write(data)
        self._prompt_seen = False
        if body == RAW_ON:
            self._raw = True
        elif body in ("ATCAF1", "ATZ", "ATD"):
            self._raw = False

    def read_until_prompt(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            # what is already buffered, else one byte: read(64) waited the whole 0.1 s timeout for any shorter reply
            chunk = self._ser.read(self._ser.in_waiting or 1)
            if chunk:
                buf += chunk
                if b">" in buf:
                    break
        self._prompt_seen = b">" in buf
        return buf.decode("ascii", errors="replace").split(">", 1)[0]

    def read_available(self, timeout: float) -> str:
        """What the adapter sends within `timeout` (a monitor stream); a '>' means it is back at the prompt."""
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._ser.read(self._ser.in_waiting or 1)
            if chunk:
                buf += chunk
                if b">" in chunk:
                    self._prompt_seen = True
                    break
            elif buf:
                break
        return buf.decode("ascii", errors="replace")

    def interrupt(self) -> None:
        """Stop a monitor stream: one CR, and only while no prompt has come back (at a prompt a CR repeats the last command)."""
        if not self._prompt_seen:
            self._ser.write(b"\r")

    def close(self) -> None:
        self._ser.close()
