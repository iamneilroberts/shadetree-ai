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
    for code in ("P0117", "P0172", "P0175", "P0171", "P0174", "P0101"):
        assert describe(code)["known"], code
