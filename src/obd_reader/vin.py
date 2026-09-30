"""VIN helpers: the ISO 3779 check digit and a detector for VIN-looking tokens in text.

The detector exists so a real VIN can never be committed by accident: it flags tokens that
either pass the check digit (North American VINs must) or have the usual North American shape.
"""
import re

_TRANSLIT = {
    **{str(d): d for d in range(10)},
    **dict(zip("ABCDEFGH", range(1, 9))),
    **dict(zip("JKLMN", range(1, 6))),
    "P": 7, "R": 9,
    **dict(zip("STUVWXYZ", range(2, 10))),
}
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
_VIN_CHARS = re.compile(r"[A-HJ-NPR-Z0-9]{17}")
_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Za-z0-9])")
_YEAR_CHARS = frozenset("ABCDEFGHJKLMNPRSTVWXY123456789")


def check_digit(vin: str) -> str:
    """The check character (position 9) a VIN of this shape should carry."""
    if not isinstance(vin, str) or not _VIN_CHARS.fullmatch(vin):
        raise ValueError("a VIN is 17 characters from A-Z (no I, O, Q) and 0-9")
    total = sum(_TRANSLIT[c] * w for c, w in zip(vin, _WEIGHTS))
    r = total % 11
    return "X" if r == 10 else str(r)


def check_digit_ok(vin: str) -> bool:
    return isinstance(vin, str) and bool(_VIN_CHARS.fullmatch(vin)) and vin[8] == check_digit(vin)


def with_check_digit(body: str) -> str:
    """Fill the '?' at position 9 of a made-up VIN body with its correct check digit (for tests and fixtures)."""
    if len(body) != 17 or body[8] != "?":
        raise ValueError("body must be 17 characters with '?' at position 9")
    return body[:8] + check_digit(body.replace("?", "0")) + body[9:]


def looks_like_vin(token: str) -> bool:
    if not _VIN_CHARS.fullmatch(token):
        return False
    letters, digits = sum(c.isalpha() for c in token), sum(c.isdigit() for c in token)
    if letters < 2 or digits < 4:  # plain words and numeric ids are not VINs
        return False
    # valid check digit, or the North American shape: plausible model-year character, numeric serial
    return check_digit_ok(token) or (token[9] in _YEAR_CHARS and token[11:].isdigit())


def find_vins(text: str) -> list[str]:
    """Unique VIN-looking tokens in the text, in order of appearance."""
    return list(dict.fromkeys(t for t in _TOKEN.findall(text) if looks_like_vin(t)))
