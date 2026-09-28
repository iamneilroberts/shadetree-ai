"""Snapshot schema v0.1 (docs/design.md §6). Later phases add freeze frame,
readiness monitors, live samples, and user context."""
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VIN_RE = re.compile(r"[A-HJ-NPR-Z0-9]{17}")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Adapter(_Model):
    ati: str | None = None
    sti: str | None = None
    chip: str | None = None
    genuine_stn: bool | None = None


class Source(_Model):
    kind: Literal["live", "replay", "import"]
    adapter: Adapter = Field(default_factory=Adapter)
    tool_version: str
    transcript: str | None = None


class Decoded(_Model):
    make: str | None = None
    model: str | None = None
    year: int | None = None
    engine: str | None = None
    source: str | None = None
    error_code: str | None = None


class Vehicle(_Model):
    vin: str | None = None
    vin_source: Literal["obd", "manual", "photo", "none"] = "none"
    decoded: Decoded | None = None

    @field_validator("vin")
    @classmethod
    def _check_vin(cls, v: str | None) -> str | None:
        if v is not None and not VIN_RE.fullmatch(v):
            raise ValueError("invalid VIN")
        return v


class Protocol(_Model):
    name: str | None = None
    atsp: str | None = None
    pinned: bool = False


class Ecu(_Model):
    header: str
    role: str | None = None
    modes_seen: list[str] = Field(default_factory=list)


class Dtc(_Model):
    code: str
    ecu: str | None = None
    ref: str | None = None


class Dtcs(_Model):
    stored: list[Dtc] = Field(default_factory=list)
    pending: list[Dtc] = Field(default_factory=list)
    permanent: list[Dtc] = Field(default_factory=list)


class Mil(_Model):
    on: bool | None = None
    dtc_count: int | None = None


class Snapshot(_Model):
    schema_version: Literal["0.1"] = "0.1"
    snapshot_id: str
    captured_at: datetime
    source: Source
    vehicle: Vehicle = Field(default_factory=Vehicle)
    protocol: Protocol = Field(default_factory=Protocol)
    ecus: list[Ecu] = Field(default_factory=list)
    supported_pids: dict[str, list[str]] = Field(default_factory=dict)
    dtcs: Dtcs = Field(default_factory=Dtcs)
    mil: Mil = Field(default_factory=Mil)
    warnings: list[str] = Field(default_factory=list)
