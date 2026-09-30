"""Mode 06 (on-board monitoring test results) over CAN.

Layout used here (J1979 description, NOT yet verified on hardware): `46 MID` then
repeated 8-byte groups `TID UASID VAL_H VAL_L MIN_H MIN_L MAX_H MAX_L`. Values are
raw integers: the UASID unit/scaling table is not applied.
"""
from pydantic import BaseModel

from obd_reader.elm import decode_supported


class Mode06Result(BaseModel):
    mid: str
    tid: str
    uasid: str
    value: int
    minimum: int
    maximum: int
    within_limits: bool | None


def supported_mids(payloads: list[bytes], base: int) -> set[str]:
    out: set[str] = set()
    for p in payloads:
        if len(p) >= 6 and p[0] == 0x46 and p[1] == base:
            out.update(decode_supported(base, p[2:6]))
    return out


def parse_results(payload: bytes) -> list[Mode06Result]:
    if len(payload) < 2 or payload[0] != 0x46:
        return []
    mid, body = f"{payload[1]:02X}", payload[2:]
    out = []
    for i in range(0, len(body) - 7, 8):
        g = body[i : i + 8]
        value, lo, hi = (int.from_bytes(g[a : a + 2], "big") for a in (2, 4, 6))
        out.append(Mode06Result(
            mid=mid, tid=f"{g[0]:02X}", uasid=f"{g[1]:02X}", value=value, minimum=lo, maximum=hi,
            within_limits=(lo <= value <= hi) if lo <= hi else None,
        ))
    return out
