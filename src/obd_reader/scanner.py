"""Minimal read-only scan: VIN, protocol, supported PIDs, DTCs, MIL."""
from datetime import datetime, timezone

from obd_reader import __version__
from obd_reader.elm import decode_dtc_list, decode_supported, parse_response
from obd_reader.snapshot import (
    VIN_RE, Adapter, Dtc, Dtcs, Mil, Protocol, Snapshot, Source, Vehicle,
)
from obd_reader.transport import Transport

INIT = ("ATZ", "ATE0", "ATL0", "ATH0")


def _first(lines: list[str]) -> str | None:
    return lines[0] if lines else None


def _dtcs(transport: Transport, cmd: str, sid: int) -> list[Dtc]:
    payload = parse_response(transport.send(cmd), sid)
    return [Dtc(code=c) for c in decode_dtc_list(payload)] if payload else []


def scan(
    transport: Transport,
    *,
    snapshot_id: str,
    captured_at: datetime | None = None,
    kind: str = "replay",
    protocol: str | None = None,
    transcript: str | None = None,
) -> Snapshot:
    warnings: list[str] = []
    for cmd in INIT:
        transport.send(cmd)
    if protocol is not None:
        transport.send(f"ATSP{protocol}")
    ati = _first(transport.send("ATI"))
    sti = _first(transport.send("STI"))
    genuine_stn = bool(sti and sti.upper().startswith("STN"))
    adapter = Adapter(
        ati=ati,
        sti=sti if genuine_stn else None,
        chip=sti.split()[0] if genuine_stn else None,
        genuine_stn=genuine_stn,
    )
    dp = _first(transport.send("ATDP"))
    proto = Protocol(
        name=dp.removeprefix("AUTO, ") if dp else None,
        atsp=protocol,
        pinned=protocol is not None,
    )

    supported: dict[str, list[str]] = {}
    pids01: list[str] = []
    base = 0x00
    while base <= 0xE0:
        p = parse_response(transport.send(f"01{base:02X}"), 0x41)
        if p is None or len(p) < 6 or p[1] != base:
            break
        pids = decode_supported(base, p[2:6])
        pids01 += pids
        if f"{base + 0x20:02X}" not in pids:
            break
        base += 0x20
    if pids01:
        supported["01"] = pids01

    # DTC and VIN replies use a different layout on non-CAN buses (no count byte;
    # multi-line VIN). Decoding them as CAN would give wrong codes, so skip until
    # Phase 4 adds the non-CAN layouts.
    is_can = "15765" in (proto.name or "")
    vin, vin_source = None, "none"
    dtcs = Dtcs()
    if is_can:
        p9 = parse_response(transport.send("0900"), 0x49)
        if p9 is not None and len(p9) >= 6:
            pids09 = decode_supported(0x00, p9[2:6])
            supported["09"] = pids09
        else:
            pids09 = []
        if "02" in pids09:
            pv = parse_response(transport.send("0902"), 0x49)
            candidate = pv[3:20].decode("ascii", errors="replace") if pv else ""
            if VIN_RE.fullmatch(candidate):
                vin, vin_source = candidate, "obd"
            else:
                warnings.append(f"Mode 09 returned an invalid VIN: {candidate!r}")
        else:
            warnings.append("VIN unsupported via Mode 09")

        dtcs = Dtcs(
            stored=_dtcs(transport, "03", 0x43),
            pending=_dtcs(transport, "07", 0x47),
            permanent=_dtcs(transport, "0A", 0x4A),
        )
    else:
        warnings.append(
            f"non-CAN or unknown protocol ({proto.name!r}): DTC and VIN decoding skipped (not supported yet)"
        )

    mil = Mil()
    p1 = parse_response(transport.send("0101"), 0x41)
    if p1 is not None and len(p1) >= 3 and p1[1] == 0x01:
        mil = Mil(on=bool(p1[2] & 0x80), dtc_count=p1[2] & 0x7F)

    return Snapshot(
        snapshot_id=snapshot_id,
        captured_at=captured_at or datetime.now(timezone.utc),
        source=Source(kind=kind, adapter=adapter, tool_version=__version__, transcript=transcript),
        vehicle=Vehicle(vin=vin, vin_source=vin_source),
        protocol=proto,
        supported_pids=supported,
        dtcs=dtcs,
        mil=mil,
        warnings=warnings,
    )
