"""Live channels read from one consistent ECU: headers on (ATH1) while sampling Mode 01, the engine ECU's reply when it
answers the PID, else the lowest other responder, kept for the run. All data here is synthetic."""
import json
import time
from collections import defaultdict

from obd_reader.hub import LiveHub
from obd_reader.live import EcuChoice, read_pid_value
from obd_reader.pids import PIDS
from obd_reader.replay import ReplayPort
from obd_reader.replay_run import load_run
from obd_reader.session import Config, Session
from obd_reader.transport import Transport


def wait_for(cond, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def dec(pid: str, hexdata: str):
    return PIDS[pid].decode(bytes.fromhex(hexdata))


class MultiEcuPort:
    """A car with several ECUs on CAN 11/500. Every Mode 01 request is answered by each ECU that has the PID, in an
    order that rotates from request to request (as the Highlander's replies did). Honours ATH1 like a real adapter."""

    def __init__(self, ecus: dict[str, dict[str, str]]):  # address -> {pid: data hex}
        self.ecus, self.headers, self.n, self._pending = ecus, False, defaultdict(int), ""

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r")
        if cmd in ("ATZ", "ATH0", "ATH1"):
            self.headers = cmd == "ATH1"
        if cmd.startswith("01") and len(cmd) == 4:
            pid, msgs = cmd[2:], []
            for addr, pids in self.ecus.items():
                if int(pid, 16) % 0x20 == 0:  # a support bitmap: only page 00 is used here
                    bits = sum(0x80000000 >> (int(p, 16) - 1) for p in pids) if pid == "00" else 0
                    if bits:
                        msgs.append((addr, f"41 00 {bits:08X}"))
                elif pid in pids:
                    msgs.append((addr, f"41 {pid} {pids[pid]}"))
            self.n[pid] += 1
            k = self.n[pid] % len(msgs) if msgs else 0
            msgs = msgs[k:] + msgs[:k]
            lines = []
            for addr, m in msgs:
                b = bytes.fromhex(m.replace(" ", ""))
                body = " ".join(f"{x:02X}" for x in b)
                lines.append(f"{addr} {len(b):02X} {body}" if self.headers else body)
            self._pending = "\r".join(lines) + "\r" if lines else "NO DATA\r"
        elif cmd == "ATDP":
            self._pending = "AUTO, ISO 15765-4 (CAN 11/500)\r"
        else:
            self._pending = "OK\r"

    def read_until_prompt(self, timeout: float) -> str:
        out, self._pending = self._pending, ""
        return out

    def close(self) -> None:
        pass


def run_hub(tmp_path, port_factory, pids, seconds=30.0, n=6):
    s = Session(Config(port="x", home=tmp_path, timeout=0.5), port_factory=port_factory)
    hub = LiveHub(s)
    hub.start(pids, hz=10, seconds=seconds)
    assert wait_for(lambda: hub.state()["seq"] >= n or hub.state()["status"] != "running")
    hub.stop()
    return hub


def values(st, pid):
    return [v for _, _, v in st["channels"][pid]["samples"]]


# The engine ECU answers 04 with 12; two modules answer it too, with 13 and 5D (7.1, 7.5 and 36.5 %).
THREE = {"7E8": {"0C": "0B 98", "04": "12"}, "7E9": {"0C": "0B 98", "04": "13"}, "7EA": {"04": "5D"}}


def test_three_ecus_in_shuffled_order_the_channel_always_takes_the_engine_value(tmp_path):
    hub = run_hub(tmp_path, lambda: MultiEcuPort(THREE), ["0C", "04"])
    st = hub.state()
    assert len(values(st, "04")) >= 6 and set(values(st, "04")) == {dec("04", "12")}
    assert st["channels"]["04"]["ecu"] == "7E8"


def test_a_pid_only_modules_answer_is_read_from_the_lowest_one_every_sweep(tmp_path):
    ecus = {"7E8": {"0C": "0B 98"}, "7EA": {"05": "7D"}, "7E9": {"05": "6C"}}  # no 05 from the engine ECU
    hub = run_hub(tmp_path, lambda: MultiEcuPort(ecus), ["0C", "05"])
    st = hub.state()
    assert len(values(st, "05")) >= 6 and set(values(st, "05")) == {dec("05", "6C")}
    assert st["channels"]["05"]["ecu"] == "7E9" and st["channels"]["0C"]["ecu"] == "7E8"


def test_state_and_the_saved_run_name_the_ecu_of_each_channel(tmp_path):
    hub = run_hub(tmp_path, lambda: MultiEcuPort(THREE), ["0C", "04"])
    st = hub.state()
    assert st["ecus"] == [{"addr": "7E8", "role": "engine"}, {"addr": "7E9", "role": "module"},
                          {"addr": "7EA", "role": "module"}]
    saved = json.loads(next((tmp_path / "runs").glob("*.json")).read_text())
    assert saved["channel_ecus"] == {"0C": "7E8", "04": "7E8"} and saved["ecus"] == st["ecus"]
    run = load_run(saved)
    hub.start_replay(run, "x", playing=False)
    assert hub.state()["channels"]["04"]["ecu"] == "7E8" and hub.state()["ecus"] == st["ecus"]
    hub.exit_replay()


def _read_all(records, pid):
    t, choice = Transport(ReplayPort(records)), EcuChoice()
    return [read_pid_value(t, pid, choice) for _ in records], choice


def test_29_bit_headers_engine_id_wins_and_padding_is_ignored():
    records = [{"tx": "010C", "rx": ["18 DA F1 18 04 41 0C 00 00 AA AA AA", "18 DA F1 10 04 41 0C 0B 98 AA AA AA"]},
               {"tx": "010C", "rx": ["18 DA F1 10 04 41 0C 0B 9C AA AA AA", "18 DA F1 18 04 41 0C 00 00 AA AA AA"]}]
    got, choice = _read_all(records, "0C")
    assert got == [742.0, 743.0]
    assert choice.by_pid == {"0C": "18DAF110"} and choice.seen == ["18DAF110", "18DAF118"]


def test_11_bit_iso_tp_multi_frame_replies_are_joined_per_ecu():
    # PID 68 is 9 bytes: a first frame and a consecutive frame from each of two ECUs, interleaved
    rx = ["7E9 10 09 41 68 01 50 00 00", "7E8 10 09 41 68 01 46 00 00",
          "7E9 21 00 00 00 AA AA AA AA", "7E8 21 00 00 00 AA AA AA AA"]
    got, choice = _read_all([{"tx": "0168", "rx": rx}], "68")
    assert got == [30] and choice.by_pid == {"68": "7E8"}


def test_legacy_headers_on_reply_reads_the_engine_source_address():
    # J1850 PWM: the priority byte 41 equals the Mode 01 response SID, so the header must be read as a header
    records = [{"tx": "010C", "rx": ["41 6B 18 41 0C 00 00 5E", "41 6B 10 41 0C 0B 98 C4"]},
               {"tx": "010C", "rx": ["41 6B 10 41 0C 0B 9C 2A", "41 6B 18 41 0C 00 00 5E"]}]
    got, choice = _read_all(records, "0C")
    assert got == [742.0, 743.0] and choice.by_pid == {"0C": "10"}


INIT = [{"tx": c, "rx": ["OK"]} for c in ("ATZ", "ATE0", "ATL0", "ATH0", "ATSP0")] + [
    {"tx": "ATI", "rx": ["ELM327 v1.4b"]}, {"tx": "STI", "rx": ["?"]}, {"tx": "ATDP", "rx": ["AUTO, ISO 15765-4 (CAN 11/500)"]},
    {"tx": "0100", "rx": ["41 00 10 10 00 00", "41 00 10 10 00 00", "41 00 10 00 00 00"]}]


def test_an_old_headers_off_transcript_replays_as_before_first_responder(tmp_path):
    shuffled = [["41 04 12", "41 04 13", "41 04 5D"], ["41 04 5D", "41 04 12", "41 04 13"],
                ["41 04 13", "41 04 5D", "41 04 12"]] * 2
    records = list(INIT)
    for rx in shuffled:
        records += [{"tx": "010C", "rx": ["41 0C 0B 98", "41 0C 0B 98"]}, {"tx": "0104", "rx": rx}]
    port = ReplayPort(records)
    hub = run_hub(tmp_path, lambda: port, ["0C", "04"])
    assert wait_for(lambda: hub.state()["status"] != "running")
    st = hub.state()
    assert "ATH1" in port.unmatched  # an old transcript has no ATH1: it answers "?" and headers stay off
    assert values(st, "04") == [dec("04", rx[0][6:]) for rx in shuffled]
    assert st["channels"]["04"]["ecu"] is None and st["ecus"] == []


def test_a_new_headers_on_transcript_replays_the_same_values_and_ecus(tmp_path):
    live = run_hub(tmp_path / "live", lambda: MultiEcuPort(THREE), ["0C", "04"], seconds=0.8, n=10**6)
    transcript = next((tmp_path / "live" / "transcripts").glob("*.jsonl"))
    port = ReplayPort.from_file(transcript)
    again = run_hub(tmp_path / "replay", lambda: port, ["0C", "04"], n=10**6)
    a, b = live.state(), again.state()
    assert values(a, "04") and values(b, "04") == values(a, "04") and values(b, "0C") == values(a, "0C")
    assert "ATH1" not in port.unmatched and b["channels"]["04"]["ecu"] == "7E8" and b["ecus"] == a["ecus"]


def test_the_simulator_honours_ath1_with_the_same_values():
    from obd_reader.simulator import SimPort
    on, off = SimPort("lean", clock=lambda: 0.0), SimPort("lean", clock=lambda: 0.0)
    t_on, t_off, choice = Transport(on), Transport(off), EcuChoice()
    assert t_on.send("ATH1") == ["OK"]
    pids = ["0C", "05", "06", "68", "42"]
    assert [read_pid_value(t_on, p, choice) for p in pids] == [read_pid_value(t_off, p) for p in pids]
    assert choice.by_pid == {"0C": "18DAF110", "05": "18DAF118", "06": "18DAF110", "68": "18DAF110", "42": "18DAF110"}
