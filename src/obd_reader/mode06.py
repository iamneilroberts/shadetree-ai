"""Mode 06 (on-board monitoring test results) over CAN, and the older layout on J1850, ISO 9141 and KWP.

Layout (verified on a 2024 Ridgeline, 2026-09-30): `46` then repeated 9-byte groups
`MID TID UASID VAL_H VAL_L MIN_H MIN_L MAX_H MAX_L`, so one reply can carry several tests
and the MID repeats in each group. Values are raw integers: the UASID unit/scaling table
is not applied.

Legacy layout (seen on a J1850 VPW GMC truck, 2026-10-04): the support bitmap `0600` answers
`46 00 FF <4 bitmap bytes> `, one filler byte before the bitmap (every TID it lists answered, none of the
others did). Each result is one line `46 TID CID VAL_H VAL_L LIM_H LIM_L`: one value against one limit.
Per SAE J1979 (non-CAN), bit 7 of CID says whether the limit is a maximum (0) or a minimum (1); that is
general knowledge, unverified on this truck, so legacy results are never judged pass or fail here. What
each TID and component id means is set by the manufacturer.
"""
from typing import Callable, Literal

from pydantic import BaseModel

from obd_reader.elm import decode_supported, parse_all


class Mode06Result(BaseModel):
    mid: str
    tid: str
    uasid: str
    value: int
    minimum: int
    maximum: int
    within_limits: bool | None


class LegacyTestResult(BaseModel):
    tid: str
    component: str  # CID with bit 7 (the limit type) cleared
    value: int
    limit: int
    limit_type: Literal["min", "max"]  # from CID bit 7 per J1979, unverified


def supported_mids(payloads: list[bytes], base: int, off: int = 2) -> set[str]:
    """`off` is where the 4 bitmap bytes start: 2 on CAN, 3 on a legacy bus (a filler byte comes first)."""
    out: set[str] = set()
    for p in payloads:
        if len(p) >= off + 4 and p[0] == 0x46 and p[1] == base:
            out.update(decode_supported(base, p[off:off + 4]))
    return out


def parse_legacy(payload: bytes) -> LegacyTestResult | None:
    if len(payload) < 7 or payload[0] != 0x46:
        return None
    cid = payload[2]
    return LegacyTestResult(tid=f"{payload[1]:02X}", component=f"{cid & 0x7F:02X}",
                            value=int.from_bytes(payload[3:5], "big"), limit=int.from_bytes(payload[5:7], "big"),
                            limit_type="min" if cid & 0x80 else "max")


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


def walk_ids(transport, off: int = 2, stop: Callable[[], bool] = lambda: False) -> list[str]:
    """Every supported MID (CAN) or TID (legacy, off=3), from the 0600/0620/... bitmaps; the bitmap pages
    themselves (20, 40, ...) are not tests and are left out."""
    found_all: set[str] = set()
    base = 0x00
    while base <= 0xE0 and not stop():
        found = supported_mids(parse_all(transport.send(f"06{base:02X}"), 0x46), base, off)
        if not found:
            break
        found_all |= found
        if f"{base + 0x20:02X}" not in found:
            break
        base += 0x20
    return sorted(m for m in found_all if int(m, 16) % 0x20 != 0)


def read_all_legacy(transport, tids: list[str] | None = None,
                    stop: Callable[[], bool] = lambda: False) -> tuple[list[str], list[LegacyTestResult]]:
    """Legacy-bus Mode 06: discover the supported TIDs (or use `tids`) and read each one."""
    tids = (walk_ids(transport, 3, stop) if tids is None else tids)[:MAX_MIDS]
    results: list[LegacyTestResult] = []
    for tid in tids:
        if stop():
            break
        for payload in parse_all(transport.send(f"06{tid}"), 0x46):
            r = parse_legacy(payload)
            if r is not None and r.tid == tid:
                results.append(r)
    return tids, results


def read_all(transport, mids: list[str] | None = None, stop: Callable[[], bool] = lambda: False) -> tuple[list[str], list[Mode06Result]]:
    """Discover the supported MIDs (or use `mids`) and read each one. The support-bitmap pages
    (MID 20, 40, ...) are not tests and are never requested as results."""
    if mids is None:
        mids = walk_ids(transport, 2, stop)
    mids = mids[:MAX_MIDS]
    results: list[Mode06Result] = []
    for m in mids:
        if stop():
            break
        for payload in parse_all(transport.send(f"06{m}"), 0x46):
            results += parse_results(payload)
    return mids, results
