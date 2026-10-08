"""ELM/STN response parsing for headers-off (ATH0) output (parse_frames: headers on), spaces on (ATS1 default)."""
import re

ERROR_MARKERS = (
    "NO DATA", "UNABLE TO CONNECT", "CAN ERROR", "BUS BUSY",
    "BUFFER FULL", "STOPPED", "ERROR", "?",
)
_HEX_LINE = re.compile(r"(?:[0-9A-F]{2} ?)+")
_LEN_LINE = re.compile(r"[0-9A-F]{3}")
_FRAME_LINE = re.compile(r"[0-9A-F]+: ((?:[0-9A-F]{2} ?)+)")


def _clean(lines: list[str]) -> list[str]:
    lines = [ln.strip().upper() for ln in lines if ln.strip()]
    # progress chatter, not errors: "SEARCHING...", K-line "BUS INIT: ...OK"
    return [ln for ln in lines if not ln.startswith("SEARCHING")
            and not (ln.startswith("BUS INIT") and ln.endswith("OK"))]


def parse_all(lines: list[str], sid: int) -> list[bytes]:
    """One payload (starting at the response SID) per responding ECU.

    Handles single-frame lines and ISO-TP multi-frame blocks ("014", "0: ...").
    Returns [] for errors, negative responses, and garbled or truncated data.
    """
    lines = _clean(lines)
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


def parse_frames(lines: list[str], sid: int) -> list[tuple[str, bytes]]:
    """The headers-on (ATH1) counterpart of parse_all: (source address, payload) per responding ECU.

    CAN 11-bit "7E8 06 41 0C 1A F8", 29-bit "18 DA F1 10 06 41 0C 1A F8": the id ("7E8", "18DAF110"), the ISO-TP PCI
    byte, then data; bytes past a single frame's length are padding. First and consecutive frames are joined per id,
    so interleaved ECUs stay apart, and a frame out of sequence drops that ECU's message. Legacy (J1850, ISO 9141,
    KWP) "48 6B 10 41 0C 1A F8 <check byte>": priority, target, source ("10"), then the message; the trailing check
    byte is kept (decoders read fixed lengths). Errors give [] as in parse_all; a line that fits no layout is skipped.
    Unverified on hardware for Mode 01."""
    lines = _clean(lines)
    if not lines or any(m in ln for ln in lines for m in ERROR_MARKERS):
        return []
    out: list[tuple[str, bytes]] = []
    pend: dict[str, list] = {}  # id -> [total length, data so far, next sequence number]
    for ln in lines:
        toks = ln.split()
        if not all(re.fullmatch(r"[0-9A-F]{2,3}", t) for t in toks) or any(len(t) == 3 for t in toks[1:]):
            continue
        if len(toks[0]) == 3 or toks[:3] == ["18", "DA", "F1"]:  # CAN
            k = 1 if len(toks[0]) == 3 else 4
            addr, data = "".join(toks[:k]), bytes.fromhex("".join(toks[k:]))
            if not data:
                continue
            kind, low = data[0] >> 4, data[0] & 0xF
            if kind == 0 and 0 < low < len(data):
                msg = data[1 : 1 + low]
            elif kind == 1 and len(data) >= 2:
                pend[addr] = [(low << 8) | data[1], data[2:], 1]
                continue
            elif kind == 2 and addr in pend and pend[addr][2] == low:
                p = pend[addr]
                p[1], p[2] = p[1] + data[1:], (p[2] + 1) & 0xF
                if len(p[1]) < p[0]:
                    continue
                msg = pend.pop(addr)[1][: p[0]]
            else:
                pend.pop(addr, None)
                continue
        elif len(toks) >= 4 and len(toks[0]) == 2:  # legacy: 3 header bytes
            addr, msg = toks[2], bytes.fromhex("".join(toks[3:]))
        else:
            continue
        if msg[:1] == bytes([sid]):
            out.append((addr, msg))
    return out


def classify(lines: list[str], sid: int) -> str:
    """Why a reply is or is not usable for a request whose response SID is `sid`:
    "ok" (parse_all finds a payload), "no_data", "nrc:<code>" (7F negative response, first
    ECU's code), "wrong_sid" (well-formed, but not an answer to this request), "adapter_error"
    ("?", bus errors, or nothing printed at all) or "garbled"."""
    if parse_all(lines, sid):
        return "ok"
    lines = _clean(lines)
    if not lines:
        return "adapter_error"
    if all(ln == "NO DATA" for ln in lines):
        return "no_data"
    if any(m in ln for ln in lines for m in ERROR_MARKERS):
        return "adapter_error"
    frames = [ln.split() for ln in lines if _HEX_LINE.fullmatch(ln)]
    for t in frames:
        if t[0] == "7F" and t[1:2] == [f"{sid - 0x40:02X}"]:
            return f"nrc:{t[2]}" if len(t) >= 3 else "garbled"
    return "wrong_sid" if frames else "garbled"


def parse_response(lines: list[str], sid: int) -> bytes | None:
    """First responder's payload, or None if unsupported/garbled."""
    payloads = parse_all(lines, sid)
    return payloads[0] if payloads else None


_HEADER_RE = re.compile(r"[0-9A-F]{3}|[0-9A-F]{8}")  # CAN 11-bit id, or 29-bit id as 4 bytes


def parse_headers(lines: list[str]) -> list[str]:
    """ECU CAN ids from a headers-on (ATH1) reply to "0100", first-seen order.

    A CAN line looks like "<id bytes> <PCI length> 41 00 ..."; everything before
    the PCI byte is the id. Header format is unverified on real hardware for
    29-bit ids; anything that does not fit yields no header instead of a guess.
    """
    out: list[str] = []
    for ln in lines:
        toks = ln.strip().upper().split()
        for p in range(2, len(toks) - 1):
            if toks[p] == "41" and toks[p + 1] == "00":
                head = "".join(toks[: p - 1])
                if _HEADER_RE.fullmatch(head) and head not in out:
                    out.append(head)
                break
    return out


def decode_dtc(b1: int, b2: int) -> str:
    letter = "PCBU"[b1 >> 6]
    return f"{letter}{(b1 >> 4) & 0x3}{b1 & 0xF:X}{b2:02X}"


def is_legacy(protocol_name: str | None) -> bool:
    """True for the pre-CAN buses an ELM/STN adapter names in ATDP: J1850 PWM/VPW, ISO 9141-2, ISO 14230 (KWP2000)."""
    n = (protocol_name or "").upper()
    return "J1850" in n or "9141" in n or "14230" in n


def decode_dtc_list(payload: bytes, legacy: bool = False) -> list[str]:
    """CAN layout: SID, count, then 2-byte DTCs (zero pairs are padding).
    Legacy layout (J1850, ISO 9141, KWP): SID, then three 2-byte DTCs, no count byte; zero pairs are padding."""
    if len(payload) < 2:
        return []
    pairs = payload[1:7] if legacy else payload[2 : 2 + 2 * payload[1]]
    out = []
    for i in range(0, len(pairs) - 1, 2):
        if pairs[i] == 0 and pairs[i + 1] == 0:
            continue
        out.append(decode_dtc(pairs[i], pairs[i + 1]))
    return out


def decode_supported(base_pid: int, data: bytes) -> list[str]:
    mask = int.from_bytes(data[:4].ljust(4, b"\x00"), "big")
    return [f"{base_pid + i + 1:02X}" for i in range(32) if mask & (0x80000000 >> i)]


def parse_vin_legacy(lines: list[str]) -> list[str]:
    """VIN candidates from a legacy-bus (J1850, ISO 9141, KWP) 0902 reply, one per answering ECU.

    Each line is `49 02 <n> <4 data bytes>`; line 1 starts with three zero pad bytes, so five lines carry the
    17 characters. A line numbered 1 starts a new ECU's message. A message that is not 17 printable ASCII
    characters is dropped rather than repaired."""
    msgs: list[dict[int, bytes]] = []
    for p in parse_all(lines, 0x49):
        if len(p) < 7 or p[1] != 0x02:
            continue
        if p[2] == 1 or not msgs:
            msgs.append({})
        msgs[-1][p[2]] = p[3:7]
    out: list[str] = []
    for m in msgs:
        data = b"".join(m[k] for k in sorted(m)).lstrip(b"\x00")
        if len(data) == 17 and all(32 <= b < 127 for b in data):
            out.append(data.decode("ascii"))
    return out


def parse_headers_legacy(lines: list[str]) -> list[str]:
    """ECU source addresses from a headers-on (ATH1) reply to "0100" on a legacy bus, first-seen order.

    A J1850 line looks like "<priority> <target> <source> 41 00 <4 bytes> [<crc>]"; the source byte names the
    ECU (10 engine, 18 transmission, ...). Anything that does not fit yields no header instead of a guess.
    Unverified on hardware."""
    out: list[str] = []
    for ln in lines:
        toks = ln.strip().upper().split()
        if len(toks) >= 9 and toks[3:5] == ["41", "00"] and all(re.fullmatch(r"[0-9A-F]{2}", t) for t in toks[:3]):
            if toks[2] not in out:
                out.append(toks[2])
    return out
