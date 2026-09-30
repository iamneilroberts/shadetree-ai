"""Read-only command allowlist: the single source of truth for what may be sent.

`check_command` returns the canonical (uppercase, spaceless, ASCII) command that
the transport writes. Anything else raises ForbiddenCommand.

Not enabled yet (see docs/design.md §13): UDS 0x19 / 0x22, STIX-style STN
commands (unverified on hardware), ATPPS, ATCAF0.
"""
import re

ALLOWED_MODES = frozenset({0x01, 0x02, 0x03, 0x05, 0x06, 0x07, 0x09, 0x0A})


class ForbiddenCommand(ValueError):
    """Raised for any command that is not on the read-only allowlist."""


_H = "[0-9A-F]"
_PATTERNS = tuple(
    re.compile(p)
    for p in (
        # OBD services: hex, spaces removed, exact argument lengths
        rf"01{_H}{{2}}",      # Mode 01 PID
        rf"02{_H}{{4}}",      # Mode 02 PID + frame number
        r"03",                # stored DTCs
        rf"05{_H}{{4}}",      # Mode 05 O2 sensor test results: TID + sensor (non-CAN)
        rf"06{_H}{{2}}",      # Mode 06 on-board test results: monitor id (MID)
        r"07",                # pending DTCs
        rf"09{_H}{{2}}",      # Mode 09 PID
        r"0A",                # permanent DTCs
        # ELM327 AT commands (explicit list)
        r"ATZ", r"ATD", r"ATWS",
        r"ATE[01]", r"ATL[01]", r"ATS[01]", r"ATH[01]",
        r"ATDPN?", r"ATRV", r"ATI", r"AT@1",
        r"ATCAF1", r"ATAT[012]",  # ATCAF0 is refused: see test_allowlist.py (CAF0 + 0104)
        r"ATSPA?[0-9]", r"ATTPA?[0-9]",  # protocols A-C (J1939, user CAN) are refused
        rf"ATST{_H}{{2}}",
        rf"ATSH(?:{_H}{{3}}|{_H}{{6}}|{_H}{{8}})",
        rf"ATCRA(?:{_H}{{3}}|{_H}{{8}})?",
        # STN identify (read-only)
        r"STI", r"STDI",
    )
)


def check_command(cmd: str) -> str:
    if not isinstance(cmd, str) or not cmd.isascii():
        raise ForbiddenCommand(f"not an ASCII string: {cmd!r}")
    canon = cmd.replace(" ", "").upper()
    if any(p.fullmatch(canon) for p in _PATTERNS):
        return canon
    raise ForbiddenCommand(f"not on the read-only allowlist: {cmd!r}")
