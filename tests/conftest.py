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
