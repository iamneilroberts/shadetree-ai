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


def test_readings_added_for_the_ridgeline_decode_from_its_real_bytes():
    from obd_reader.pids import decode_pid, pid_label
    assert decode_pid("3C", bytes.fromhex("1760")).value == 558.4
    lam = decode_pid("24", bytes.fromhex("7F654979")).value
    assert 0.99 < lam < 1.01
    assert decode_pid("23", bytes.fromhex("0155")).value == 3410
    assert decode_pid("62", bytes.fromhex("91")).value == 20
    assert decode_pid("A6", bytes.fromhex("0012ADD6")).value == 122415.0
    assert decode_pid("55", bytes.fromhex("80")).value == 0
    assert pid_label("51", 1) == "Gasoline" and pid_label("03", 2) == "Closed loop" and pid_label("0C", 800) is None
