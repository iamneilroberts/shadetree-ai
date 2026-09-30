from obd_reader.vin import with_check_digit
from obd_reader.vehicle import vehicle_key

A = with_check_digit("9SXSMUL1?T0000001")
SAME_CLASS_OTHER_SERIAL = with_check_digit("9SXSMUL1?T0999999")
OTHER_YEAR = with_check_digit("9SXSMUL1?V0000001")


def test_key_is_positions_1_to_8_and_10():
    assert vehicle_key(A) == "9SXSMUL1-T"


def test_key_ignores_the_serial_and_the_check_digit():
    assert vehicle_key(A) == vehicle_key(SAME_CLASS_OTHER_SERIAL)
    assert len(vehicle_key(A)) == 10 and A[-6:] not in vehicle_key(A)


def test_model_year_changes_the_key():
    assert vehicle_key(A) != vehicle_key(OTHER_YEAR)


def test_malformed_vin_has_no_key():
    for bad in ("", "short", "9SXSMUL1?T0000001", "9sxsmul10t0000001", None, 123, "I" * 17):
        assert vehicle_key(bad) is None
