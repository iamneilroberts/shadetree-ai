import pytest

from obd_reader.elm import decode_dtc, decode_dtc_list, decode_supported, parse_response


def test_single_frame():
    assert parse_response(["41 00 BE 3F A8 13"], 0x41) == bytes.fromhex("4100BE3FA813")


def test_searching_line_is_ignored():
    assert parse_response(["SEARCHING...", "41 0C 1A F8"], 0x41) == bytes.fromhex("410C1AF8")


def test_multi_frame_vin():
    lines = ["014", "0: 49 02 01 31 48 47", "1: 43 4D 38 32 36 33 33", "2: 41 30 30 34 33 35 32"]
    payload = parse_response(lines, 0x49)
    assert payload[:3] == bytes([0x49, 0x02, 0x01])
    assert payload[3:].decode("ascii") == "1HGCM82633A004352"


@pytest.mark.parametrize(
    "lines",
    [
        ["NO DATA"],
        ["?"],
        ["UNABLE TO CONNECT"],
        ["CAN ERROR"],
        ["7F 09 12"],                       # negative response
        [],                                 # empty reply
        ["41 0C 1A F8"],                    # wrong SID for the request below
    ],
)
def test_unsupported_or_wrong_sid_returns_none(lines):
    assert parse_response(lines, 0x49) is None


def test_truncated_multi_frame_returns_none():  # Review Focus 4
    lines = ["014", "0: 49 02 01 31 48 47", "1: 43 4D 38 32 36 33 33"]
    assert parse_response(lines, 0x49) is None


@pytest.mark.parametrize(
    "lines",
    [["014", "garbage"], ["ZZ ZZ"], ["41 0"], ["0FF"], ["000", "0: 49"]],
)
def test_garbage_returns_none_and_never_raises(lines):  # Review Focus 4
    assert parse_response(lines, 0x49) is None


@pytest.mark.parametrize(
    "b1,b2,code",
    [(0x01, 0x71, "P0171"), (0x43, 0x00, "C0300"), (0x80, 0x00, "B0000"), (0xC1, 0x00, "U0100"), (0x21, 0x04, "P2104")],
)
def test_decode_dtc(b1, b2, code):
    assert decode_dtc(b1, b2) == code


def test_decode_dtc_list_skips_padding_and_honours_count():
    assert decode_dtc_list(bytes.fromhex("4302 0171 C100 0000")) == ["P0171", "U0100"]
    assert decode_dtc_list(bytes.fromhex("43 00 00 00 00 00 00")) == []
    assert decode_dtc_list(b"\x43") == []


def test_decode_dtc_list_tolerates_truncation():
    assert decode_dtc_list(bytes.fromhex("43 02 01 71 C1")) == ["P0171"]


def test_decode_supported():
    pids = decode_supported(0x00, bytes.fromhex("BE3FA813"))
    for expected in ["01", "03", "04", "05", "06", "07", "0B", "0C", "0D", "0E", "0F", "10", "11", "13", "15", "1C", "1F", "20"]:
        assert expected in pids
    for absent in ["02", "08", "09", "0A", "12", "14"]:
        assert absent not in pids
    assert decode_supported(0x20, bytes.fromhex("80000000")) == ["21"]
