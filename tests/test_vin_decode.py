import json
from pathlib import Path

import pytest

from obd_reader import vin_decode as vd
from obd_reader.__main__ import main
from obd_reader.vehicle import make_of
from obd_reader.vin import with_check_digit

FIXTURE = (Path(__file__).parent / "fixtures" / "vpic_partial_honda.json").read_bytes()
SEDAN = with_check_digit("1HGCM826?3A004352")  # the allowlisted synthetic sedan


def test_model_year_uses_both_cycles():
    assert vd.model_year("1HGCM826-3", this_year=2026) == 2003   # digit at position 7: 1980-2009
    assert vd.model_year("5FPYK3F5-R", this_year=2026) == 2024   # letter at position 7: 2010-2039


def test_position_7_picks_the_cycle_and_the_future_falls_back():
    assert vd.model_year("ABCDEFGH-T", this_year=2026) == 2026   # same year character: a letter at position 7
    assert vd.model_year("ABCDEF1H-T", this_year=2026) == 1996   # ... and a digit there
    assert vd.model_year("ABCDEFGH-5", this_year=2026) == 2005   # 2035 is in the future: the earlier cycle


def test_wmi_make_hit_and_miss_and_honda_table_unchanged():
    assert vd.make_of_wmi("1FT") == "Ford" and vd.make_of_wmi("JTH") == "Lexus" and vd.make_of_wmi("5FP") == "Honda"
    assert vd.make_of_wmi("9SX") is None
    assert vd.offline("9SXSMUL1-T")["make"] is None and vd.offline("9SXSMUL1-T")["model"] is None
    assert make_of("1FTAB123-R") is None and make_of("JH4AB123-R") == "Acura"   # DTC hints still Honda/Acura only


def test_partial_vin_carries_no_check_digit_or_serial():
    key = vd.to_key(SEDAN)
    assert key == "1HGCM826-3"
    p = vd.partial_vin(key)
    assert p == "1HGCM826*3*******" and SEDAN[8] not in p[8] and SEDAN[10:] not in p
    assert vd.to_key("1hgcm826*3*******") == key and vd.to_key(" 1hgcm826-3 ") == key
    for bad in ("1HGCM826-3/../x", "1HGCM826", "1HGCM826-3?a=b", "", None, "IHGCM826-3"):
        with pytest.raises(ValueError):
            vd.to_key(bad)
    with pytest.raises(ValueError):
        vd.partial_vin("1HGCM826*3")


def test_vpic_reply_is_parsed_and_cached(tmp_path, monkeypatch):
    urls = []
    monkeypatch.setattr(vd, "_fetch", lambda url: urls.append(url) or FIXTURE)
    r = vd.lookup("1HGCM826-3", tmp_path)
    assert r == {"make": "Honda", "model": "Accord", "year": 2003, "trim": "EX-V6", "cylinders": "6",
                 "displacement_l": "3.0", "fuel": "Gasoline", "source": "nhtsa"}
    assert urls == ["https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/1HGCM826*3*******?format=json"]
    assert vd.lookup("1HGCM826-3", tmp_path) == r and len(urls) == 1   # the second ask comes from the cache
    assert json.loads((tmp_path / vd.CACHE_NAME).read_text())["1HGCM826-3"]["model"] == "Accord"


def test_offline_or_empty_reply_is_unavailable_and_not_cached(tmp_path, monkeypatch):
    def boom(url):
        raise TimeoutError("timed out")
    monkeypatch.setattr(vd, "_fetch", boom)
    with pytest.raises(vd.LookupUnavailable):
        vd.lookup("1HGCM826-3", tmp_path)
    monkeypatch.setattr(vd, "_fetch", lambda url: json.dumps({"Results": [{"Make": "", "Model": "", "ErrorCode": "7"}]}).encode())
    with pytest.raises(vd.LookupUnavailable):
        vd.lookup("1HGCM826-3", tmp_path)
    assert not (tmp_path / vd.CACHE_NAME).exists()


def test_cli_reduces_a_full_vin_to_the_key_and_never_echoes_it(tmp_path, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(vd, "_fetch", lambda url: sent.append(url) or FIXTURE)
    assert main(["vin-info", SEDAN, "--lookup", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "1HGCM826-3" in out and "Accord" in out and SEDAN not in out and SEDAN[11:] not in out
    assert SEDAN[11:] not in sent[0] and SEDAN not in (tmp_path / vd.CACHE_NAME).read_text()
