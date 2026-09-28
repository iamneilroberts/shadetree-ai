import argparse
import sys
from pathlib import Path

from obd_reader.replay import ReplayPort
from obd_reader.scanner import scan
from obd_reader.transport import Transport


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shadetree-ai")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay", help="build a snapshot from a recorded transcript (no adapter)")
    rp.add_argument("transcript", type=Path)
    rp.add_argument("--protocol", default=None, help="ATSP value to pin, e.g. 6")
    args = ap.parse_args(argv)

    port = ReplayPort.from_file(args.transcript)
    snap = scan(
        Transport(port),
        snapshot_id=args.transcript.stem,
        protocol=args.protocol,
        transcript=str(args.transcript),
    )
    print(snap.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
