import pytest

from obd_reader.vin import check_digit, check_digit_ok, find_vins, looks_like_vin, with_check_digit

# Public, documented examples (not real cars): the Wikipedia VIN example and the all-ones VIN.
WIKI_EXAMPLE = "1M8GDM9AXKP042788"
ALL_ONES = "11111111111111111"


def fake(body_with_hole: str) -> str:
    """A syntactically valid VIN made up on the spot (never a real car)."""
    return with_check_digit(body_with_hole)


def test_known_valid_vins_pass_the_check_digit():
    assert check_digit_ok(WIKI_EXAMPLE) and check_digit(WIKI_EXAMPLE) == "X"
    assert check_digit_ok(ALL_ONES)


def test_a_single_changed_character_breaks_the_check_digit():
    # built in code, not written out: the repo guard flags any VIN-shaped literal that is not allowlisted
    wrong_serial = WIKI_EXAMPLE[:-1] + "9"
    wrong_check = WIKI_EXAMPLE[:8] + "1" + WIKI_EXAMPLE[9:]
    assert not check_digit_ok(wrong_serial)
    assert not check_digit_ok(wrong_check)


@pytest.mark.parametrize("bad", ["", "1M8GDM9AXKP04278", "1M8GDM9AXKP0427888", "1M8GDM9AXKP04278I", "1m8gdm9axkp042788"])
def test_wrong_length_or_characters_are_never_valid(bad):
    assert not check_digit_ok(bad)


def test_with_check_digit_builds_a_valid_vin_and_finds_x():
    v = fake("1M8GDM9A?KP042788")
    assert v == WIKI_EXAMPLE and check_digit_ok(v)
    assert check_digit_ok(fake("5FPYK3F5?RB999999"))


def test_find_vins_finds_valid_vins_in_json_prose_and_paths():
    vin = fake("5FPYK3F5?RB999999")
    text = f'{{"vin": "{vin}", "note": "car {vin}."}} see /data/{vin}.json and (VIN:{vin})'
    assert find_vins(text) == [vin]


def test_find_vins_ignores_longer_tokens_and_lowercase_and_ordinary_words():
    vin = fake("5FPYK3F5?RB999999")
    assert find_vins(f"X{vin}") == [] and find_vins(f"{vin}9") == []
    assert find_vins(vin.lower()) == []
    assert find_vins("SHADETREEAICONSOLEXYZ THISISNOTAVINATALL1") == []
    assert find_vins("sha256-BLRDBEj2Y2HpV7pQCbmNzaIWa3tCll7WVzrSWTR7tdc=") == []


def test_shape_heuristic_catches_vins_with_a_wrong_check_digit():
    # European-style or mistyped VIN: bad check digit, but the North American shape (year char, numeric serial)
    v = list(fake("5FPYK3F5?RB999999"))
    v[8] = "0" if v[8] != "0" else "1"
    bad = "".join(v)
    assert not check_digit_ok(bad) and looks_like_vin(bad) and find_vins(bad) == [bad]


def test_ordinary_identifiers_are_not_vins():
    for token in ("ABCDEFGHJKLMNPRST", "12345678901234567", "SIMULATEDNOCAR0000"[:17], "AAAAAAAAAAAAAAAAA"):
        assert not looks_like_vin(token), token
