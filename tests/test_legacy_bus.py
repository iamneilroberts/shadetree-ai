"""Pre-CAN buses (J1850 VPW/PWM, ISO 9141, KWP): DTC, VIN and ECU-header layouts.

The transcript shape follows a real J1850 VPW scan (bitmaps, 0101, 0113, 011E as captured); the codes, VIN and
headers-on line are synthetic (the VIN is the allowlisted synthetic sedan VIN)."""
from datetime import datetime, timezone

from obd_reader.elm import decode_dtc_list, is_legacy, parse_headers_legacy, parse_vin_legacy
from obd_reader.pids import decode_pid
from obd_reader.replay import ReplayPort
from obd_reader.scanner import scan
from obd_reader.transport import Transport

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
VIN = "1HGCM82633A004352"


def vin_lines(vin: str) -> list[str]:
    data = b"\x00\x00\x00" + vin.encode()
    return [f"49 02 {n + 1:02X} " + " ".join(f"{b:02X}" for b in data[n * 4:n * 4 + 4]) for n in range(5)]


def vpw_records(**over) -> list[dict]:
    rec = {
        "ATZ": ["ELM327 v1.4b"], "ATE0": ["OK"], "ATL0": ["OK"], "ATH0": ["OK"], "ATSP2": ["OK"],
        "ATI": ["ELM327 v1.4b"], "STI": ["STN2232 v5.12.4"], "ATRV": ["13.9V"], "STDI": ["OBDLink EX r2.7.1"],
        "0100": ["41 00 BF BF B9 94"], "ATDP": ["SAE J1850 VPW"], "ATH1": ["OK"],
        "0100#h": ["48 6B 10 41 00 BF BF B9 94 C6", "48 6B 18 41 00 80 00 00 00 1A"],
        "0900": ["49 00 01 54 00 00 00"], "0902": vin_lines(VIN),
        "03": ["43 01 33 03 00 00 00"], "07": ["47 00 00 00 00 00 00"],
        "0101": ["41 01 81 07 65 00"], "0113": ["41 13 33"], "011E": ["41 1E 12"], "020200": ["42 02 00 01 33"],
        "020000": ["42 00 00 00 00 00 00"],
    } | over
    order = ["ATZ", "ATE0", "ATL0", "ATH0", "ATSP2", "ATI", "STI", "ATRV", "STDI", "0100", "ATDP", "ATH1",
             "0100#h", "ATH0", "0900", "0902", "03", "07", "0101", "0113", "011E", "020200", "020000"]
    return [{"tx": k.split("#")[0], "rx": rec[k]} for k in order if rec.get(k) is not None]


def run(records):
    port = ReplayPort(records)
    return scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol="2"), port


def test_is_legacy_names_the_pre_can_buses_only():
    for name in ("SAE J1850 VPW", "SAE J1850 PWM", "ISO 9141-2", "ISO 14230-4 (KWP FAST)", "AUTO, SAE J1850 VPW"):
        assert is_legacy(name)
    for name in ("ISO 15765-4 (CAN 11/500)", "AUTO", "", None):
        assert not is_legacy(name)


def test_legacy_dtc_layout_has_no_count_byte():
    # The CAN decoder would read 01 as a count and give P3303 for this reply.
    assert decode_dtc_list(bytes.fromhex("430133030000 00".replace(" ", "")), legacy=True) == ["P0133", "P0300"]
    assert decode_dtc_list(bytes.fromhex("47000000000000"), legacy=True) == []


def test_legacy_vin_is_rebuilt_from_five_numbered_lines():
    assert parse_vin_legacy(vin_lines(VIN)) == [VIN]
    two = vin_lines(VIN) + vin_lines(VIN)
    assert parse_vin_legacy(two) == [VIN, VIN]
    assert parse_vin_legacy(vin_lines(VIN)[:4]) == []  # truncated: dropped, not repaired
    assert parse_vin_legacy(["NO DATA"]) == []


def test_legacy_headers_name_the_source_address():
    lines = ["48 6B 10 41 00 BF BF B9 94 C6", "48 6B 18 41 00 80 00 00 00 1A", "41 00 BF BF B9 94", "garbage"]
    assert parse_headers_legacy(lines) == ["10", "18"]


def test_pids_13_and_1e_decode():
    assert decode_pid("13", bytes([0x33])).value == 0x33
    assert decode_pid("1E", bytes([0x12])).value == 0  # bit 0 only: PTO not active


def test_vpw_scan_reads_codes_vin_and_ecus_with_the_legacy_layouts():
    snap, port = run(vpw_records())
    assert snap.protocol.name == "SAE J1850 VPW"
    assert snap.vehicle.vin == VIN and snap.vehicle.vin_source == "obd"
    assert [d.code for d in snap.dtcs.stored] == ["P0133", "P0300"]
    assert snap.dtcs.pending == [] and snap.dtcs.permanent == []
    assert snap.dtcs.unanswered == ["permanent"]  # never asked on a legacy bus: not a claim of "no codes"
    assert [e.header for e in snap.ecus] == ["10", "18"]
    assert "0A" not in port.written and "0904" not in port.written
    assert snap.freeze_frame is not None and snap.freeze_frame.dtc == "P0133"
    assert snap.undecoded == []  # 13 and 1E now decode
    assert port.unmatched == []
    assert not any("non-CAN" in w or "unknown protocol" in w for w in snap.warnings)


def test_vpw_codes_that_do_not_answer_are_unanswered_not_empty():
    snap, _ = run(vpw_records(**{"03": ["NO DATA"], "07": ["NO DATA"], "020200": None, "020000": None}))
    assert snap.dtcs.unanswered == ["stored", "pending", "permanent"]
    assert snap.freeze_frame is None


def test_vpw_mode03_no_data_is_no_stored_codes_only_when_0101_counts_zero():
    none, _ = run(vpw_records(**{"03": ["NO DATA"], "0101": ["41 01 00 07 65 00"], "020200": None, "020000": None}))
    assert none.dtcs.stored == [] and none.dtcs.unanswered == ["permanent"]
    some, _ = run(vpw_records(**{"03": ["NO DATA"], "020200": None, "020000": None}))  # 0101 counts one code
    assert some.dtcs.unanswered == ["stored", "permanent"]


def test_vpw_mode09_identity_items_are_not_decoded_but_said_so():
    snap, port = run(vpw_records(**{"0900": ["49 00 01 55 40 00 00"]}))  # advertises 02, 04, 06, 08, 0A
    assert snap.mode09.cal_ids == [] and "0904" not in port.written
    assert any("legacy-bus layout is not supported yet" in w for w in snap.warnings)


def test_auto_search_that_finds_nothing_falls_back_to_each_protocol_in_turn():
    # As captured on a real VPW truck: ATSP0 + 0100 gave UNABLE TO CONNECT; pinned to 2 it answered.
    fail = ["SEARCHING...", "UNABLE TO CONNECT"]
    records = [r for r in vpw_records() if r["tx"] not in ("ATSP2", "0100")]
    records += [{"tx": "ATSP0", "rx": ["OK"]}, {"tx": "0100", "rx": fail}]
    records += [{"tx": f"ATSP{p}", "rx": ["OK"]} for p in "6879"] + [{"tx": "0100", "rx": ["NO DATA"]}] * 4
    records += [{"tx": "ATSP2", "rx": ["OK"]}, {"tx": "0100", "rx": ["41 00 BF BF B9 94"]}]  # the fallback's ask
    records += [{"tx": "0100", "rx": ["41 00 BF BF B9 94"]}]  # the bitmap walk again, now on VPW
    records += [{"tx": "0100", "rx": ["48 6B 10 41 00 BF BF B9 94 C6"]}]  # headers-on pass
    port = ReplayPort(records)
    snap = scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol="0")
    assert snap.protocol.atsp == "2" and snap.protocol.pinned is False
    assert snap.supported_pids["01"][:3] == ["01", "03", "04"]
    assert [d.code for d in snap.dtcs.stored] == ["P0133", "P0300"]
    assert any("protocol 2 answered when tried directly" in w for w in snap.warnings)
    assert [c for c in port.written if c.startswith("ATSP")] == ["ATSP0", "ATSP6", "ATSP8", "ATSP7", "ATSP9", "ATSP2"]


def test_auto_search_with_no_bus_at_all_returns_to_automatic_search():
    fail = ["SEARCHING...", "UNABLE TO CONNECT"]
    records = [{"tx": t, "rx": ["OK"]} for t in ("ATZ", "ATE0", "ATL0", "ATH0", "ATSP0")] + [{"tx": "ATDP", "rx": ["AUTO"]}]
    records += [{"tx": "0100", "rx": fail}] * 10
    port = ReplayPort(records)
    snap = scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol="0")
    sp = [c for c in port.written if c.startswith("ATSP")]
    assert sp[-1] == "ATSP0" and len(sp) == 11  # initial, nine tries, back to automatic
    assert "01" not in snap.supported_pids and snap.protocol.atsp == "0"


def test_legacy_mode09_bitmap_skips_the_message_number():
    # As a real J1850 VPW truck answered: 01 is the message number, FC advertises 01-06 (VIN included).
    snap, port = run(vpw_records(**{"0900": ["49 00 01 FC 00 00 00"]}))
    assert snap.supported_pids["09"] == ["01", "02", "03", "04", "05", "06"]
    assert "0902" in port.written and snap.vehicle.vin == VIN


def test_vpw_probe_walks_the_mode06_bitmap_past_the_filler_byte():
    records = vpw_records() + [{"tx": "0600", "rx": ["46 00 FF 48 54 00 00"]}]
    port = ReplayPort(records)
    snap = scan(Transport(port), snapshot_id="t", captured_at=NOW, protocol="2", mode06=True)
    assert snap.supported_pids["06"] == ["02", "05", "0A", "0C", "0E"]
