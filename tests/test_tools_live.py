import inspect
from pathlib import Path

import pytest

from obd_reader.allowlist import check_command
from obd_reader.live import LiveLimitError
from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.session import AdapterBusy, Config, NoAdapterError, Session
from obd_reader.tools import LIVE_TOOLS, OFFLINE_TOOLS, TOOL_NAMES, build_tools

from conftest import FakeClock, ScriptedPort

FIX = Path(__file__).parent / "fixtures"
FORBIDDEN_PARAMS = {"cmd", "command", "raw", "hex", "at", "payload", "data"}


def live_session(tmp_path, factory, clk=None):
    clk = clk or FakeClock()
    return Session(Config(port="fake", home=tmp_path, timeout=0.2), port_factory=factory,
                   clock=clk.now, sleep=clk.sleep)


def test_tool_names_are_exactly_the_reviewed_set(tmp_path):
    tools = build_tools(live_session(tmp_path, lambda: ScriptedPort({})))
    assert set(tools) == set(TOOL_NAMES) == set(OFFLINE_TOOLS | LIVE_TOOLS)
    assert len(TOOL_NAMES) == 15


def test_no_tool_accepts_a_command_string(tmp_path):
    tools = build_tools(live_session(tmp_path, lambda: ScriptedPort({})))
    for name, fn in tools.items():
        assert FORBIDDEN_PARAMS.isdisjoint(inspect.signature(fn).parameters), name


def test_read_pid_decodes_and_records(tmp_path):
    s = live_session(tmp_path, lambda: ScriptedPort({"0C": "1AF8"}))
    out = build_tools(s)["read_pid"]("0c")
    assert out["pid"] == "0C" and out["name"] == "engine_rpm" and out["value"] == 1726.0
    assert list((tmp_path / "transcripts").glob("*-read-pid.jsonl"))


def test_read_pid_without_data_says_so(tmp_path):
    s = live_session(tmp_path, lambda: ScriptedPort({}))
    out = build_tools(s)["read_pid"]("0C")
    assert out["value"] is None and "no data" in out["note"].lower()


@pytest.mark.parametrize("bad", ["0C\r04", "ZZ", "", "0C0", "0c\n", "FF"])
def test_read_pid_refuses_smuggled_commands(tmp_path, bad):  # Review Focus 1
    ports = []
    s = live_session(tmp_path, lambda: ports.append(ScriptedPort({})) or ports[-1])
    with pytest.raises(LiveLimitError):
        build_tools(s)["read_pid"](bad)
    assert ports == []  # validation happens before any port is opened


def test_live_data_returns_stats_and_at_most_120_points(tmp_path):  # Review Focus 5
    s = live_session(tmp_path, lambda: ScriptedPort({"0C": "1AF8", "05": "7B"}))
    out = build_tools(s)["live_data"](["0C", "05"], seconds=120, hz=10)
    rpm = out["series"]["0C"]
    assert len(rpm["samples"]) <= 120 and 1199 <= rpm["stats"]["n"] <= 1202  # 120 s x 10 Hz, float ticks
    assert rpm["stats"]["min"] == rpm["stats"]["max"] == 1726.0
    assert out["duration_s"] == 120 and out["hz"] == 10


def test_live_data_limits(tmp_path):
    tools = build_tools(live_session(tmp_path, lambda: ScriptedPort({})))
    with pytest.raises(LiveLimitError):
        tools["live_data"](["0C"], seconds=500)
    with pytest.raises(LiveLimitError):
        tools["live_data"]([f"{i:02X}" for i in range(9)])


def test_trim_summary_covers_supported_trims_only(tmp_path):
    s = live_session(tmp_path, lambda: ScriptedPort({"06": "80", "07": "6B"}))
    out = build_tools(s)["trim_summary"](seconds=2, hz=1)
    assert out["series"]["07"]["stats"]["mean"] == pytest.approx(-16.4, abs=0.1)
    assert out["series"]["08"]["stats"] == {"n": 0} and "no data" in out["notes"]["08"].lower()


def test_adapter_info_reports_identity_and_voltage(tmp_path):
    recs = [{"tx": "ATZ", "rx": ["ELM327 v1.4b"]}, {"tx": "ATE0", "rx": ["OK"]}, {"tx": "ATL0", "rx": ["OK"]},
            {"tx": "ATH0", "rx": ["OK"]}, {"tx": "ATSP0", "rx": ["OK"]},
            {"tx": "ATI", "rx": ["ELM327 v1.4b"]}, {"tx": "STI", "rx": ["STN2232 v5.12.4"]},
            {"tx": "STDI", "rx": ["OBDLink EX r2.7.1"]}, {"tx": "ATRV", "rx": ["12.6V"]}]
    s = live_session(tmp_path, lambda: ReplayPort(recs))
    out = build_tools(s)["adapter_info"]()
    assert out["chip"] == "STN2232" and out["genuine_stn"] is True
    assert out["device"] == "OBDLink EX r2.7.1" and out["supply_voltage"] == "12.6V"


def test_scan_saves_a_snapshot_the_offline_tools_can_read(tmp_path):
    recs = load_transcript(FIX / "synthetic_sedan.jsonl")
    s = live_session(tmp_path, lambda: ReplayPort(recs))
    tools = build_tools(s)
    out = tools["scan"]("bench", "6", "rough idle")
    assert out["vin"] == "1HGCM82633A004352" and out["stored_dtcs"] == ["P0171"]
    assert tools["read_dtcs"](out["snapshot_id"])["dtcs"][0]["code"] == "P0171"
    assert tools["get_snapshot"](out["snapshot_id"])["user_context"]["symptoms"] == "rough idle"


def test_scan_rejects_bad_labels_and_protocols_before_traffic(tmp_path):  # Review Focus 1
    ports = []
    s = live_session(tmp_path, lambda: ports.append(ReplayPort([])) or ports[-1])
    for label, proto in (("../x", "0"), ("ok", "0\r04"), ("ok", "Z")):
        with pytest.raises(ValueError):
            build_tools(s)["scan"](label, proto)
    assert all(p.written == [] for p in ports)


def test_mode06_lists_supported_tests_then_reads_them(tmp_path):
    recs = [{"tx": c, "rx": ["OK"]} for c in ("ATZ", "ATE0", "ATL0", "ATH0", "ATSP0")]
    recs += [{"tx": "0600", "rx": ["46 00 80 00 00 00"]},
             {"tx": "0601", "rx": ["46 01 8B 0A 12 34 00 00 FF FF"]}]
    s = live_session(tmp_path, lambda: ReplayPort(recs))
    out = build_tools(s)["mode06_tests"]()
    assert out["supported_mids"] == ["01"]
    assert out["results"][0]["tid"] == "8B" and out["results"][0]["within_limits"] is True
    assert "unverified" in out["note"].lower()


def test_mode06_rejects_a_bad_mid(tmp_path):  # Review Focus 1
    tools = build_tools(live_session(tmp_path, lambda: ScriptedPort({})))
    for bad in ("0", "ZZ", "01\r04", "001", "0G", ""):
        with pytest.raises(ValueError):
            tools["mode06_tests"](bad)


def test_live_tools_fail_clearly_without_an_adapter(tmp_path):  # Review Focus 4
    s = Session(Config(port=None, home=tmp_path))
    for name, args in (("adapter_info", ()), ("read_pid", ("0C",)), ("scan", ("x",)), ("mode06_tests", ())):
        with pytest.raises(NoAdapterError):
            build_tools(s)[name](*args)


def test_silent_adapter_gives_a_structured_answer_not_a_hang(tmp_path):  # Review Focus 4
    class Silent(ScriptedPort):
        def write(self, data):
            self.writes.append(data.decode().rstrip("\r"))
            self._pending = ""

    s = live_session(tmp_path, lambda: Silent({}))
    out = build_tools(s)["read_pid"]("0C")
    assert out["value"] is None


def test_concurrent_live_calls_fail_fast(tmp_path):  # Review Focus 3
    s = live_session(tmp_path, lambda: ScriptedPort({"0C": "1AF8"}))
    tools = build_tools(s)
    with s.connection("holder"):
        with pytest.raises(AdapterBusy):
            tools["read_pid"]("0C")


def test_every_live_command_stays_inside_the_allowlist(tmp_path):
    ports = []
    s = live_session(tmp_path, lambda: ports.append(ScriptedPort({"0C": "1AF8", "05": "7B"})) or ports[-1])
    tools = build_tools(s)
    tools["read_pid"]("0C")
    tools["live_data"](["0C", "05"], seconds=1, hz=2)
    tools["trim_summary"](seconds=1, hz=1)
    tools["mode06_tests"]("01")
    for p in ports:
        for c in p.writes:
            assert check_command(c) == c
