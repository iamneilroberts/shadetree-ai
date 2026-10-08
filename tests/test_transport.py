import json

import pytest
from hypothesis import given, strategies as st

from obd_reader.allowlist import ForbiddenCommand, check_command
from obd_reader.transport import SerialPort, Transport, TranscriptRecorder

from conftest import SpyPort


def test_send_writes_canonical_command_with_cr_and_returns_lines():
    port = SpyPort(reply="\r41 00 BE 3F A8 13\r\r")
    t = Transport(port)
    assert t.send("01 00") == ["41 00 BE 3F A8 13"]
    assert port.writes == [b"0100\r"]


def test_forbidden_command_never_reaches_the_port(spy):
    t = Transport(spy)
    with pytest.raises(ForbiddenCommand):
        t.send("04")
    assert spy.writes == []


@given(st.text(max_size=20))
def test_fuzz_only_allowlisted_bytes_reach_the_port(s):
    port = SpyPort()
    t = Transport(port)
    try:
        t.send(s)
    except ForbiddenCommand:
        assert port.writes == []
        return
    assert len(port.writes) == 1
    written = port.writes[0]
    assert written.endswith(b"\r") and written.count(b"\r") == 1
    assert check_command(written[:-1].decode("ascii")) == written[:-1].decode("ascii")


def test_recorder_writes_jsonl(tmp_path):
    path = tmp_path / "t.jsonl"
    ticks = iter([10.0, 10.5])
    rec = TranscriptRecorder(path)
    t = Transport(SpyPort(reply="OK\r"), recorder=rec, clock=lambda: next(ticks))
    t.send("ATE0")
    rec.close()
    line = json.loads(path.read_text().splitlines()[0])
    assert line == {"t": 0.5, "tx": "ATE0", "rx": ["OK"]}


def test_recorder_refuses_to_overwrite_an_existing_capture(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("precious real capture\n")
    with pytest.raises(FileExistsError):
        TranscriptRecorder(path)
    assert path.read_text() == "precious real capture\n"


def test_forbidden_command_is_not_recorded(tmp_path):
    path = tmp_path / "t.jsonl"
    rec = TranscriptRecorder(path)
    t = Transport(SpyPort(), recorder=rec)
    with pytest.raises(ForbiddenCommand):
        t.send("04")
    rec.close()
    assert path.read_text() == ""


@pytest.mark.parametrize("data", [b"04\r", b"0100\r04\r", b"0100", b"ATCAF0\r", b"\xff\r", b""])
def test_serial_port_write_is_gated_even_when_used_directly(data):
    port = SerialPort("loop://")
    with pytest.raises(ForbiddenCommand):
        port.write(data)
    assert port._ser.in_waiting == 0  # nothing reached the (loopback) wire
    port.close()


def test_serial_port_write_accepts_a_gated_command():
    port = SerialPort("loop://")
    port.write(b"0100\r")
    assert port._ser.read(5) == b"0100\r"
    port.close()


def test_serial_port_write_discards_stale_input_first():
    # A late reply from the previous command must not be read as this answer.
    port = SerialPort("loop://")
    port._ser.write(b"STALE\r>")
    port.write(b"0100\r")
    assert port._ser.read(64) == b"0100\r"
    port.close()


def test_transport_default_timeout_is_configurable():
    seen = []

    class TimeoutSpy(SpyPort):
        def read_until_prompt(self, timeout):
            seen.append(timeout)
            return "OK\r"

    t = Transport(TimeoutSpy(), default_timeout=12.0)
    t.send("ATE0")
    t.send("ATE0", timeout=1.5)
    assert seen == [12.0, 1.5]


def test_serial_port_reads_up_to_prompt_using_loopback():
    port = SerialPort("loop://")
    port._ser.write(b"NO DATA\r\r>")
    assert port.read_until_prompt(1.0) == "NO DATA\r\r"
    port.close()


class _TimedSerial:
    """pyserial-like: bytes arrive at set times on a fake clock; read(n) returns at once if n bytes are buffered,
    else waits until they are or the 0.1 s timeout ends (pyserial's blocking read), whichever is first."""

    def __init__(self, clock, arrivals):
        self._clock, self._arrivals, self._got = clock, list(arrivals), 0

    def _buffered(self) -> bytes:
        return b"".join(b for at, b in self._arrivals if at <= self._clock[0])[self._got:]

    @property
    def in_waiting(self) -> int:
        return len(self._buffered())

    def read(self, n: int) -> bytes:
        if len(self._buffered()) < n:
            ready = [at for at, _ in self._arrivals if at > self._clock[0]]
            enough = next((at for at in sorted(ready) if len(b"".join(b for t, b in self._arrivals if t <= at)) - self._got >= n), None)
            self._clock[0] = enough if enough is not None and enough <= self._clock[0] + 0.1 else self._clock[0] + 0.1
        out = self._buffered()[:n]
        self._got += len(out)
        return out


def test_short_reply_returns_when_the_prompt_arrives_and_split_replies_assemble(monkeypatch):
    import obd_reader.transport as tr

    clock = [0.0]
    monkeypatch.setattr(tr.time, "monotonic", lambda: clock[0])
    port = SerialPort.__new__(SerialPort)
    # a short reply split over three arrivals; the prompt is in by t = 0.02 s
    port._ser = _TimedSerial(clock, [(0.005, b"41 0C"), (0.012, b" 0B 40\r"), (0.02, b"\r>")])
    assert port.read_until_prompt(1.0) == "41 0C 0B 40\r\r"
    assert clock[0] < 0.05  # read(64) waited the whole 0.1 s serial timeout here
    assert port._prompt_seen is True
