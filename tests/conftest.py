import pytest


class SpyPort:
    """Records every byte string written; replies with a canned response."""

    def __init__(self, reply: str = "OK\r"):
        self.writes: list[bytes] = []
        self.reply = reply

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def read_until_prompt(self, timeout: float) -> str:
        return self.reply

    def close(self) -> None:
        pass


@pytest.fixture
def spy():
    return SpyPort()


class ScriptedPort:
    """Answers `01PP` from a table of raw data hex; anything else gets OK, unknown PIDs NO DATA.
    Like a real adapter it honours ATH1: replies then carry one ECU's CAN id and PCI byte ("7E8 04 41 0C 1A F8")."""

    def __init__(self, pid_data: dict[str, str]):
        self.pid_data = pid_data
        self.writes: list[str] = []
        self._pending = ""
        self.headers = False

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        self.writes.append(cmd)
        if cmd.startswith("01") and len(cmd) == 4:
            pid = cmd[2:]
            msg = f"41 {pid} {self.pid_data[pid]}" if pid in self.pid_data else None
            if msg and self.headers:
                b = bytes.fromhex(msg.replace(" ", ""))
                msg = f"7E8 {len(b):02X} " + " ".join(f"{x:02X}" for x in b)
            self._pending = f"{msg}\r" if msg else "NO DATA\r"
        else:
            if cmd in ("ATH0", "ATH1", "ATZ"):
                self.headers = cmd == "ATH1"
            self._pending = "OK\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def close(self) -> None:
        pass


class FakeClock:
    """A clock that only moves when the code under test sleeps."""

    def __init__(self):
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


REVIEWED_TOOLS = frozenset({
    "list_snapshots", "get_snapshot", "import_snapshot", "read_dtcs", "freeze_frame", "readiness",
    "vehicle_info", "list_supported_pids", "compare_snapshots", "adapter_info", "scan", "read_pid",
    "live_data", "trim_summary", "mode06_tests", "open_console", "console_data",
})
"""The literal, human-reviewed tool list. Do not derive it from the code under test."""


class RampPort(ScriptedPort):
    """Engine RPM rises by 10 on every read, so exact stats differ from any subsample's stats."""

    def __init__(self):
        super().__init__({})
        self.n = 0

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        if cmd == "010C":
            self.n += 1
            self.writes.append(cmd)
            self._pending = f"41 0C {self.n * 40:04X}\r"
        else:
            super().write(data)


@pytest.fixture
def elm_server():
    """A TCP 'adapter' that answers like an ELM from transcript records (rx lines, then '>').
    `elm_server(records)` returns a `socket://` URL for SerialPort, so a live CLI path runs end to end."""
    import socket
    import threading

    from obd_reader.replay import ReplayPort

    socks = []

    def start(records):
        port = ReplayPort(records)
        srv = socket.create_server(("127.0.0.1", 0))
        socks.append(srv)

        def serve():
            conn, _ = srv.accept()
            buf = b""
            with conn:
                while chunk := conn.recv(256):
                    buf += chunk
                    while b"\r" in buf:
                        cmd, buf = buf.split(b"\r", 1)
                        port.write(cmd + b"\r")
                        conn.sendall(port.read_until_prompt(0).encode("ascii") + b"\r>")

        threading.Thread(target=serve, daemon=True).start()
        return f"socket://127.0.0.1:{srv.getsockname()[1]}"

    yield start
    for s in socks:
        s.close()
