from obd_reader.mode06 import Mode06Result, parse_results, supported_mids


def test_supported_mids_bitmap():
    assert supported_mids([bytes.fromhex("460080000001")], 0x00) == {"01", "20"}
    assert supported_mids([bytes.fromhex("462000000001")], 0x00) == set()  # wrong page for this base


def test_parse_two_result_groups():
    payload = bytes.fromhex("46" "01" "8B0A12340000FFFF" "01" "8C0A000500000003")
    res = parse_results(payload)
    assert res[0] == Mode06Result(mid="01", tid="8B", uasid="0A", value=0x1234, minimum=0, maximum=0xFFFF,
                                  within_limits=True)
    assert res[1].tid == "8C" and res[1].value == 5 and res[1].within_limits is False


def test_a_multi_test_reply_from_a_real_car_reads_every_group():
    # Mode 06 MID 02 from a 2024 Ridgeline: two tests, the MID repeats in each 9-byte group
    payload = bytes.fromhex("46" "029D0B002E00000128" "029E0B02B10032FFFF")
    res = parse_results(payload)
    assert [(r.mid, r.tid, r.uasid, r.value, r.minimum, r.maximum) for r in res] == [
        ("02", "9D", "0B", 0x2E, 0, 0x128), ("02", "9E", "0B", 0x2B1, 0x32, 0xFFFF)]
    assert [r.within_limits for r in res] == [True, True]


def test_min_greater_than_max_gives_unknown_limits():
    payload = bytes.fromhex("46" "02" "010A000500090003")
    assert parse_results(payload)[0].within_limits is None


def test_incomplete_trailing_group_is_dropped_not_raised():
    payload = bytes.fromhex("46" "01" "8B0A12340000FFFF" "01" "8C0A00")
    assert [r.tid for r in parse_results(payload)] == ["8B"]


def test_not_a_mode06_payload_returns_nothing():
    assert parse_results(b"") == [] and parse_results(b"\x41\x01\x00") == [] and parse_results(b"\x46") == []


# ---- legacy bus (J1850, ISO 9141, KWP): replies as a J1850 VPW GMC truck answered (2026-10-04) ----
from obd_reader.mode06 import LegacyTestResult, parse_legacy, read_all_legacy, walk_ids  # noqa: E402
from obd_reader.replay import ReplayPort  # noqa: E402
from obd_reader.transport import Transport  # noqa: E402

GMC_06 = {
    "0600": ["46 00 FF 48 54 00 00"],
    "0602": ["46 02 84 00 00 00 00", "46 02 66 80 03 80 46", "46 02 D0 80 03 80 6E"],
    "0605": ["46 05 0A 00 10 05 AA", "46 05 4A 00 1A 05 AA"],
    "060A": ["46 0A 09 00 00 00 00"],
    "060C": ["46 0C 60 76 1F 80 29"],
    "060E": ["46 0E 11 00 00 00 08"],
}


def gmc_port():
    return ReplayPort([{"tx": k, "rx": v} for k, v in GMC_06.items()])


def test_legacy_bitmap_has_a_filler_byte_before_it():
    # Read at byte 2 this bitmap would list 01-08, 0A, 0D, 12, 14, 16; the truck answered only 02, 05, 0A, 0C, 0E.
    assert walk_ids(Transport(gmc_port()), 3) == ["02", "05", "0A", "0C", "0E"]


def test_legacy_result_is_one_value_against_one_limit_typed_by_cid_bit_7():
    assert parse_legacy(bytes.fromhex("4602D08003806E")) == LegacyTestResult(
        tid="02", component="50", value=0x8003, limit=0x806E, limit_type="min")
    assert parse_legacy(bytes.fromhex("4605 0A 0010 05AA".replace(" ", ""))).limit_type == "max"
    assert parse_legacy(bytes.fromhex("4602D080")) is None  # truncated


def test_legacy_read_all_reads_every_listed_tid_and_nothing_else():
    port = gmc_port()
    tids, res = read_all_legacy(Transport(port))
    assert tids == ["02", "05", "0A", "0C", "0E"] and len(res) == 8
    assert port.unmatched == []
