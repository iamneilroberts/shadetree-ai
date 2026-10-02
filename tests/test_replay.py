from pathlib import Path

from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.transport import Transport

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_sedan.jsonl"


def test_load_transcript_reads_jsonl():
    records = load_transcript(FIXTURE)
    assert records[0] == {"t": 0.0, "tx": "ATZ", "rx": ["ELM327 v1.5"]}
    assert len(records) == 29


def test_replies_come_from_the_transcript_through_the_transport():
    port = ReplayPort.from_file(FIXTURE)
    t = Transport(port)
    assert t.send("0100") == ["41 00 BE 3F A8 13"]
    assert port.written == ["0100"]
    assert port.unmatched == []


def test_unknown_command_gets_question_mark_and_is_reported():
    port = ReplayPort([])
    t = Transport(port)
    assert t.send("0100") == ["?"]
    assert port.unmatched == ["0100"]


def test_repeated_commands_are_served_in_fifo_order_then_run_out():
    port = ReplayPort([{"tx": "0105", "rx": ["41 05 5A"]}, {"tx": "0105", "rx": ["41 05 5B"]}])
    t = Transport(port)
    assert t.send("0105") == ["41 05 5A"]
    assert t.send("0105") == ["41 05 5B"]
    assert t.send("0105") == ["?"]
    assert port.unmatched == ["0105"]
