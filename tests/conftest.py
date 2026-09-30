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
    """Answers `01PP` from a table of raw data hex; anything else gets OK, unknown PIDs NO DATA."""

    def __init__(self, pid_data: dict[str, str]):
        self.pid_data = pid_data
        self.writes: list[str] = []
        self._pending = ""

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        self.writes.append(cmd)
        if cmd.startswith("01") and len(cmd) == 4:
            pid = cmd[2:]
            self._pending = (f"41 {pid} {self.pid_data[pid]}\r" if pid in self.pid_data else "NO DATA\r")
        else:
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
