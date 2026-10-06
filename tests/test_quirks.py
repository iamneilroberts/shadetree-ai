import json
import time
from pathlib import Path

import pytest

from obd_reader.__main__ import main
from obd_reader.hub import DEFAULT_PIDS, LiveHub
from obd_reader.probe import propose_quirks
from obd_reader.quirks import REPO_QUIRKS, QuirkStore, Quirks
from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.session import Config, Session
from obd_reader.simulator import SIM_VIN, SimPort
from obd_reader.transport import Transport
from obd_reader.vehicle import vehicle_key
from obd_reader.vin import find_vins

from conftest import ScriptedPort

FIX = Path(__file__).parent / "fixtures"
KEY = "1HGCM826-3"  # the synthetic sedan's vehicle key


def put(folder: Path, name: str, body) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")


def store(tmp_path):
    return QuirkStore(tmp_path / "home", committed=tmp_path / "committed")


def sedan_records():
    """The synthetic sedan, with its one advertised undecoded PID (2B) answering NO DATA."""
    return [dict(r, rx=["NO DATA"]) if r["tx"] == "012B" else r for r in load_transcript(FIX / "synthetic_sedan.jsonl")]


@pytest.mark.parametrize("bad", ["{not json", json.dumps({"key": KEY, "bogus": 1}), json.dumps({"key": "1HG"}),
                                 json.dumps({"key": KEY, "max_hz": 99}), json.dumps({"key": KEY, "protocol": "0"}),
                                 json.dumps({"key": KEY, "notes": [{"text": "x", "source": "y"}]}), json.dumps([])])
def test_a_valid_file_loads_and_a_malformed_one_is_no_quirks(tmp_path, bad):
    st = store(tmp_path)
    put(tmp_path / "committed", KEY, {"key": KEY, "max_hz": 2.5, "pids_lie": ["13"]})
    q, path = st.load(KEY)
    assert q.max_hz == 2.5 and q.pids_lie == ["13"] and path.name == f"{KEY}.json"
    put(tmp_path / "committed", KEY, bad)
    assert st.load(KEY) is None
    assert st.load(None) is None and st.load("not a key") is None


def test_the_vehicle_key_file_wins_and_the_wmi_file_is_the_fallback(tmp_path):
    st = store(tmp_path)
    put(tmp_path / "committed", "1HG", {"key": "1HG", "max_hz": 1.0})
    assert st.load(KEY)[0].key == "1HG"
    put(tmp_path / "committed", KEY, {"key": KEY, "max_hz": 3.0})
    assert st.load(KEY)[0].max_hz == 3.0
    assert st.load("2HGCM826-3") is None  # another WMI: nothing


def test_the_local_folder_takes_precedence_over_the_committed_one(tmp_path):
    st = store(tmp_path)
    put(tmp_path / "committed", KEY, {"key": KEY, "max_hz": 3.0})
    put(tmp_path / "home" / "quirks-local", KEY, {"key": KEY, "max_hz": 1.5})
    q, path = st.load(KEY)
    assert q.max_hz == 1.5 and path.parent.name == "quirks-local"


def test_the_probe_proposes_entries_from_reply_classes_and_latency():
    snap = scan(Transport(ReplayPort(sedan_records())), snapshot_id="p", protocol="6")
    for r in snap.replies:
        r.ms = 50.0  # replay latency is near 0; a 50 ms link
    prop = propose_quirks(snap)
    assert prop["key"] == KEY and prop["pids_lie"] == ["2B"] and prop["protocol"] == "6" and prop["ecus"] == {"7E8": "unknown"}
    assert prop["max_hz"] == 1.6  # 1000 / (50 ms x 12 requests a sweep), rounded down
    assert prop["notes"] and all(n["verified"] is False and n["confidence"] == "low" for n in prop["notes"])
    Quirks.model_validate(prop)
    assert find_vins(json.dumps(prop)) == [] and snap.vehicle.vin not in json.dumps(prop)


def test_nothing_is_written_until_a_person_accepts_and_accept_writes_only_quirks_local(tmp_path, capsys):
    tr = tmp_path / "t.jsonl"
    tr.write_text("".join(json.dumps(r) + "\n" for r in sedan_records()))
    committed_before = sorted(REPO_QUIRKS.iterdir())
    assert main(["probe", "--replay", str(tr), "--protocol", "6", "--out-dir", str(tmp_path), "--propose-quirks"]) == 0
    out = capsys.readouterr().out
    assert '"pids_lie": [\n    "2B"\n  ]' in out and "quirks applied: none" in out
    assert not (tmp_path / "quirks-local").exists() and sorted(REPO_QUIRKS.iterdir()) == committed_before
    (j,) = (tmp_path / "probes").glob("*.json")
    assert main(["quirks", "accept", str(j), "--out-dir", str(tmp_path)]) == 0
    assert QuirkStore(tmp_path).load(KEY)[1] == tmp_path / "quirks-local" / f"{KEY}.json"
    assert main(["quirks", "accept", str(j), "--out-dir", str(tmp_path)]) == 1  # never overwrites
    assert main(["probe", "--replay", str(tr), "--protocol", "6", "--out-dir", str(tmp_path), "--label", "again"]) == 0
    (j2,) = (tmp_path / "probes").glob("*-again.json")
    assert json.loads(j2.read_text())["quirks_applied"]["file"] == f"quirks-local/{KEY}.json"


def test_session_connection_uses_the_quirks_protocol_only_instead_of_automatic_search(tmp_path):
    hint = Quirks(key="ZZZ", protocol="6")
    for configured, sent in (("0", "ATSP6"), ("2", "ATSP2")):
        port = ScriptedPort({})
        with Session(Config(port="x", protocol=configured, home=tmp_path), port_factory=lambda: port).connection("t", quirks=hint):
            pass
        assert [w for w in port.writes if w.startswith("ATSP")] == [sent]


def test_the_console_state_shows_the_quirks_applied(tmp_path):
    key = vehicle_key(SIM_VIN)
    put(tmp_path / "quirks-local", key, {"key": key, "max_hz": 2.0, "pids_lie": ["0B"]})
    sim = SimPort("rich")
    hub = LiveHub(Session(Config(port="sim", home=tmp_path, timeout=0.5), port_factory=lambda: sim), sim=sim)
    assert hub.state()["quirks"] is None
    hub.start(DEFAULT_PIDS, hz=10, seconds=30)
    end = time.monotonic() + 8
    while time.monotonic() < end and hub.state()["seq"] < 4:
        time.sleep(0.05)
    st = hub.state()
    hub.stop()
    assert st["quirks"]["file"] == f"quirks-local/{key}.json" and st["quirks"]["hz_capped"] is True and st["hz"] == 2.0
    assert st["seq"] >= 4 and "0B" not in st["unsupported"]  # a hint, not a decision: 0B answers, so it stays


def test_committed_quirks_carry_no_vin_and_the_example_is_marked():
    files = [p for p in REPO_QUIRKS.rglob("*") if p.is_file()]
    assert files, "quirks/ should hold at least the example"
    for p in files:
        assert find_vins(p.read_text(encoding="utf-8")) == [], f"VIN-looking token in {p.name}"  # no allowlist here
    ex = Quirks.model_validate_json((REPO_QUIRKS / "example.json").read_text(encoding="utf-8"))
    assert ex.example and all(n.confidence == "unverified" and not n.verified for n in ex.notes)
