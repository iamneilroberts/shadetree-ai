from obd_reader.dtc_text import describe


def test_known_generic_code_has_own_words_description_and_hint():
    d = describe("P0171")
    assert d["known"] is True and "lean" in d["desc"].lower() and "bank 1" in d["desc"].lower() and d["hint"]


def test_unknown_code_gets_a_category_fallback_and_no_hint():
    d = describe("P0999")
    assert d["known"] is False and "powertrain" in d["desc"].lower() and d["hint"] == ""


def test_manufacturer_specific_code_is_labelled_as_such():
    assert "manufacturer" in describe("P1234")["desc"].lower()
    assert "body" in describe("B0001")["desc"].lower() or "manufacturer" in describe("B1001")["desc"].lower()


def test_every_code_the_demo_car_reports_is_described():
    for code in ("P0118", "P0171", "P0174"):
        assert describe(code)["known"], code


def test_a_make_specific_meaning_applies_only_to_that_make():
    honda = describe("P1456", "Honda")
    assert honda["known"] and "Honda" in honda["desc"] and describe("P1456", "Acura") == honda
    assert describe("P1456")["known"] is False and describe("P1456", "Toyota")["known"] is False


def test_sensor_circuit_low_reads_hot_and_high_reads_cold():
    # thermistor sensors: low voltage = hot reading, high voltage (open circuit) = cold reading [general knowledge, unverified]
    low, high = describe("P0117")["hint"].lower(), describe("P0118")["hint"].lower()
    assert "hot" in low and "cold" not in low
    assert "cold" in high and "hot" not in high and "open circuit" in high
