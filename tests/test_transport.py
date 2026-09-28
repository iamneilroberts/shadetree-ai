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


def test_forbidden_command_is_not_recorded(tmp_path):
    path = tmp_path / "t.jsonl"
    rec = TranscriptRecorder(path)
    t = Transport(SpyPort(), recorder=rec)
    with pytest.raises(ForbiddenCommand):
        t.send("04")
    rec.close()
    assert path.read_text() == ""


def test_serial_port_reads_up_to_prompt_using_loopback():
    port = SerialPort("loop://")
    port._ser.write(b"NO DATA\r\r>")
    assert port.read_until_prompt(1.0) == "NO DATA\r\r"
    port.close()
