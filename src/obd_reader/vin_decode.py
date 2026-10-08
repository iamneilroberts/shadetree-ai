"""Suggest a car's make and model year from its vehicle key, offline; optionally ask NHTSA's vPIC for the model.

Only the vehicle key is ever used: VIN positions 1-8 and 10 (see vehicle.vehicle_key). The check digit and the
serial (positions 11-17) are never read here, never sent and never cached.

Offline: the model year from position 10 and the make from the WMI (positions 1-3). The model cannot be decoded
offline: it lives in the maker's own VDS coding, which needs a database such as vPIC.

Online (only when the user asks): one HTTPS GET to vpic.nhtsa.dot.gov with a wildcard VIN built from the key
(`ABCDEFGH*P*******`). Results are cached per key in the data home, so a car is looked up once.
"""
import json
import re
import urllib.request
from datetime import date
from pathlib import Path

from obd_reader.profiles import KEY_RE
from obd_reader.vehicle import _WMI_MAKE as _HONDA_WMI, vehicle_key

# Model-year characters at VIN position 10, in order: A = 1980 or 2010 ... Y = 2000 or 2030, 1 = 2001 or 2031 ...
# The 30-year cycle and the position-7 rule (a letter at position 7 means 2010-2039, a digit 1980-2009, for North
# American passenger cars and light trucks) are [general knowledge, unverified]; makers outside North America do
# not always follow the position-7 rule, so a decoded year is a suggestion the user checks.
_YEAR_CHARS = "ABCDEFGHJKLMNPRSTVWXY123456789"
OBD2_FIRST_YEAR = 1996

# World manufacturer identifiers (VIN positions 1-3) of common US-market makes: [general knowledge, unverified].
# A WMI some makers share (e.g. Stellantis' 1C3/1C4) names the group; the user edits it or presses Look up.
# The Honda/Acura entries are vehicle.py's table, reused unchanged.
_WMI = {
    **dict.fromkeys(("JTD", "JTE", "JTK", "JTL", "JTM", "JTN", "4T1", "4T3", "4T4", "5TB", "5TD", "5TE", "5TF",
                     "2T1", "2T3", "3TM"), "Toyota"),
    **dict.fromkeys(("JTH", "JTJ", "2T2", "58A"), "Lexus"),
    **dict.fromkeys(("1G1", "1GC", "1GB", "1GN", "2G1", "2GC", "2GN", "3G1", "3GC", "3GN", "KL7", "KL8"), "Chevrolet"),
    **dict.fromkeys(("1GT", "1GK", "1GD", "2GT", "3GT", "3GK"), "GMC"),
    **dict.fromkeys(("1G4", "2G4", "5GA", "KL4"), "Buick"),
    **dict.fromkeys(("1G6", "1GY"), "Cadillac"),
    **dict.fromkeys(("1G2", "2G2", "5Y2"), "Pontiac"),
    "1G8": "Saturn",
    **dict.fromkeys(("1FA", "1FB", "1FC", "1FD", "1FM", "1FT", "2FA", "2FM", "2FT", "3FA", "3FM", "3FT", "1ZV",
                     "NM0", "WF0"), "Ford"),
    **dict.fromkeys(("1LN", "2LM", "3LN", "5LM"), "Lincoln"),
    **dict.fromkeys(("1ME", "2ME", "4M2"), "Mercury"),
    **dict.fromkeys(("1C3", "1C4", "2C3", "2C4", "3C4"), "Chrysler/Dodge/Jeep"),
    **dict.fromkeys(("1C6", "3C6", "3C7"), "Ram"),
    **dict.fromkeys(("1B3", "1B7", "1D7", "2B3", "2D4", "3D7"), "Dodge"),
    **dict.fromkeys(("1J4", "1J8"), "Jeep"),
    **dict.fromkeys(("2A4", "2A8"), "Chrysler"),
    **dict.fromkeys(("ZFA", "3C3"), "Fiat"),
    **dict.fromkeys(("1N4", "1N6", "3N1", "3N6", "5N1", "JN1", "JN8"), "Nissan"),
    **dict.fromkeys(("JNK", "JNR", "5N3"), "Infiniti"),
    **dict.fromkeys(("KMH", "KM8", "5NP", "5NM"), "Hyundai"),
    "KMT": "Genesis",
    **dict.fromkeys(("KNA", "KND", "5XX", "5XY", "3KP"), "Kia"),
    **dict.fromkeys(("JF1", "JF2", "4S3", "4S4"), "Subaru"),
    **dict.fromkeys(("JM1", "JM3", "3MZ", "4F2", "4F4"), "Mazda"),
    **dict.fromkeys(("JA3", "JA4", "4A3", "4A4", "ML3"), "Mitsubishi"),
    **dict.fromkeys(("WVW", "WVG", "1VW", "3VW", "3VV", "1V2"), "Volkswagen"),
    **dict.fromkeys(("WAU", "WA1", "WUA", "TRU"), "Audi"),
    **dict.fromkeys(("WP0", "WP1"), "Porsche"),
    **dict.fromkeys(("WBA", "WBS", "WBX", "WBY", "5UX", "4US"), "BMW"),
    "WMW": "MINI",
    **dict.fromkeys(("WDB", "WDC", "WDD", "W1K", "W1N", "4JG", "55S"), "Mercedes-Benz"),
    **dict.fromkeys(("YV1", "YV4", "7JR"), "Volvo"),
    **dict.fromkeys(("5YJ", "7SA"), "Tesla"),
    "SAJ": "Jaguar", "SAL": "Land Rover",
    **_HONDA_WMI,
}

VPIC_HOST = "vpic.nhtsa.dot.gov"
TIMEOUT_S = 8.0
CACHE_NAME = "cache/vpic.json"  # cache/ is gitignored
_PARTIAL_RE = re.compile(r"[A-HJ-NPR-Z0-9]{8}\*[A-HJ-NPR-Z0-9]\*{7}")
_FIELDS = {"Make": "make", "Model": "model", "ModelYear": "year", "Trim": "trim", "EngineCylinders": "cylinders",
           "DisplacementL": "displacement_l", "FuelTypePrimary": "fuel"}


class LookupUnavailable(RuntimeError):
    """vPIC could not be reached or gave nothing usable."""


def to_key(text: str) -> str:
    """A vehicle key from a key ('1HGCM826-3'), a wildcard partial VIN ('1HGCM826*3*******') or a full VIN, which is
    reduced to its key at once. The error never repeats the input (it may be a full VIN)."""
    t = text.strip().upper() if isinstance(text, str) else ""
    key = vehicle_key(t) if len(t) == 17 and "*" not in t else (f"{t[:8]}-{t[9]}" if _PARTIAL_RE.fullmatch(t) else t)
    if not key or not KEY_RE.fullmatch(key):
        raise ValueError("give a vehicle key such as 1HGCM826-3 (VIN characters 1-8, a dash, character 10), "
                         "a partial VIN such as 1HGCM826*3*******, or a full VIN")
    return key


def partial_vin(key: str) -> str:
    """The wildcard VIN vPIC is asked about: key characters only, '*' for the check digit and the serial."""
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        raise ValueError("not a vehicle key")
    return f"{key[:8]}*{key[9]}" + "*" * 7


def model_year(key: str, this_year: int | None = None) -> int | None:
    """The model year from key character 10 (VIN position 10), the cycle picked by VIN position 7. A year beyond next
    year falls back to the earlier cycle; one before OBD-II (1996) moves to the later cycle if that is not in the future."""
    if not isinstance(key, str) or not KEY_RE.fullmatch(key) or key[9] not in _YEAR_CHARS:
        return None
    latest = (this_year or date.today().year) + 1
    early = 1980 + _YEAR_CHARS.index(key[9])
    late = early + 30
    year = late if key[6].isalpha() else early
    if year > latest:
        year = early
    if year < OBD2_FIRST_YEAR and late <= latest:
        year = late
    return year


def make_of_wmi(wmi: str) -> str | None:
    return _WMI.get(wmi[:3].upper()) if isinstance(wmi, str) else None


def offline(key: str) -> dict:
    """{make, model, year, source}: make from the WMI (None when not listed), year from position 10, model always
    None (it cannot be decoded offline)."""
    return {"make": make_of_wmi(key[:3]), "model": None, "year": model_year(key), "source": "offline"}


def _fetch(url: str) -> bytes:
    """The one network call: HTTPS GET to the fixed vPIC host (tests replace this function)."""
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "shadetree-ai"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 (fixed https URL)
        return r.read(1_000_000)


def parse_vpic(data: bytes, key: str) -> dict:
    """The fields we keep from a DecodeVinValues reply. ErrorCode 1/4/14 are normal with wildcards; the result is
    usable if Make or Model is set."""
    try:
        row = json.loads(data)["Results"][0]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LookupUnavailable("unexpected reply") from e
    if not isinstance(row, dict):
        raise LookupUnavailable("unexpected reply")
    out = {}
    for src, dst in _FIELDS.items():
        v = row.get(src)
        out[dst] = v.strip()[:40] if isinstance(v, str) and v.strip() else None
    if not out["make"] and not out["model"]:
        raise LookupUnavailable("NHTSA did not recognise this vehicle key")
    out["year"] = int(out["year"]) if out["year"] and out["year"].isdigit() else model_year(key)
    try:
        out["displacement_l"] = f"{float(out['displacement_l']):.1f}" if out["displacement_l"] else None
    except ValueError:
        pass
    off = make_of_wmi(key[:3])
    if off and out["make"] and off.upper() == out["make"].upper():
        out["make"] = off  # 'Honda', not 'HONDA', so My runs groups it with the offline name
    return {**out, "source": "nhtsa"}


def lookup(key: str, home) -> dict:
    """vPIC's answer for this vehicle key, from the cache in `home` or one HTTPS call. Raises LookupUnavailable."""
    url = f"https://{VPIC_HOST}/api/vehicles/DecodeVinValues/{partial_vin(key)}?format=json"
    cache_path = Path(home) / CACHE_NAME
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(key)
    if isinstance(hit, dict) and hit.get("source") == "nhtsa":
        return hit
    try:
        data = _fetch(url)
    except Exception as e:  # offline, DNS, timeout, HTTP error: all mean the same to the user
        raise LookupUnavailable("could not reach NHTSA") from e
    result = parse_vpic(data, key)
    cache[key] = result
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        tmp.replace(cache_path)
    except OSError:
        pass  # a cache that cannot be written only means asking again next time
    return result
