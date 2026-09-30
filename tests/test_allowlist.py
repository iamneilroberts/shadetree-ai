import pytest
from hypothesis import given, strategies as st

from obd_reader.allowlist import ALLOWED_MODES, ForbiddenCommand, check_command

# mode -> number of argument bytes the request takes
ARG_BYTES = {0x01: 1, 0x02: 2, 0x03: 0, 0x05: 2, 0x06: 1, 0x07: 0, 0x09: 1, 0x0A: 0}

ALLOWED = [
    "0100", "01 0C", "020C00", "03", "07", "0900", "0902", "0A",
    "ATZ", "ATD", "ATWS", "ATE0", "ATL0", "ATS0", "ATH1", "ATSP6", "ATSPA6",
    "ATTP6", "ATDP", "ATDPN", "ATRV", "ATI", "AT@1", "ATCAF1", "ATST64",
    "ATAT1", "ATSH7DF", "ATSH7E0", "ATCRA7E8", "ATCRA", "STI", "STDI",
    "0600", "0601", "06 20", "050101", "05 02 01",
    "  at i ",
]

FORBIDDEN = [
    # services outside the allowlist
    "04", "0400", "08", "0800", "0B", "0C", "0E",
    "10", "1901", "22F190", "2F", "3101",
    # ELM/STN commands that write, persist, or flood
    "ATPP", "ATPP0CSV01", "ATPPS", "ATMA", "ATCF", "ATCM", "STPX", "STPXH7DF", "STSAVE",
    # CAN auto-formatting off makes the first hex byte the ISO-TP PCI byte, so
    # "0104" would go out as a Mode 04 (clear DTCs) frame. Never allow it.
    "ATCAF0", "ATCAF 0",
    # wrong argument length
    "010", "01000", "0200", "020C", "0300", "0A00",
    "05", "0500", "05000000", "06", "060000",
    # injection / framing tricks (Review Focus 1)
    "0100\r04", "0100\n", "0100\r", "ATZ\rATPP0CSV01",
    # unicode look-alikes (Review Focus 2)
    "ATı", "ＡＴＺ", "０１００",
    "", " ",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed_commands_pass_and_are_canonical(cmd):
    canon = check_command(cmd)
    assert canon == cmd.replace(" ", "").upper()
    assert canon.isascii()


@pytest.mark.parametrize("cmd", FORBIDDEN)
def test_forbidden_commands_raise(cmd):
    with pytest.raises(ForbiddenCommand):
        check_command(cmd)


@pytest.mark.parametrize("cmd", [None, b"0100", 100, ["0100"]])
def test_non_string_input_raises(cmd):
    with pytest.raises(ForbiddenCommand):
        check_command(cmd)


def assert_modes_rejected(check):
    """Exhaustive: every hex frame is accepted iff mode+arg length is on the list."""
    for mode in range(256):
        for n_args in range(4):
            cmd = f"{mode:02X}" + "00" * n_args
            expected = ARG_BYTES.get(mode) == n_args
            try:
                check(cmd)
                accepted = True
            except ForbiddenCommand:
                accepted = False
            assert accepted == expected, cmd


def test_every_hex_frame_is_classified_correctly():
    assert_modes_rejected(check_command)
    assert ALLOWED_MODES == frozenset(ARG_BYTES)


def test_mutation_check_a_gate_that_allows_mode_04_is_caught():
    def mutant(cmd):
        if cmd.replace(" ", "").upper() == "04":
            return "04"
        return check_command(cmd)

    with pytest.raises(AssertionError):
        assert_modes_rejected(mutant)


_ALPHABET = "0123456789ABCDEFabcdef ATSPHCRDLEIZWMXQ@\r\n\t"


@given(st.text(alphabet=_ALPHABET, max_size=14))
def test_fuzz_near_miss_strings(s):
    try:
        canon = check_command(s)
    except ForbiddenCommand:
        return
    assert canon.isascii() and "\r" not in canon and "\n" not in canon
    if canon[:2] in ("AT", "ST"):
        assert not canon.startswith(("ATPP", "ATMA", "STPX"))
    else:
        assert int(canon[:2], 16) in ALLOWED_MODES


@given(st.text(max_size=20))
def test_fuzz_arbitrary_unicode_never_yields_non_ascii(s):
    try:
        canon = check_command(s)
    except ForbiddenCommand:
        return
    assert canon.isascii()
