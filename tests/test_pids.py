import pytest

from obd_reader.pids import PIDS, decode_pid, pid_name


@pytest.mark.parametrize(
    "pid,data,value,unit",
    [
        ("05", "7B", 83, "C"),
        ("05", "00", -40, "C"),
        ("06", "80", 0.0, "%"),
        ("06", "00", -100.0, "%"),
        ("07", "FF", 99.2, "%"),
        ("08", "8C", 9.4, "%"),
        ("09", "74", -9.4, "%"),
        ("04", "80", 50.2, "%"),
        ("0A", "64", 300, "kPa"),
        ("0B", "63", 99, "kPa"),
        ("0C", "1AF8", 1726.0, "rpm"),
        ("0D", "3C", 60, "km/h"),
        ("0E", "80", 0.0, "deg"),
        ("0F", "3C", 20, "C"),
        ("10", "0393", 9.15, "g/s"),
        ("11", "FF", 100.0, "%"),
        ("14", "5AFF", 0.45, "V"),
        ("1F", "0064", 100, "s"),
        ("42", "3630", 13.872, "V"),
        ("43", "00FF", 100.0, "%"),
        ("44", "8000", 1.0, "ratio"),
        ("46", "28", 0, "C"),
        ("5C", "5A", 50, "C"),
        ("5E", "0064", 5.0, "L/h"),
    ],
)
def test_decode(pid, data, value, unit):
    v = decode_pid(pid, bytes.fromhex(data))
    assert v is not None and v.unit == unit and v.raw == data
    assert v.value == pytest.approx(value, abs=0.01)


def test_unknown_pid_and_short_data_return_none():
    assert decode_pid("FF", b"\x00") is None
    assert decode_pid("0C", b"\x1a") is None  # RPM needs 2 bytes


def test_names_are_unique_and_lowercase_snake():
    names = [d.name for d in PIDS.values()]
    assert len(names) == len(set(names))
    assert all(n == n.lower() and " " not in n for n in names)
    assert pid_name("0C") == "engine_rpm" and pid_name("EE") == "unknown"


def test_every_pid_key_is_two_upper_hex_digits_and_matches_its_def():
    for key, d in PIDS.items():
        assert len(key) == 2 and key == key.upper() and d.pid == key
        int(key, 16)
