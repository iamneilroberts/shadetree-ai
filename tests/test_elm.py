import pytest

from hypothesis import given, strategies as st

from obd_reader.elm import (
    classify, decode_dtc, decode_dtc_list, decode_supported, parse_all, parse_headers, parse_response,
)

VIN_A = ["014", "0: 49 02 01 31 48 47", "1: 43 4D 38 32 36 33 33", "2: 41 30 30 34 33 35 32"]
VIN_B = ["014", "0: 49 02 01 35 46 50", "1: 59 4B 33 46 35 31 52", "2: 42 30 30 30 30 30 31"]


def test_parse_all_returns_one_payload_per_responding_ecu():
    lines = ["SEARCHING...", "41 00 B7 BC A8 93", "41 00 98 18 80 03"]
    assert parse_all(lines, 0x41) == [bytes.fromhex("4100B7BCA893"), bytes.fromhex("410098188003")]


def test_parse_all_handles_short_replies_from_two_ecus():
    assert parse_all(["43 00", "43 00"], 0x43) == [b"\x43\x00", b"\x43\x00"]


def test_parse_all_handles_two_multi_frame_blocks_and_mixed_replies():
    payloads = parse_all(VIN_A + ["49 00 40 00 00 00"] + VIN_B, 0x49)
    assert len(payloads) == 3
    assert payloads[0][3:].decode() == "1HGCM82633A004352"
    assert payloads[1] == bytes.fromhex("490040000000")
    assert payloads[2][3:].decode() == "5FPYK3F51RB000001"


@pytest.mark.parametrize(
    "lines",
    [[], ["NO DATA"], ["UNABLE TO CONNECT"], ["7F 09 12"], ["ZZ"], ["014", "garbage"],
     ["014", "0: 49 02 01 31 48 47"], ["000", "0: 49"], ["0FF"]],
)
def test_parse_all_returns_empty_for_errors_and_garbage_never_raises(lines):
    assert parse_all(lines, 0x49) == []


@pytest.mark.parametrize(
    "lines,expected",
    [
        (["7E8 06 41 00 BE 3F A8 13", "7E9 06 41 00 98 18 80 03"], ["7E8", "7E9"]),
        (["18 DA F1 10 06 41 00 B7 BC A8 93", "18 DA F1 18 06 41 00 98 18 80 03"], ["18DAF110", "18DAF118"]),
        (["SEARCHING...", "7E8 06 41 00 BE 3F A8 13", "7E8 06 41 00 BE 3F A8 13"], ["7E8"]),
        (["41 00 BE 3F A8 13"], []),          # headers off: nothing to attribute
        (["41 00 98 41 00"], []),             # "41 00" inside data is not a header
        (["NO DATA"], []), ([], []), (["ZZ ZZ 41"], []),
    ],
)
def test_parse_headers(lines, expected):
    assert parse_headers(lines) == expected


def test_parse_response_is_the_first_of_parse_all():
    lines = ["41 00 B7 BC A8 93", "41 00 98 18 80 03"]
    assert parse_response(lines, 0x41) == parse_all(lines, 0x41)[0]


def test_single_frame():
    assert parse_response(["41 00 BE 3F A8 13"], 0x41) == bytes.fromhex("4100BE3FA813")


def test_searching_line_is_ignored():
    assert parse_response(["SEARCHING...", "41 0C 1A F8"], 0x41) == bytes.fromhex("410C1AF8")


def test_kline_bus_init_ok_line_is_noise_not_an_error():
    lines = ["BUS INIT: ...OK", "41 00 BE 3F B8 13"]
    assert parse_response(lines, 0x41) == bytes.fromhex("4100BE3FB813")


@pytest.mark.parametrize("lines", [["BUS INIT: ERROR"], ["BUS INIT: ...ERROR"], ["BUS INIT: ..."]])
def test_kline_bus_init_failure_returns_none(lines):
    assert parse_response(lines, 0x41) is None


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


@pytest.mark.parametrize(
    "lines,sid,expected",
    [
        (["41 0C 1A F8"], 0x41, "ok"),
        (["SEARCHING...", "41 00 B7 BC A8 93", "41 00 98 18 80 03"], 0x41, "ok"),
        (VIN_A, 0x49, "ok"),
        (["7F 01 12", "41 0C 1A F8"], 0x41, "ok"),          # one ECU refuses, another answers: usable
        (["NO DATA"], 0x41, "no_data"),
        (["SEARCHING...", "NO DATA"], 0x41, "no_data"),
        (["7F 01 12"], 0x41, "nrc:12"),                     # negative response keeps its NRC
        (["7F 09 31"], 0x49, "nrc:31"),
        (["7F 03 22", "7F 03 11"], 0x43, "nrc:22"),         # first ECU's code
        (["43 00"], 0x47, "wrong_sid"),                      # answered, but not the request we sent
        (["7F 03 12"], 0x41, "wrong_sid"),                   # a refusal of some other request
        (["?"], 0x41, "adapter_error"),
        (["UNABLE TO CONNECT"], 0x41, "adapter_error"),
        (["CAN ERROR"], 0x41, "adapter_error"),
        (["BUS INIT: ...ERROR"], 0x41, "adapter_error"),
        (["BUFFER FULL", "41 0C 1A F8"], 0x41, "adapter_error"),  # parse_all drops it too
        ([], 0x41, "adapter_error"),                         # the adapter printed nothing
        (["ZZ"], 0x41, "garbled"),
        (["41 0"], 0x41, "garbled"),
        (["014", "0: 49 02 01 31 48 47"], 0x49, "garbled"),  # truncated multi-frame
        (["7F 01"], 0x41, "garbled"),                        # NRC with no code
    ],
)
def test_classify(lines, sid, expected):
    assert classify(lines, sid) == expected


@given(st.lists(st.text(alphabet="0123456789ABCDEF :?.NODAT", max_size=24), max_size=5), st.integers(0x41, 0x4A))
def test_classify_never_raises_and_ok_means_parse_all_has_a_payload(lines, sid):
    got = classify(lines, sid)
    assert got in {"ok", "no_data", "wrong_sid", "adapter_error", "garbled"} or got.startswith("nrc:")
    assert (got == "ok") == bool(parse_all(lines, sid))
