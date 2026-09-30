"""Mode 06 (on-board monitoring test results) over CAN.

Layout (verified on a 2024 Ridgeline, 2026-09-30): `46` then repeated 9-byte groups
`MID TID UASID VAL_H VAL_L MIN_H MIN_L MAX_H MAX_L`, so one reply can carry several tests
and the MID repeats in each group. Values are raw integers: the UASID unit/scaling table
is not applied.
"""
from pydantic import BaseModel

from typing import Callable

from obd_reader.elm import decode_supported, parse_all


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
    body, out = payload[1:], []
    for i in range(0, len(body) - 8, 9):
        g = body[i : i + 9]
        value, lo, hi = (int.from_bytes(g[a : a + 2], "big") for a in (3, 5, 7))
        out.append(Mode06Result(
            mid=f"{g[0]:02X}", tid=f"{g[1]:02X}", uasid=f"{g[2]:02X}", value=value, minimum=lo, maximum=hi,
            within_limits=(lo <= value <= hi) if lo <= hi else None,
        ))
    return out


MAX_MIDS = 40


def read_all(transport, mids: list[str] | None = None, stop: Callable[[], bool] = lambda: False) -> tuple[list[str], list[Mode06Result]]:
    """Discover the supported MIDs (or use `mids`) and read each one. The support-bitmap pages
    (MID 20, 40, ...) are not tests and are never requested as results."""
    if mids is None:
        found_all: set[str] = set()
        base = 0x00
        while base <= 0xE0 and not stop():
            found = supported_mids(parse_all(transport.send(f"06{base:02X}"), 0x46), base)
            if not found:
                break
            found_all |= found
            if f"{base + 0x20:02X}" not in found:
                break
            base += 0x20
        mids = sorted(m for m in found_all if int(m, 16) % 0x20 != 0)
    mids = mids[:MAX_MIDS]
    results: list[Mode06Result] = []
    for m in mids:
        if stop():
            break
        for payload in parse_all(transport.send(f"06{m}"), 0x46):
            results += parse_results(payload)
    return mids, results
