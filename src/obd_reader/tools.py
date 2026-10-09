"""Tool functions shared by every front end. Offline tools read saved snapshots;
live tools are the only ones that open the adapter, always through a Session."""
import math
import re
from collections import Counter
from pathlib import Path
from typing import Callable

from obd_reader.adapter import identify
from obd_reader.capture import capture
from obd_reader.console import ConsoleService
from obd_reader.elm import is_legacy, parse_all
from obd_reader.live import downsample, sample, summarize, validate_pids
from obd_reader.mode06 import read_all, read_all_legacy
from obd_reader.pids import PIDS, decode_pid, pid_name
from obd_reader.scenarios import load_scenarios
from obd_reader.session import Session
from obd_reader.snapshot import Snapshot

OFFLINE_TOOLS = frozenset({
    "list_snapshots", "get_snapshot", "import_snapshot", "read_dtcs", "freeze_frame",
    "readiness", "vehicle_info", "list_supported_pids", "compare_snapshots",
})
LIVE_TOOLS = frozenset({"adapter_info", "scan", "read_pid", "live_data", "trim_summary", "mode06_tests",
                        "open_console", "console_data"})
TOOL_NAMES = OFFLINE_TOOLS | LIVE_TOOLS

_MID_RE = re.compile(r"[0-9A-Fa-f]{2}")
_LABEL_RE = re.compile(r"[a-z0-9-]{1,40}")
_PROTO_RE = re.compile(r"[0-9]")  # 0 = automatic, 1-9 = a fixed protocol; A-C (J1939, user CAN) are refused


class NoSnapshotError(LookupError):
    """No snapshot has been saved yet."""


def _dump(model) -> dict:
    return model.model_dump(mode="json")


def build_tools(session: Session) -> dict[str, Callable]:
    store = session.store

    def latest_or(snapshot_id: str | None) -> Snapshot:
        if snapshot_id is not None:
            return store.load(snapshot_id)
        rows = store.list()
        if not rows:
            raise NoSnapshotError("no snapshots saved yet; run `scan` first or import one")
        return store.load(rows[-1]["snapshot_id"])

    # ---- offline tools: read saved snapshots, never touch the adapter --------------------------

    def list_snapshots() -> dict:
        """List saved vehicle snapshots, oldest first."""
        return {"snapshots": store.list()}

    def get_snapshot(snapshot_id: str | None = None) -> dict:
        """Return a saved snapshot (the newest if no id is given)."""
        return _dump(latest_or(snapshot_id))

    def import_snapshot(path: str) -> dict:
        """Import a snapshot JSON file that already sits inside the data directory."""
        snap = store.import_file(Path(path))
        return {"snapshot_id": snap.snapshot_id}

    def read_dtcs(snapshot_id: str | None = None, kind: str = "stored") -> dict:
        """Diagnostic trouble codes from a snapshot: kind is stored, pending, permanent or all."""
        if kind not in ("stored", "pending", "permanent", "all"):
            raise ValueError("kind must be stored, pending, permanent or all")
        s = latest_or(snapshot_id)
        kinds = ("stored", "pending", "permanent") if kind == "all" else (kind,)
        dtcs = [{**_dump(d), "kind": k} for k in kinds for d in getattr(s.dtcs, k)]
        return {"snapshot_id": s.snapshot_id, "kind": kind, "dtcs": dtcs, "mil": _dump(s.mil),
                "unanswered": [k for k in kinds if k in s.dtcs.unanswered]}  # no answer: unknown, not "no codes"

    def freeze_frame(snapshot_id: str | None = None) -> dict:
        """The freeze frame stored with the first DTC, if the snapshot has one."""
        s = latest_or(snapshot_id)
        return {"snapshot_id": s.snapshot_id, "freeze_frame": _dump(s.freeze_frame) if s.freeze_frame else None}

    def readiness(snapshot_id: str | None = None) -> dict:
        """Emissions readiness monitors: which are supported and which are not yet complete."""
        s = latest_or(snapshot_id)
        return {
            "snapshot_id": s.snapshot_id,
            "ignition_type": s.ignition_type,
            "monitors": {n: _dump(m) for n, m in s.readiness.items() if m.supported},
            "incomplete": [n for n, m in s.readiness.items() if m.supported and m.complete is False],
            "not_supported": [n for n, m in s.readiness.items() if not m.supported],
        }

    def vehicle_info(snapshot_id: str | None = None) -> dict:
        """VIN, protocol, adapter (incl. battery voltage), ECUs, Mode 09 items and CAL ID / CVN / ECU name from a snapshot,
        plus how many scan requests got each reply class and how many advertised PIDs have no decoder."""
        s = latest_or(snapshot_id)
        return {
            "snapshot_id": s.snapshot_id,
            "vin": s.vehicle.vin,
            "vin_source": s.vehicle.vin_source,
            "decoded": _dump(s.vehicle.decoded) if s.vehicle.decoded else None,
            "protocol": s.protocol.name,
            "adapter": _dump(s.source.adapter),
            "ecus": [_dump(e) for e in s.ecus],
            "supported_mode09_pids": s.supported_pids.get("09", []),
            "mode09": _dump(s.mode09),
            "user_context": _dump(s.user_context),
            "reply_counts": dict(Counter(r.reply for r in s.replies)),
            "undecoded_count": len(s.undecoded),
            "warnings": s.warnings,
        }

    def list_supported_pids(snapshot_id: str | None = None) -> dict:
        """Mode 01 PIDs the car supports, with names for the ones we can decode."""
        s = latest_or(snapshot_id)
        return {
            "snapshot_id": s.snapshot_id,
            "mode01": [
                {"pid": p, "name": pid_name(p), "unit": PIDS[p].unit if p in PIDS else None,
                 "decodable": p in PIDS}
                for p in s.supported_pids.get("01", [])
            ],
        }

    def compare_snapshots(a: str, b: str) -> dict:
        """Differences between two snapshots: DTCs, MIL, protocol, supported PIDs, readiness."""
        sa, sb = store.load(a), store.load(b)

        def codes(s):
            return {d.code for k in ("stored", "pending", "permanent") for d in getattr(s.dtcs, k)}

        pa, pb = set(sa.supported_pids.get("01", [])), set(sb.supported_pids.get("01", []))
        return {
            "a": a, "b": b,
            "dtcs": {"only_in_a": sorted(codes(sa) - codes(sb)), "only_in_b": sorted(codes(sb) - codes(sa))},
            "mil": {"a": sa.mil.on, "b": sb.mil.on},
            "protocol": {"a": sa.protocol.name, "b": sb.protocol.name},
            "supported_pids": {"only_in_a": sorted(pa - pb), "only_in_b": sorted(pb - pa)},
            "incomplete_monitors": {
                "a": sorted(n for n, m in sa.readiness.items() if m.complete is False),
                "b": sorted(n for n, m in sb.readiness.items() if m.complete is False),
            },
        }

    # ---- live tools: the only ones that open the adapter ---------------------------------------

    def _series_out(ls) -> dict:
        return {p: {"name": s.name, "unit": s.unit, "stats": summarize(s),
                    "samples": downsample(s.samples)} for p, s in ls.series.items()}

    def adapter_info() -> dict:
        """Identify the connected adapter (chip, firmware, device id) and read its supply voltage."""
        with session.connection("adapter-info") as t:
            a = identify(t)
            device = (t.send("STDI") or [None])[0]
            volts = (t.send("ATRV") or [None])[0]
        return {"ati": a.ati, "sti": a.sti, "chip": a.chip, "genuine_stn": a.genuine_stn,
                "device": device, "supply_voltage": volts}

    def scan(label: str = "scan", protocol: str = "0", symptoms: str = "") -> dict:
        """Run a full read-only scan of the car and save a snapshot. protocol is 0 (auto) or an ATSP digit 1-9."""
        if not _LABEL_RE.fullmatch(label):
            raise ValueError("label must be 1-40 chars of [a-z0-9-]")
        if not _PROTO_RE.fullmatch(protocol):
            raise ValueError("protocol must be one digit 0-9")
        with session.raw_port() as port:  # same lock as every live tool; capture records its own transcript
            snap, _s_path, _t_path = capture(
                port, session.config.home, label=label, protocol=protocol,
                timeout=session.config.timeout, symptoms=symptoms,
            )
        return {"snapshot_id": snap.snapshot_id, "vin": snap.vehicle.vin, "protocol": snap.protocol.name,
                "stored_dtcs": [d.code for d in snap.dtcs.stored], "mil": _dump(snap.mil),
                "ecus": [e.header for e in snap.ecus], "warnings": snap.warnings}

    def read_pid(pid: str) -> dict:
        """Read one Mode 01 PID once (the PID must be in the decoder table)."""
        pid = validate_pids([pid])[0]
        with session.connection("read-pid") as t:
            payloads = parse_all(t.send(f"01{pid}"), 0x41)
        for p in payloads:
            if len(p) >= 3 and p[1] == int(pid, 16):
                v = decode_pid(pid, p[2:])
                if v is not None:
                    return {"pid": pid, "name": v.name, "value": v.value, "unit": v.unit, "raw": v.raw}
        return {"pid": pid, "name": PIDS[pid].name, "value": None, "unit": PIDS[pid].unit,
                "note": "no data: the ECU did not answer this PID"}

    def live_data(pids: list[str], seconds: float = 10, hz: float = 2, conditions: str = "") -> dict:
        """Poll up to 8 Mode 01 PIDs for up to 120 s at up to 10 Hz; returns stats plus a downsampled series."""
        validate_pids(pids)
        with session.connection("live") as t:
            ls = sample(t, pids, seconds, hz=hz, clock=session.clock, sleep=session.sleep)
        out = {"duration_s": ls.duration_s, "hz": ls.rate_hz, "conditions": conditions,
               "series": _series_out(ls)}
        if not any(s.samples for s in ls.series.values()):
            out["note"] = "no data: the ECU did not answer any of these PIDs (car off or not connected?)"
        return out

    def trim_summary(seconds: float = 15, hz: float = 2) -> dict:
        """Fuel-trim statistics (short and long term, both banks) over a short sample."""
        with session.connection("trims") as t:
            ls = sample(t, ["06", "07", "08", "09"], seconds, hz=hz, clock=session.clock, sleep=session.sleep)
        notes = {p: "no data: the ECU did not answer this PID" for p, s in ls.series.items() if not s.samples}
        return {"duration_s": ls.duration_s, "hz": ls.rate_hz, "series": _series_out(ls), "notes": notes}

    def mode06_tests(mid: str | None = None) -> dict:
        """Read Mode 06 on-board test results (raw values, no unit scaling). mid is a 2-digit hex monitor id, or omit for all supported."""
        if mid is not None and not _MID_RE.fullmatch(mid):
            raise ValueError("mid must be 2 hex digits")
        with session.connection("mode06") as t:
            t.send("0100")  # the adapter names the bus only after a request has found it
            if is_legacy((t.send("ATDP") or [""])[0]):
                tids, lres = read_all_legacy(t, None if mid is None else [mid.upper()])
                return {"layout": "legacy", "supported_tids": list(tids), "results": [r.model_dump() for r in lres],
                        "note": "legacy-bus layout (J1850, ISO 9141, KWP): one value against one limit per row; "
                                "limit_type comes from bit 7 of the component id per J1979 [general knowledge, unverified]; "
                                "what each TID and component means is manufacturer-specific; rows are not judged pass/fail. "
                                "Layout seen on one J1850 VPW GMC truck only."}
            mids, res = read_all(t, None if mid is None else [mid.upper()])
            results = [r.model_dump() for r in res]
        return {"supported_mids": list(mids), "results": results,
                "note": "values are raw integers with no unit scaling; layout verified on one 2024 Ridgeline only."}

    # ---- live console: one shared sampler, viewed by a web page and by Claude ---------------------

    consoles: dict[str, ConsoleService | None] = {"real": None, "demo": None}
    recent_first: list[str] = []  # console kinds, most recently opened first

    def _service(demo: bool) -> ConsoleService:
        key = "demo" if demo else "real"
        if consoles[key] is None:
            consoles[key] = ConsoleService(session, demo=demo)
        return consoles[key]

    def open_console(demo: bool = False, start: bool = True, scenarios_file: str | None = None) -> dict:
        """Start the live console web page (local, token-protected, read-only) and return its URL. demo=True uses a simulated car.
        scenarios_file: a scenarios JSON file (as for `console --scenarios`) whose scenarios the page offers; an open page shows them after a reload."""
        scen = None
        if scenarios_file:
            try:
                scen = load_scenarios(Path(scenarios_file))
            except (OSError, ValueError) as exc:
                raise ValueError(f"scenarios_file {scenarios_file}: {exc}") from None
        service = _service(bool(demo))
        server = service.ensure()
        if scen is not None:
            server.scenarios = scen
        key = "demo" if demo else "real"
        if key in recent_first:
            recent_first.remove(key)
        recent_first.insert(0, key)
        if start:
            service.start_sampling()
        return {"url": server.url, "status": service.hub.state()["status"], "demo": bool(demo)}

    def console_data(seconds: float = 30) -> dict:
        """Latest values and exact statistics over the last N seconds from the console's sampler (what the page shows). The "source" field says whether the numbers are live from the car or a replay of a saved run; check it before drawing conclusions about the car."""
        if not (isinstance(seconds, (int, float)) and math.isfinite(seconds) and 0 < seconds <= 600):
            raise ValueError("seconds must be in (0, 600]")
        service = next((consoles[k] for k in recent_first if consoles[k] is not None and consoles[k].hub is not None), None)
        if service is None:
            return {"status": "idle", "message": "the console is not open; call open_console first", "channels": {}}
        st = service.hub.state()
        rp = st.get("replay")
        return {"status": st["status"], "message": st["message"], "seq": st["seq"],
                "source": "replay" if rp else "live", **({"replay": rp["name"]} if rp else {}),
                "readiness": st["readiness"], "freeze_frame": st["freeze_frame"], "channels": service.hub.recent(seconds)}

    return {f.__name__: f for f in (
        list_snapshots, get_snapshot, import_snapshot, read_dtcs, freeze_frame,
        readiness, vehicle_info, list_supported_pids, compare_snapshots,
        adapter_info, scan, read_pid, live_data, trim_summary, mode06_tests,
        open_console, console_data,
    )}
