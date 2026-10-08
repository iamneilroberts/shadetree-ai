"""Adapter bring-up and identification, shared by the scanner and the live tools."""
from obd_reader.snapshot import Adapter
from obd_reader.transport import Transport

INIT = ("ATZ", "ATE0", "ATL0", "ATH0")

# Tried one by one when automatic search (ATSP0) finds nothing: CAN first (most cars after 2008), then
# J1850 VPW, J1850 PWM, ISO 9141-2 and KWP. A real J1850 VPW truck answered when pinned to 2 right after
# ATSP0 had returned UNABLE TO CONNECT.
FALLBACK_PROTOCOLS = ("6", "8", "7", "9", "2", "1", "3", "5", "4")


def init_adapter(transport: Transport, protocol: str | None) -> None:
    for cmd in INIT:
        transport.send(cmd)
    if protocol is not None:
        transport.send(f"ATSP{protocol}")


def identify(transport: Transport) -> Adapter:
    ati = (transport.send("ATI") or [None])[0]
    sti = (transport.send("STI") or [None])[0]
    genuine = bool(sti and sti.upper().startswith("STN"))
    return Adapter(
        ati=ati,
        sti=sti if genuine else None,
        chip=sti.split()[0] if genuine else None,
        genuine_stn=genuine,
    )


def fallback_search(transport, parse=None) -> str | None:
    """After automatic search found nothing: pin each protocol in turn and ask `0100`. Returns the ATSP value
    that answered (left pinned), or None with the adapter back on automatic search. `parse` reads a reply into
    its Mode 01 payloads (default elm.parse_all, headers off)."""
    from obd_reader.elm import parse_all  # local: elm has no adapter dependency, keep it that way

    parse = parse or (lambda lines: parse_all(lines, 0x41))
    for p in FALLBACK_PROTOCOLS:
        transport.send(f"ATSP{p}")
        if parse(transport.send("0100")):
            return p
    transport.send("ATSP0")
    return None
