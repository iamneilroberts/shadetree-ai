from obd_reader.mode06 import Mode06Result, parse_results, supported_mids


def test_supported_mids_bitmap():
    assert supported_mids([bytes.fromhex("460080000001")], 0x00) == {"01", "20"}
    assert supported_mids([bytes.fromhex("462000000001")], 0x00) == set()  # wrong page for this base


def test_parse_two_result_groups():
    payload = bytes.fromhex("46" "01" "8B0A12340000FFFF" "8C0A000500000003")
    res = parse_results(payload)
    assert res[0] == Mode06Result(mid="01", tid="8B", uasid="0A", value=0x1234, minimum=0, maximum=0xFFFF,
                                  within_limits=True)
    assert res[1].tid == "8C" and res[1].value == 5 and res[1].within_limits is False


def test_min_greater_than_max_gives_unknown_limits():
    payload = bytes.fromhex("46" "02" "010A000500090003")
    assert parse_results(payload)[0].within_limits is None


def test_incomplete_trailing_group_is_dropped_not_raised():
    payload = bytes.fromhex("46" "01" "8B0A12340000FFFF" "8C0A00")
    assert [r.tid for r in parse_results(payload)] == ["8B"]


def test_not_a_mode06_payload_returns_nothing():
    assert parse_results(b"") == [] and parse_results(b"\x41\x01\x00") == [] and parse_results(b"\x46") == []
