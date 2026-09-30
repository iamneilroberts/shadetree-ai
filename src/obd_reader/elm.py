"""ELM/STN response parsing for headers-off (ATH0) output, spaces on (ATS1 default)."""
import re

ERROR_MARKERS = (
    "NO DATA", "UNABLE TO CONNECT", "CAN ERROR", "BUS BUSY",
    "BUFFER FULL", "STOPPED", "ERROR", "?",
)
_HEX_LINE = re.compile(r"(?:[0-9A-F]{2} ?)+")
_LEN_LINE = re.compile(r"[0-9A-F]{3}")
_FRAME_LINE = re.compile(r"[0-9A-F]+: ((?:[0-9A-F]{2} ?)+)")


def parse_all(lines: list[str], sid: int) -> list[bytes]:
    """One payload (starting at the response SID) per responding ECU.

    Handles single-frame lines and ISO-TP multi-frame blocks ("014", "0: ...").
    Returns [] for errors, negative responses, and garbled or truncated data.
    """
    lines = [ln.strip().upper() for ln in lines if ln.strip()]
    # progress chatter, not errors: "SEARCHING...", K-line "BUS INIT: ...OK"
    lines = [ln for ln in lines if not ln.startswith("SEARCHING")
             and not (ln.startswith("BUS INIT") and ln.endswith("OK"))]
    if not lines or any(m in ln for ln in lines for m in ERROR_MARKERS):
        return []

    out: list[bytes] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _LEN_LINE.fullmatch(ln):  # ISO-TP multi-frame block
            total, data = int(ln, 16), b""
            i += 1
            while i < len(lines) and (m := _FRAME_LINE.fullmatch(lines[i])):
                data += bytes.fromhex(m.group(1))
                i += 1
            if total > 0 and len(data) >= total and data[:1] == bytes([sid]):
                out.append(data[:total])
            continue
        if _HEX_LINE.fullmatch(ln):  # single frame
            candidate = bytes.fromhex(ln)
            if candidate[:1] == bytes([sid]):
                out.append(candidate)
        i += 1
    return out


def parse_response(lines: list[str], sid: int) -> bytes | None:
    """First responder's payload, or None if unsupported/garbled."""
    payloads = parse_all(lines, sid)
    return payloads[0] if payloads else None


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
