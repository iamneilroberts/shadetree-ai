"""Minimal read-only scan: VIN, protocol, supported PIDs, DTCs, MIL."""
from datetime import datetime, timezone

from obd_reader import __version__
from obd_reader.adapter import identify, init_adapter
from obd_reader.elm import decode_dtc, decode_dtc_list, decode_supported, parse_all, parse_headers
from obd_reader.pids import PIDS, decode_pid
from obd_reader.readiness import parse_readiness
from obd_reader.snapshot import (
    VIN_RE, Dtc, Dtcs, Ecu, FreezeFrame, Mil, PidValue, Protocol, Snapshot, Source, UserContext, Vehicle,
)
from obd_reader.transport import Transport


def _first(lines: list[str]) -> str | None:
    return lines[0] if lines else None


def _dtcs(transport: Transport, cmd: str, sid: int) -> list[Dtc]:
    """Union of the codes every responding ECU reports, first-seen order."""
    codes: list[str] = []
    for payload in parse_all(transport.send(cmd), sid):
        codes += [c for c in decode_dtc_list(payload) if c not in codes]
    return [Dtc(code=c) for c in codes]


def _discover_ecus(transport: Transport) -> list[Ecu]:
    """One headers-on Mode 01 request to learn which CAN ids answer, then headers off again."""
    transport.send("ATH1")
    try:
        lines = transport.send("0100")
    finally:
        transport.send("ATH0")  # every later parse assumes headers off
    return [Ecu(header=h, modes_seen=["01"]) for h in parse_headers(lines)]


def _supported(payloads: list[bytes], base: int) -> set[str]:
    """PIDs advertised by any ECU whose reply is for this bitmap page."""
    out: set[str] = set()
    for p in payloads:
        if len(p) >= 6 and p[1] == base:
            out.update(decode_supported(base, p[2:6]))
    return out


def _walk_pages(transport: Transport, mode: int) -> set[str]:
    """Supported-PID bitmaps for Mode 01 (`01xx`) or Mode 02 (`02xx00`), page by page."""
    sid, off = 0x40 + mode, (2 if mode == 0x01 else 3)
    found: set[str] = set()
    base = 0x00
    while base <= 0xE0:
        cmd = f"{mode:02X}{base:02X}" + ("00" if mode == 0x02 else "")
        pids: set[str] = set()
        for p in parse_all(transport.send(cmd), sid):
            if len(p) >= off + 4 and p[1] == base:
                pids.update(decode_supported(base, p[off : off + 4]))
        if not pids:
            break
        found |= pids
        if f"{base + 0x20:02X}" not in pids:  # no ECU advertises another page
            break
        base += 0x20
    return found


def _freeze_frame(transport: Transport) -> FreezeFrame | None:
    """Mode 02 frame 0: the DTC that triggered it, then every decodable supported PID."""
    dtc_payloads = [p for p in parse_all(transport.send("020200"), 0x42)
                    if len(p) >= 5 and p[1] == 0x02 and p[2] == 0x00]
    # The ECU that has a frame is the one reporting a non-zero DTC (another ECU may answer first with 0000).
    idx = next((i for i, p in enumerate(dtc_payloads) if p[3] or p[4]), None)
    if idx is None:
        return None
    hi, lo = dtc_payloads[idx][3], dtc_payloads[idx][4]
    values: dict[str, PidValue] = {}
    for pid in sorted(_walk_pages(transport, 0x02)):
        if pid not in PIDS:
            continue
        got = [p for p in parse_all(transport.send(f"02{pid}00"), 0x42)
               if len(p) >= 3 + PIDS[pid].nbytes and p[1] == int(pid, 16) and p[2] == 0x00]
        # Headers are off, so an ECU is known only by its position in the reply list. Use the same
        # position as the DTC's ECU, and only when every ECU answered; otherwise skip rather than mix ECUs.
        if len(got) == len(dtc_payloads):
            v = decode_pid(pid, got[idx][3:])
            if v is not None:
                values[pid] = v
    return FreezeFrame(dtc=decode_dtc(hi, lo), pids=values)


def scan(
    transport: Transport,
    *,
    snapshot_id: str,
    captured_at: datetime | None = None,
    kind: str = "replay",
    protocol: str | None = None,
    transcript: str | None = None,
    symptoms: str = "",
) -> Snapshot:
    warnings: list[str] = []
    init_adapter(transport, protocol)
    adapter = identify(transport)
    supported: dict[str, list[str]] = {}
    pids01 = _walk_pages(transport, 0x01)
    if pids01:
        supported["01"] = sorted(pids01)
    else:
        warnings.append("Mode 01: no response to the supported-PID request (no data or unable to connect)")

    # Ask for the protocol only after a request has run: under ATSP0 (automatic
    # search) ATDP answers just "AUTO" until the adapter has found the bus.
    dp = _first(transport.send("ATDP"))
    proto = Protocol(
        name=dp.removeprefix("AUTO, ") if dp else None,
        atsp=protocol,
        pinned=protocol not in (None, "0"),  # ATSP0 = automatic search, not a pin
    )

    # DTC and VIN replies use a different layout on non-CAN buses (no count byte;
    # multi-line VIN). Decoding them as CAN would give wrong codes, so skip until
    # Phase 4 adds the non-CAN layouts.
    is_can = "15765" in (proto.name or "")
    ecus: list[Ecu] = []
    if is_can:
        ecus = _discover_ecus(transport)
        if not ecus:
            warnings.append("ECU attribution unavailable (no CAN ids in the headers-on reply)")
    vin, vin_source = None, "none"
    dtcs = Dtcs()
    if is_can:
        pids09 = _supported(parse_all(transport.send("0900"), 0x49), 0x00)
        if pids09:
            supported["09"] = sorted(pids09)
        if "02" in pids09:
            candidates = [p[3:20].decode("ascii", errors="replace") for p in parse_all(transport.send("0902"), 0x49)]
            valid = [c for c in dict.fromkeys(candidates) if VIN_RE.fullmatch(c)]
            if valid:
                vin, vin_source = valid[0], "obd"
                if len(valid) > 1:
                    warnings.append(f"ECUs disagree on the VIN: {valid}; using the first")
            else:
                warnings.append(f"Mode 09 returned an invalid VIN: {candidates[0] if candidates else ''!r}")
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
    status = [p for p in parse_all(transport.send("0101"), 0x41) if len(p) >= 3 and p[1] == 0x01]
    if status:  # the lamp is on if any ECU commands it; each ECU counts its own codes
        mil = Mil(on=any(p[2] & 0x80 for p in status), dtc_count=sum(p[2] & 0x7F for p in status))
    ignition, monitors = parse_readiness(status)
    freeze_frame = _freeze_frame(transport) if dtcs.stored else None

    return Snapshot(
        snapshot_id=snapshot_id,
        captured_at=captured_at or datetime.now(timezone.utc),
        source=Source(kind=kind, adapter=adapter, tool_version=__version__, transcript=transcript),
        vehicle=Vehicle(vin=vin, vin_source=vin_source),
        protocol=proto,
        ecus=ecus,
        supported_pids=supported,
        dtcs=dtcs,
        mil=mil,
        freeze_frame=freeze_frame,
        readiness=monitors,
        ignition_type=ignition,
        user_context=UserContext(symptoms=symptoms),
        warnings=warnings,
    )
