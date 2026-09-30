import argparse
import sys
from pathlib import Path

from obd_reader.capture import capture
from obd_reader.replay import ReplayPort
from obd_reader.scanner import scan
from obd_reader.transport import SerialPort, Transport


def _replay(args) -> int:
    port = ReplayPort.from_file(args.transcript)
    snap = scan(
        Transport(port),
        snapshot_id=args.transcript.stem,
        protocol=args.protocol,
        transcript=str(args.transcript),
    )
    print(snap.model_dump_json(indent=2))
    return 0


def _scan(args) -> int:
    port = SerialPort(args.port, baudrate=args.baud)
    snap, s_path, t_path = capture(
        port, args.out_dir, label=args.label, protocol=args.protocol, timeout=args.timeout
    )
    codes = lambda ds: ", ".join(d.code for d in ds) or "none"  # noqa: E731
    print(f"vin:        {snap.vehicle.vin or 'not read'}")
    print(f"protocol:   {snap.protocol.name or 'unknown'}")
    print(f"adapter:    {snap.source.adapter.ati} / {snap.source.adapter.sti or 'not STN'}")
    print(f"stored:     {codes(snap.dtcs.stored)}")
    print(f"pending:    {codes(snap.dtcs.pending)}")
    print(f"permanent:  {codes(snap.dtcs.permanent)}")
    print(f"mil:        {snap.mil.on} ({snap.mil.dtc_count} codes)")
    for w in snap.warnings:
        print(f"warning:    {w}")
    print(f"snapshot:   {s_path}")
    print(f"transcript: {t_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shadetree-ai")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("replay", help="build a snapshot from a recorded transcript (no adapter)")
    rp.add_argument("transcript", type=Path)
    rp.add_argument("--protocol", default=None, help="ATSP value to pin, e.g. 6")
    rp.set_defaults(func=_replay)

    sc = sub.add_parser("scan", help="read-only scan of a connected car through an adapter")
    sc.add_argument("--port", required=True, help="serial device or pyserial URL, e.g. /dev/ttyUSB0")
    sc.add_argument("--protocol", default="0", help="ATSP value; 0 = automatic search (default)")
    sc.add_argument("--baud", type=int, default=115200)
    sc.add_argument("--timeout", type=float, default=10.0, help="seconds to wait per command")
    sc.add_argument("--label", default="scan", help="short name for the capture, [a-z0-9-]")
    sc.add_argument("--out-dir", type=Path, default=Path("."), help="snapshots/ and transcripts/ go here")
    sc.set_defaults(func=_scan)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, OSError) as e:  # e.g. adapter never returned its '>' prompt
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
