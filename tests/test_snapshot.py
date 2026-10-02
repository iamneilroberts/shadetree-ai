from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from obd_reader.snapshot import Dtc, Dtcs, Snapshot, Source, Vehicle


def make(**over):
    base = dict(
        snapshot_id="x",
        captured_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        source=Source(kind="replay", tool_version="0.1.0"),
    )
    base.update(over)
    return Snapshot(**base)


def test_defaults_are_sensible():
    s = make()
    assert s.schema_version == "0.1"
    assert s.vehicle.vin is None and s.vehicle.vin_source == "none"
    assert s.dtcs.stored == [] and s.warnings == []


def test_snapshot_saved_before_mode09_and_battery_fields_still_loads():
    old = make().model_dump(mode="json")
    del old["mode09"]
    for k in ("device", "supply_voltage"):
        del old["source"]["adapter"][k]
    s = Snapshot.model_validate(old)
    assert s.mode09.cal_ids == [] and s.source.adapter.supply_voltage is None


def test_snapshot_saved_before_reply_classes_still_loads():
    old = make().model_dump(mode="json")
    del old["replies"]
    assert Snapshot.model_validate(old).replies == []


def test_snapshot_saved_before_undecoded_capture_still_loads():
    old = make().model_dump(mode="json")
    del old["undecoded"]
    assert Snapshot.model_validate(old).undecoded == []


def test_json_round_trip():
    s = make(
        vehicle=Vehicle(vin="1HGCM82633A004352", vin_source="obd"),
        dtcs=Dtcs(stored=[Dtc(code="P0171")]),
        supported_pids={"01": ["0C", "0D"]},
    )
    assert Snapshot.model_validate_json(s.model_dump_json()) == s


@pytest.mark.parametrize("vin", ["1HGCM82633A00435", "1HGCM82633A0043521", "1HGCM82633AO04352", "1hgcm82633a004352", ""])
def test_bad_vin_is_rejected(vin):
    with pytest.raises(ValidationError):
        Vehicle(vin=vin, vin_source="manual")


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        make(surprise=1)


def test_wrong_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        make(schema_version="0.2")


def test_json_schema_is_exportable():
    schema = Snapshot.model_json_schema()
    assert "schema_version" in schema["properties"]
