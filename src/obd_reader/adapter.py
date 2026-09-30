"""Adapter bring-up and identification, shared by the scanner and the live tools."""
from obd_reader.snapshot import Adapter
from obd_reader.transport import Transport

INIT = ("ATZ", "ATE0", "ATL0", "ATH0")


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
