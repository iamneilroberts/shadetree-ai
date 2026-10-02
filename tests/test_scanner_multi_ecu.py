"""Multi-ECU behavior, driven by a real 2024 Ridgeline capture (VIN serial redacted)."""
from datetime import datetime, timezone
from pathlib import Path

from obd_reader.replay import ReplayPort, load_transcript
from obd_reader.scanner import scan
from obd_reader.transport import Transport

REAL = Path(__file__).parent / "fixtures" / "ridgeline_2024_can29.jsonl"
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
VIN_A = ["014", "0: 49 02 01 31 48 47", "1: 43 4D 38 32 36 33 33", "2: 41 30 30 34 33 35 32"]


def run(records):
    port = ReplayPort(records)
    return scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol="0"), port


def patch(records, tx, rx):
    return [dict(r, rx=rx) if r["tx"] == tx else r for r in records]


def test_real_ridgeline_capture_decodes_as_can29_with_synthetic_vin():
    snap, _ = run(load_transcript(REAL))
    assert snap.protocol.name == "ISO 15765-4 (CAN 29/500)" and snap.protocol.pinned is False
    assert snap.vehicle.vin == "5FPYK3F51RB000001" and snap.vehicle.vin_source == "obd"
    assert snap.dtcs.stored == snap.dtcs.pending == snap.dtcs.permanent == []
    assert snap.mil.on is False and snap.mil.dtc_count == 0


def test_supported_pids_are_the_union_of_every_responding_ecu():
    # PID 03 is supported only by the first ECU, PID 05 (coolant temp) only by the second.
    snap, _ = run(load_transcript(REAL))
    pids = snap.supported_pids["01"]
    assert "03" in pids and "05" in pids
    assert pids == sorted(set(pids))  # no duplicates, stable order
    assert {"20", "40", "60", "80", "A0"} <= set(pids)  # every page was walked
    assert "09" in snap.supported_pids and "02" in snap.supported_pids["09"]


def test_dtcs_are_the_union_across_ecus_without_duplicates():
    records = patch(load_transcript(REAL), "03", ["43 02 01 71 C1 00", "43 02 01 71 03 00"])
    snap, _ = run(records)
    assert [d.code for d in snap.dtcs.stored] == ["P0171", "U0100", "P0300"]


def test_mil_is_on_if_any_ecu_says_so_and_counts_add_up():
    records = patch(load_transcript(REAL), "0101", ["41 01 00 07 E5 00", "41 01 82 04 00 00"])
    snap, _ = run(records)
    assert snap.mil.on is True and snap.mil.dtc_count == 2


DISCOVERY_OK = [
    {"tx": "ATH1", "rx": ["OK"]},
    {"tx": "0100", "rx": ["18 DA F1 10 06 41 00 B7 BC A8 93", "18 DA F1 18 06 41 00 98 18 80 03"]},
    {"tx": "ATH0", "rx": ["OK"]},
]


def test_ecus_are_attributed_from_a_headers_on_pass():
    snap, port = run(load_transcript(REAL) + DISCOVERY_OK)
    assert [e.header for e in snap.ecus] == ["18DAF110", "18DAF118"]
    assert all(e.modes_seen == ["01"] for e in snap.ecus)
    assert not any("attribution" in w for w in snap.warnings)
    assert port.written.count("ATH1") == 1 and port.written.count("ATH0") == 2  # init + restore


def test_headers_are_switched_back_off_even_when_discovery_gets_garbage():
    records = load_transcript(REAL) + [{"tx": "ATH1", "rx": ["OK"]}, {"tx": "0100", "rx": ["?"]},
                                       {"tx": "ATH0", "rx": ["OK"]}]
    snap, port = run(records)
    assert snap.ecus == []
    assert any("ECU attribution unavailable" in w for w in snap.warnings)
    assert port.written.count("ATH0") == 2
    # ATH0 came after the discovery request, so later decoding still sees headers off
    assert port.written.index("ATH1") < len(port.written) - 1 - port.written[::-1].index("ATH0")


def test_capture_without_a_headers_pass_warns_that_ecus_are_unattributed():
    snap, _ = run(load_transcript(REAL))
    assert snap.ecus == []
    assert any("ECU attribution unavailable" in w for w in snap.warnings)


def test_non_can_protocol_never_sends_the_headers_pass():
    records = patch(load_transcript(REAL), "ATDP", ["SAE J1850 PWM"])
    snap, port = run(records)
    assert "ATH1" not in port.written


def _frames(payload: bytes) -> list[str]:
    hx = lambda c: " ".join(f"{x:02X}" for x in c)  # noqa: E731
    if len(payload) <= 7:
        return [hx(payload)]
    rest = [payload[i:i + 7] for i in range(6, len(payload), 7)]
    return [f"{len(payload):03X}", "0: " + hx(payload[:6])] + [f"{n + 1:X}: " + hx(c) for n, c in enumerate(rest)]


def test_mode_09_identity_is_read_because_the_real_bitmap_advertises_it():
    # The real capture's 0900 bitmaps advertise 04, 06 and 0A on both ECUs; it predates these reads, so the replies are synthetic.
    cal = lambda *ids: bytes([0x49, 0x04, len(ids)]) + b"".join(i.ljust(16, b"\0") for i in ids)  # noqa: E731
    extra = [
        {"tx": "STDI", "rx": ["OBDLink EX r1.0"]}, {"tx": "ATRV", "rx": ["12.4V"]},
        {"tx": "0904", "rx": _frames(cal(b"SYNENG01", b"SYNENG02")) + _frames(cal(b"SYNTRN01"))},
        {"tx": "0906", "rx": ["49 06 01 00 00 12 34", "49 06 01 00 00 AB CD"]},
        {"tx": "090A", "rx": _frames(bytes([0x49, 0x0A, 0x01]) + b"TCM\0-TransmissionCtl".ljust(20, b"\0"))},
    ]
    snap, port = run(load_transcript(REAL) + extra)
    assert {"0904", "0906", "090A", "STDI", "ATRV"} <= set(port.written)
    assert snap.mode09.cal_ids == ["SYNENG01", "SYNENG02", "SYNTRN01"]
    assert snap.mode09.cvns == ["00001234", "0000ABCD"]
    assert snap.mode09.ecu_names == ["TCM-TransmissionCtl"]
    assert snap.source.adapter.device == "OBDLink EX r1.0" and snap.source.adapter.supply_voltage == "12.4V"


def test_disagreeing_vins_warn_and_use_the_first_valid_one():
    records = patch(load_transcript(REAL), "0902", VIN_A + ["014", "0: 49 02 01 35 46 50",
                    "1: 59 4B 33 46 35 31 52", "2: 42 30 30 30 30 30 31"])
    snap, _ = run(records)
    assert snap.vehicle.vin == "1HGCM82633A004352"
    assert any("disagree" in w.lower() for w in snap.warnings)
