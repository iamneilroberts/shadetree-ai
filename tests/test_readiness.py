from obd_reader.readiness import parse_readiness

REAL_ECU1 = bytes.fromhex("410100" "07E500")   # real Ridgeline: B=07 C=E5 D=00
REAL_ECU2 = bytes.fromhex("410100" "040000")   # real Ridgeline: B=04 C=00 D=00


def test_real_ridgeline_two_ecu_status_is_all_complete():
    ignition, m = parse_readiness([REAL_ECU1, REAL_ECU2])
    assert ignition == "spark"
    for name in ("misfire", "fuel_system", "components", "catalyst", "evap", "o2_sensor", "o2_sensor_heater", "egr"):
        assert m[name].supported is True and m[name].complete is True, name
    for name in ("heated_catalyst", "secondary_air", "ac_refrigerant"):
        assert m[name].supported is False and m[name].complete is None, name


def test_incomplete_flags_are_reported():
    # B=0x37: misfire+fuel_system incomplete (bits 4,5), components complete
    # D=0x25: catalyst(bit0), evap(bit2), o2_sensor(bit5) incomplete
    ignition, m = parse_readiness([bytes.fromhex("410100" "37E525")])
    assert m["misfire"].complete is False and m["fuel_system"].complete is False
    assert m["components"].complete is True
    assert m["catalyst"].complete is False and m["evap"].complete is False and m["o2_sensor"].complete is False
    assert m["o2_sensor_heater"].complete is True and m["egr"].complete is True


def test_a_monitor_is_complete_only_if_every_supporting_ecu_says_so():
    a = bytes.fromhex("410100" "070100")   # catalyst supported, complete
    b = bytes.fromhex("410100" "070101")   # catalyst supported, incomplete
    _, m = parse_readiness([a, b])
    assert m["catalyst"].complete is False
    _, m2 = parse_readiness([b, a])
    assert m2["catalyst"].complete is False


def test_compression_ignition_is_detected():
    ignition, m = parse_readiness([bytes.fromhex("410100" "0F0000")])
    assert ignition == "compression"
    assert m["misfire"].supported and "catalyst" not in m


def test_garbage_and_short_payloads_yield_nothing():
    assert parse_readiness([]) == (None, {})
    assert parse_readiness([b"\x41\x01\x00"]) == (None, {})
    assert parse_readiness([bytes.fromhex("410200000000")]) == (None, {})
