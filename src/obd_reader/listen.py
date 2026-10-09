"""`shadetree-ai listen`: the standard scan, then a listen-only bus capture driven by a guided action script."""
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from obd_reader import __version__
from obd_reader.bus_capture import CaptureWriter
from obd_reader.scanner import scan
from obd_reader.session import Session
from obd_reader.transport import MonitorEvent
from obd_reader.vehicle import vehicle_key


@dataclass(frozen=True)
class Step:
    id: str
    prompt: str
    window_s: float = 10.0


REST_S = 5.0  # between steps, so each action's changes stand apart
SCRIPT = (  # engine running, in Park, parking brake on; the same list for every car so captures compare
    Step("baseline", "Idle: hands off, touch nothing", 30.0),
    Step("brake", "Press the brake pedal 3 times"),
    Step("throttle", "Blip the throttle 3 times (in Park)"),
    Step("steering", "Turn the steering wheel lock to lock"),
    Step("signal_left", "Left turn signal on, then off"),
    Step("signal_right", "Right turn signal on, then off"),
    Step("hazards", "Hazard lights on, then off"),
    Step("headlights", "Headlights on, then off"),
    Step("high_beams", "High beams on, then off"),
    Step("driver_door", "Open the driver door, then close it"),
    Step("windows", "Driver window down a little, then up"),
    Step("hvac_fan", "HVAC fan to high, then back"),
    Step("locks", "Lock the doors, then unlock them"),
    Step("shifter", "Foot on the brake: shift P-R-N-D, then back to P"),
)


def script_seconds(script) -> float:
    return sum(s.window_s + REST_S for s in script)


class Keys:
    """Single key presses without Enter, when stdin is a terminal; otherwise poll() is always None."""

    def __init__(self, stream=None):
        self._stream, self._restore, self._win = stream if stream is not None else sys.stdin, None, False

    def __enter__(self) -> "Keys":
        try:
            if not self._stream.isatty():
                return self
        except Exception:  # pytest's captured stdin and closed streams: no keys
            return self
        try:
            import termios
            import tty

            fd = self._stream.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            self._restore = lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except ImportError:  # Windows
            self._win = True
        return self

    def poll(self) -> str | None:
        if self._win:
            import msvcrt

            return msvcrt.getwch().lower() if msvcrt.kbhit() else None
        if self._restore is None:
            return None
        import select

        if select.select([self._stream], [], [], 0)[0]:
            return self._stream.read(1).lower()
        return None

    def __exit__(self, *exc) -> None:
        if self._restore is not None:
            self._restore()


def run_capture(events: Iterator[MonitorEvent], writer: CaptureWriter, script, keys, out: Callable[[str], None], start: float) -> str:
    """Write the monitor's events and the script's step records; `start` is the transport time the capture counts from."""
    idx, in_window, deadline, t, ids, last_status = 0, False, 0.0, 0.0, set(), 0.0
    reason = "finished" if not script else "time_limit"

    def begin(i: int, at: float) -> float:
        writer.step(at, script[i].id, "start")
        out(f"[{i + 1}/{len(script)}] {script[i].prompt} ({script[i].window_s:g} s)")
        return at + script[i].window_s

    def stop(at: float, why: str) -> None:
        if in_window:  # a window still open when the capture stops gets its end record
            writer.step(at, script[idx].id, "end")
        writer.end(at, why)

    try:
        if script:
            deadline, in_window = begin(0, 0.0), True
        for ev in events:
            t = ev.t - start
            key = keys.poll()
            if key == "q":
                reason = "quit"
                break
            if script:
                if key == "s" and in_window:
                    writer.step(t, script[idx].id, "skipped")
                    in_window, deadline = False, t + REST_S
                while t >= deadline:
                    if in_window:
                        writer.step(deadline, script[idx].id, "end")
                        in_window, deadline = False, deadline + REST_S
                    else:
                        idx += 1
                        if idx >= len(script):
                            break
                        deadline, in_window = begin(idx, deadline), True
                if idx >= len(script):
                    reason = "finished"
                    break
            if ev.kind == "frame":
                writer.frame(t, ev.text)
                ids.add(ev.text.split(" ", 1)[0])
            elif ev.kind == "gap":
                writer.gap(t, ev.text, ev.seconds)
            if t - last_status >= 5.0:
                last_status = t
                out(f"  {t:5.0f} s · {writer.frames} frames · {len(ids)} ids · {writer.gaps} gaps")
        stop(t, reason)  # inside the try: the end record exists even if closing the stream raises
    except KeyboardInterrupt:
        stop(t, "interrupted")
        raise
    except Exception:
        stop(t, "error")
        raise
    finally:
        events.close()  # stops the adapter and restores ATCAF1 (Transport.monitor's finally)
    return reason


def listen(session: Session, *, label: str, protocol: str, seconds: float | None, out: Callable[[str], None], keys,
           now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    sid = f"{now:%Y-%m-%dT%H-%M-%SZ}-{label}"
    script = () if seconds else SCRIPT
    path = Path(session.config.home) / "captures" / f"{sid}.jsonl"
    with session.connection("listen", protocol) as t:
        transcript = t.transcript_path.relative_to(session.config.home).as_posix() if t.transcript_path else None
        snap = scan(t, snapshot_id=sid, captured_at=now, kind="live", protocol=protocol, transcript=transcript, mode06=True)
        session.store.save(snap)
        dpn = (t.send("ATDPN") or [""])[0].strip().upper()
        can = dpn.lstrip("A") in ("6", "7", "8", "9")
        setup = [{"tx": c, "rx": t.send(c)} for c in ("ATH1", "ATS1", "ATAL")]
        adapter = snap.source.adapter
        mon = "STMA" if adapter.genuine_stn else "ATMA"
        events = t.monitor(mon, seconds or script_seconds(script) + 2.0, can=can)  # SilentModeUnsupported raises here, before any file
        writer = CaptureWriter(path)
        try:
            writer.header(tool_version=__version__, started=now.isoformat(timespec="seconds"),
                          adapter={"ati": adapter.ati, "sti": adapter.sti}, protocol=dpn,
                          protocol_name=snap.protocol.name, can=can,
                          vehicle_key=vehicle_key(snap.vehicle.vin), snapshot_id=sid,
                          monitor_command=mon, setup=setup,
                          script=[{"id": s.id, "prompt": s.prompt, "window_s": s.window_s} for s in script], rest_s=REST_S)
            out(f"listening ({mon}, {'CAN' if can else 'protocol ' + dpn}): s skips a step, q stops")
            run_capture(events, writer, script, keys, out, t.now)
        finally:
            writer.close()
    return path
