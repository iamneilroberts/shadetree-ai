import pytest
from hypothesis import given, settings, strategies as st

from conftest import FakeClock, ScriptedPort
from obd_reader.allowlist import ForbiddenCommand
from obd_reader.transport import MonitorEvent, SilentModeUnsupported, Transport


class StreamPort:
    """A monitor-capable fake: commands get replies from a table; after ATMA/STMA, each read returns the next chunk."""

    def __init__(self, chunks=(), replies=None, clock=None, fail_on_read=None):
        self.replies = {"ATCSM1": "OK", "ATCAF0": "OK", "ATCAF1": "OK", **(replies or {})}
        self.chunks, self.clock, self.fail_on_read = list(chunks), clock, fail_on_read
        self.writes, self.interrupts, self.reads, self._pending = [], 0, 0, ""

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        self.writes.append(cmd)
        self._pending = "" if cmd in ("ATMA", "STMA") else self.replies.get(cmd, "OK") + "\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def read_available(self, timeout: float) -> str:
        self.reads += 1
        if self.fail_on_read == self.reads:
            raise OSError("adapter unplugged")
        if self.clock:
            self.clock.sleep(0.1)
        return self.chunks.pop(0) if self.chunks else ""

    def interrupt(self) -> None:
        self.interrupts += 1
        self._pending = "STOPPED\r"

    def close(self) -> None:
        pass


def run(chunks, seconds=0.35, can=True, **kw):
    clk = FakeClock()
    port = StreamPort(chunks, clock=clk, **kw)
    t = Transport(port, clock=clk.now)
    return port, t, list(t.monitor("ATMA", seconds, can=can))


def test_frames_stream_with_times_and_the_adapter_is_stopped_and_restored():
    port, _, ev = run(["0C9 01 02\r1F5 00\r"])
    assert [(e.kind, e.text) for e in ev if e.kind == "frame"] == [("frame", "0C9 01 02"), ("frame", "1F5 00")]
    assert ev[0].t == pytest.approx(0.1)
    assert port.writes == ["ATCSM1", "ATCAF0", "ATMA", "ATCAF1"] and port.interrupts == 1


def test_a_line_split_across_reads_is_one_frame():
    _, _, ev = run(["0C9 01 02", " 03\r1F5 00\r"])
    assert [e.text for e in ev if e.kind == "frame"] == ["0C9 01 02 03", "1F5 00"]


def test_buffer_full_gives_a_gap_with_its_length_and_a_restart():
    port, _, ev = run(["0C9 01\rBUFFER FULL\r>", "", "0C9 02\r"], seconds=0.45)
    kinds = [(e.kind, e.text) for e in ev if e.kind != "idle"]
    assert kinds == [("frame", "0C9 01"), ("gap", "BUFFER FULL"), ("frame", "0C9 02")]
    gap = next(e for e in ev if e.kind == "gap")
    assert gap.t == pytest.approx(0.1) and gap.seconds == pytest.approx(0.2)
    assert port.writes.count("ATMA") == 2


def test_a_prompt_at_the_end_needs_no_interrupt_and_the_gap_runs_to_the_end():
    port, _, ev = run(["0C9 01\rSTOPPED\r>"], seconds=0.1)
    assert [(e.kind, e.text) for e in ev] == [("frame", "0C9 01"), ("gap", "STOPPED")]
    assert port.interrupts == 0 and port.writes[-1] == "ATCAF1"


def test_raw_mode_refuses_obd_commands_only_while_monitoring():
    clk = FakeClock()
    port = StreamPort(["0C9 01\r"], clock=clk)
    t = Transport(port, clock=clk.now)
    it = t.monitor("ATMA", 5, can=True)
    next(it)
    with pytest.raises(ForbiddenCommand, match="raw CAN mode"):
        t.send("0104")
    assert t.send("ATRV") == ["OK"]  # AT commands still pass
    it.close()
    assert port.interrupts == 1 and port.writes[-1] == "ATCAF1"
    assert t.send("0104") == ["OK"]


def test_an_exception_mid_stream_still_stops_and_restores():
    clk = FakeClock()
    port = StreamPort(["0C9 01\r"], clock=clk, fail_on_read=2)
    t = Transport(port, clock=clk.now)
    with pytest.raises(OSError):
        list(t.monitor("ATMA", 5, can=True))
    assert port.interrupts == 1 and port.writes[-1] == "ATCAF1"


@settings(max_examples=60, deadline=None)
@given(st.from_regex(r"0[0-9A][0-9A-F]{0,4}", fullmatch=True))
def test_while_raw_every_obd_command_is_refused_before_the_port(cmd):
    clk = FakeClock()
    port = StreamPort(["0C9 01\r"], clock=clk)
    t = Transport(port, clock=clk.now)
    it = t.monitor("ATMA", 5, can=True)
    next(it)
    n = len(port.writes)
    with pytest.raises(ForbiddenCommand):
        t.send(cmd)
    assert len(port.writes) == n
    it.close()


def test_can_needs_silent_mode_and_refusal_sends_no_monitor():
    port = StreamPort(replies={"ATCSM1": "?"})
    with pytest.raises(SilentModeUnsupported):
        Transport(port).monitor("ATMA", 1, can=True)
    assert port.writes == ["ATCSM1"]


def test_j1850_skips_silent_mode_and_raw_mode():
    port, _, _ = run(["88 FE 10 0B 01 02 AA\r"], can=False)
    assert port.writes == ["ATMA"]


@pytest.mark.parametrize("seconds", [0, -1, 901, float("nan"), float("inf")])
def test_seconds_must_be_in_range(seconds):
    with pytest.raises(ValueError):
        Transport(StreamPort()).monitor("ATMA", seconds, can=False)


def test_send_refuses_monitor_commands_and_monitor_refuses_other_commands():
    port = StreamPort()
    t = Transport(port)
    for cmd in ("ATMA", "STMA", "at ma"):
        with pytest.raises(ForbiddenCommand):
            t.send(cmd)
    with pytest.raises(ForbiddenCommand):
        t.monitor("ATI", 1, can=False)
    assert port.writes == []


def test_a_port_that_cannot_stream_is_refused():
    with pytest.raises(ValueError, match="cannot monitor"):
        Transport(ScriptedPort({})).monitor("ATMA", 1, can=False)


def test_now_counts_from_the_transport_opening():
    clk = FakeClock()
    clk.t = 5.0
    t = Transport(StreamPort(), clock=clk.now)
    clk.t = 7.5
    assert t.now == pytest.approx(2.5)
    assert MonitorEvent("idle", 1.0).text == ""


def test_a_refused_atcaf0_still_ends_with_atcaf1():
    port, _, _ = run(["0C9 01\r"], replies={"ATCAF0": "?"})
    assert port.writes[-1] == "ATCAF1"


def test_a_failed_atcaf1_is_sent_twice_and_raw_mode_stays_refusing():
    port, t, _ = run(["0C9 01\r"], replies={"ATCAF1": "?"})
    assert port.writes[-2:] == ["ATCAF1", "ATCAF1"]
    with pytest.raises(ForbiddenCommand, match="raw CAN mode"):
        t.send("0104")
