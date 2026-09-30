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
