"""ELM/STN response parsing for headers-off (ATH0) output, spaces on (ATS1 default)."""
import re

ERROR_MARKERS = (
    "NO DATA", "UNABLE TO CONNECT", "CAN ERROR", "BUS BUSY",
    "BUFFER FULL", "STOPPED", "ERROR", "?",
)
_HEX_LINE = re.compile(r"(?:[0-9A-F]{2} ?)+")
_LEN_LINE = re.compile(r"[0-9A-F]{3}")
_FRAME_LINE = re.compile(r"[0-9A-F]+: ((?:[0-9A-F]{2} ?)+)")


def parse_response(lines: list[str], sid: int) -> bytes | None:
    """Payload starting at the response SID, or None if unsupported/garbled."""
    lines = [ln.strip().upper() for ln in lines if ln.strip()]
    # progress chatter, not errors: "SEARCHING...", K-line "BUS INIT: ...OK"
    lines = [ln for ln in lines if not ln.startswith("SEARCHING")
             and not (ln.startswith("BUS INIT") and ln.endswith("OK"))]
    if not lines or any(m in ln for ln in lines for m in ERROR_MARKERS):
        return None

    if _LEN_LINE.fullmatch(lines[0]) and len(lines) > 1:  # ISO-TP multi-frame
        total = int(lines[0], 16)
        data = b""
        for ln in lines[1:]:
            m = _FRAME_LINE.fullmatch(ln)
            if not m:
                return None
            data += bytes.fromhex(m.group(1))
        if len(data) < total:
            return None
        payload = data[:total]
    else:  # single frame; take the first line that carries the expected SID
        payload = None
        for ln in lines:
            if _HEX_LINE.fullmatch(ln):
                candidate = bytes.fromhex(ln)
                if candidate[:1] == bytes([sid]):
                    payload = candidate
                    break
        if payload is None:
            return None

    return payload if payload[:1] == bytes([sid]) else None


def decode_dtc(b1: int, b2: int) -> str:
    letter = "PCBU"[b1 >> 6]
    return f"{letter}{(b1 >> 4) & 0x3}{b1 & 0xF:X}{b2:02X}"


def decode_dtc_list(payload: bytes) -> list[str]:
    """CAN layout: SID, count, then 2-byte DTCs (zero pairs are padding)."""
    if len(payload) < 2:
        return []
    pairs = payload[2 : 2 + 2 * payload[1]]
    out = []
    for i in range(0, len(pairs) - 1, 2):
        if pairs[i] == 0 and pairs[i + 1] == 0:
            continue
        out.append(decode_dtc(pairs[i], pairs[i + 1]))
    return out


def decode_supported(base_pid: int, data: bytes) -> list[str]:
    mask = int.from_bytes(data[:4].ljust(4, b"\x00"), "big")
    return [f"{base_pid + i + 1:02X}" for i in range(32) if mask & (0x80000000 >> i)]
