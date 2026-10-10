import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from obd_reader.capture import capture
from obd_reader.plugins import load_plugins
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
    codes = lambda k: "no answer" if k in snap.dtcs.unanswered else ", ".join(d.code for d in getattr(snap.dtcs, k)) or "none"  # noqa: E731
    print(f"vin:        {snap.vehicle.vin or 'not read'}")
    print(f"protocol:   {snap.protocol.name or 'unknown'}")
    a, m9 = snap.source.adapter, snap.mode09
    print(f"adapter:    {a.ati} / {a.sti or 'not STN'}" + (f" / {a.device}" if a.device else ""))
    print(f"battery:    {a.supply_voltage or 'not read'}")
    print(f"ecu names:  {', '.join(m9.ecu_names) or 'not read'}")
    print(f"cal ids:    {', '.join(m9.cal_ids) or 'not read'} (cvn {', '.join(m9.cvns) or 'not read'})")
    print(f"stored:     {codes('stored')}")
    print(f"pending:    {codes('pending')}")
    print(f"permanent:  {codes('permanent')}")
    print(f"mil:        {snap.mil.on} ({snap.mil.dtc_count} codes)")
    classes = Counter(r.reply for r in snap.replies)
    print(f"replies:    {len(snap.replies)} ({', '.join(f'{k} {n}' for k, n in sorted(classes.items())) or 'none'})")
    print(f"undecoded:  {len(snap.undecoded)} PIDs" + (f" ({', '.join(u.pid for u in snap.undecoded)})" if snap.undecoded else ""))
    for w in snap.warnings:
        print(f"warning:    {w}")
    print(f"snapshot:   {s_path}")
    print(f"transcript: {t_path}")
    return 0


def _listen(args) -> int:
    from obd_reader.bus_capture import summarize_file

    if args.summarize:
        md = summarize_file(args.summarize)
        print(md.read_text(encoding="utf-8"), end="")
        return 0
    from obd_reader.capture import _LABEL_RE
    from obd_reader.listen import Keys, listen
    from obd_reader.session import Config, Session

    if not _LABEL_RE.fullmatch(args.label):
        raise ValueError("label must be 1-40 chars of [a-z0-9-]")
    if args.seconds is not None and not 0 < args.seconds <= 900:
        raise ValueError("--seconds must be in (0, 900]")
    if args.port == "sim":
        from obd_reader.simulator import SimPort

        session = Session(Config(port="sim", home=args.out_dir, timeout=1.0), port_factory=lambda: SimPort("healthy", bus="can"))
    else:
        session = Session(Config(port=args.port, baud=args.baud, timeout=args.timeout, home=args.out_dir))
    # captures that exist before this run, so Ctrl-C never names an older one
    pattern = f"*-{args.label}.jsonl"
    before = set((Path(args.out_dir) / "captures").glob(pattern))
    try:
        with Keys() as keys:
            path = listen(session, label=args.label, protocol=args.protocol or "0", seconds=args.seconds,
                          out=lambda s: print(s, flush=True), keys=keys)
    except KeyboardInterrupt:
        new = sorted(set((Path(args.out_dir) / "captures").glob(pattern)) - before)
        print(f"stopped: the partial capture is {new[-1]}" if new else "stopped before the capture began")
        return 130
    md = summarize_file(path)
    print(md.read_text(encoding="utf-8"), end="")
    print(f"capture (raw bus data, may hold the VIN, keep local): {path}\nsummary (no payload bytes): {md}")
    return 0


def _probe(args) -> int:
    from obd_reader.capture import _LABEL_RE
    from obd_reader.probe import write_probe

    if args.replay:
        if not _LABEL_RE.fullmatch(args.label):
            raise ValueError("label must be 1-40 chars of [a-z0-9-]")
        snap = scan(Transport(ReplayPort.from_file(args.replay)),
                    snapshot_id=f"{datetime.now(timezone.utc):%Y-%m-%dT%H-%M-%SZ}-{args.label}",
                    protocol=args.protocol, transcript=str(args.replay), mode06=True)
    else:
        snap, s_path, t_path = capture(SerialPort(args.port, baudrate=args.baud), args.out_dir, label=args.label,
                                       protocol=args.protocol or "0", timeout=args.timeout, mode06=True)
        print(f"snapshot and transcript (contain the VIN, keep local): {s_path}, {t_path}")
    from obd_reader.quirks import QuirkStore, applied
    from obd_reader.vehicle import vehicle_key

    found = QuirkStore(args.out_dir).load(vehicle_key(snap.vehicle.vin))
    j_path, m_path = write_probe(snap, args.out_dir, applied(*found) if found else None)
    print(m_path.read_text(encoding="utf-8"), end="")
    print(f"report (no VIN, safe to share): {j_path} and {m_path}")
    if args.propose_quirks:  # printed only; `quirks accept` is the one writer
        import json

        print(json.dumps(json.loads(j_path.read_text(encoding="utf-8"))["quirks_proposal"], indent=2))
    return 0


def _quirks_accept(args) -> int:
    from obd_reader.quirks import accept

    print(f"wrote {accept(args.file, args.out_dir, replace=args.replace)} (local, gitignored; a hint for runs on this class of car)")
    return 0


def _quirks_check(args) -> int:
    from obd_reader.quirks import check, hints

    q, why = check(args.file)
    if not why:
        print(f"ok: {q.key}, hints: {hints(q)}")
        return 0
    for w in why:
        print(f"problem: {w}")
    return 1


def _quirks_show(args) -> int:
    from obd_reader.quirks import KEY_RE, REPO_QUIRKS, WMI_RE, QuirkStore, hints
    from obd_reader.vehicle import vehicle_key

    typed = args.key.strip().upper()
    key = vehicle_key(typed) or typed
    if key != typed:
        print(f"vehicle key {key} (from the VIN typed; the VIN is not printed or kept)")
    if not (KEY_RE.fullmatch(key) or WMI_RE.fullmatch(key)):
        raise ValueError("not a vehicle key (VIN characters 1-8, a dash, VIN character 10, e.g. 1HGCM826-3) "
                         "or a WMI (VIN characters 1-3, e.g. 1HG)")
    found = None
    for path, q, why in QuirkStore(args.out_dir).candidates(key):
        status = "applies" if q else "missing" if why == ["missing"] else "skipped: " + "; ".join(why)
        print(f"  {path.parent.name}/{path.name}: {status}")
        if q is not None:
            found = (q, path)
            break
    if not REPO_QUIRKS.is_dir():
        print("  (no committed quirks/ folder here: it only loads from a source checkout)")
    print(f"applies: {found[1].parent.name}/{found[1].name}: {hints(found[0])}" if found else f"no quirks file applies to {key}")
    return 0


def console_main(args, block: bool = True):
    """Start the live console (page + sampler). Returns the ConsoleService; blocks until Ctrl-C if block."""
    from obd_reader.console import ConsoleService
    from obd_reader.session import Config, Session

    from obd_reader.scenarios import load_scenarios

    scen = None
    if args.scenarios:   # main() prints "error: ..." and exits 1 for ValueError/OSError, as for any other bad argument
        try:
            scen = load_scenarios(args.scenarios)
        except (OSError, ValueError) as exc:
            raise ValueError(f"--scenarios {args.scenarios}: {exc}") from None
    session = Session(Config(port=args.port, protocol=args.protocol, home=args.out_dir))
    svc = ConsoleService(session, demo=args.demo, host=args.host, http_port=args.http_port,
                         allow_lan=args.allow_lan, scenario=args.scenario, allow_hosts=args.allow_host,
                         examples_dir=args.examples_dir, scenarios=scen)
    server = svc.ensure()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("warning: the console is reachable from your network; anyone with the link can watch live data",
              file=sys.stderr)
    if not args.no_start and not args.demo:   # a demo console comes up idle: the page's Demo button starts the simulated run
        svc.start_sampling(seconds=args.seconds)
    print(f"console: {server.url}", flush=True)
    if args.allow_host:
        print(f"console (remote): https://{args.allow_host[0]}/?t={server.token}", flush=True)
    if args.host in ("0.0.0.0", "::"):
        from obd_reader.console import guess_lan_ip

        ip = guess_lan_ip()
        if ip:  # from another device on the same network
            print(f"console (other devices): http://{ip}:{server.port}/?t={server.token}", flush=True)
    if block:
        import time

        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            svc.stop()
    return svc


def _export_run(args) -> int:
    from obd_reader.export import ExportError, build_zip, export_run, newest_runs

    if args.zip or args.dest.suffix.lower() == ".zip":
        dest, names = args.dest.with_suffix(".zip"), [p.name for p in newest_runs(args.out_dir, args.latest)]
        try:
            if not names:
                raise ExportError(f"no run files in {args.out_dir / 'runs'} (press Save run in the console first)")
            data, left_out = build_zip(args.out_dir, names)
        except (ExportError, ValueError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        dest.write_bytes(data)
        print(f"wrote {dest.resolve()} ({len(data)} bytes)")
        for x in left_out:
            print(f"left out: {x}")
        print("the VIN's serial digits are masked (000000), so it is safe to attach to a GitHub issue")
        return 0
    try:
        dest = export_run(args.out_dir, args.dest, args.latest)
    except ExportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"wrote {dest.resolve()} ({dest.stat().st_size} bytes)")
    print("the transcripts inside can contain the VIN: move it privately and never commit it")
    return 0


def _label_run(args) -> int:
    from obd_reader.replay_run import label_run

    meta = label_run(args.file, make=args.make, model=args.model, year=args.year, title=args.title)
    print(f"labelled {args.file}: {meta['year']} {meta['make']} {meta['model']} \u00b7 {meta['title']}")
    return 0


def _vin_info(args) -> int:
    from obd_reader import vin_decode as vd

    key = vd.to_key(args.vin)  # a full VIN is cut to its key here, before anything is printed or sent
    off = vd.offline(key)
    print(f"vehicle key: {key} (VIN characters 1-8 and 10; the serial is not used)")
    print(f"make:        {off['make'] or 'unknown (WMI ' + key[:3] + ' is not in the offline table)'}")
    print(f"model year:  {off['year'] or 'unknown'} (from character 10; check it)")
    print("model:       not decodable offline" + ("" if args.lookup else " (add --lookup to ask NHTSA)"))
    if args.lookup:
        print(f"asking NHTSA vPIC with {vd.partial_vin(key)} ...")
        try:
            r = vd.lookup(key, args.out_dir)
        except vd.LookupUnavailable as e:
            print(f"lookup unavailable: {e}")
            return 1
        for k in ("make", "model", "year", "trim", "cylinders", "displacement_l", "fuel"):
            print(f"  {k + ':':16}{r.get(k) or '-'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
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

    pr = sub.add_parser("probe", help="read-only scan plus Mode 06 support bitmaps; writes a VIN-free report to probes/")
    src = pr.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="serial device or pyserial URL, e.g. /dev/ttyUSB0")
    src.add_argument("--replay", type=Path, metavar="TRANSCRIPT", help="probe a recorded transcript instead (no adapter)")
    pr.add_argument("--protocol", default=None, help="ATSP value; live default 0 = automatic search")
    pr.add_argument("--baud", type=int, default=115200)
    pr.add_argument("--timeout", type=float, default=10.0, help="seconds to wait per command")
    pr.add_argument("--label", default="probe", help="short name for the probe, [a-z0-9-]")
    pr.add_argument("--out-dir", type=Path, default=Path("."), help="probes/ (and, live, snapshots/ and transcripts/) go here")
    pr.add_argument("--propose-quirks", action="store_true", help="also print the proposed quirks JSON (nothing is written)")
    pr.set_defaults(func=_probe)

    ls = sub.add_parser("listen", help="listen-only bus capture with a guided action script; writes captures/<id>.jsonl (raw bus data, keep local)")
    src = ls.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="serial device or pyserial URL, or 'sim' for the simulator")
    src.add_argument("--summarize", type=Path, metavar="CAPTURE", help="print and save the summary of a capture (no adapter)")
    ls.add_argument("--protocol", default=None, help="ATSP value; default 0 = automatic search")
    ls.add_argument("--baud", type=int, default=115200)
    ls.add_argument("--timeout", type=float, default=10.0, help="seconds to wait per command")
    ls.add_argument("--seconds", type=float, default=None, help="plain listen for N seconds (max 900) instead of the guided script")
    ls.add_argument("--label", default="listen", help="short name for the capture, [a-z0-9-]")
    ls.add_argument("--out-dir", type=Path, default=Path("."), help="captures/ (and snapshots/, transcripts/) go here")
    ls.set_defaults(func=_listen)

    qk = sub.add_parser("quirks", help="per-car hints (quirks/ committed, quirks-local/ private)")
    qsub = qk.add_subparsers(dest="qcmd", required=True)
    qa = qsub.add_parser("accept", help="write a reviewed probe proposal to quirks-local/<key>.json (overwrites only with --replace)")
    qa.add_argument("file", type=Path, help="a probe report .json (its quirks_proposal) or a quirks .json")
    qa.add_argument("--out-dir", type=Path, default=Path("."), help="quirks-local/ goes here (the data home)")
    qa.add_argument("--replace", action="store_true", help="overwrite an existing quirks-local/<key>.json")
    qa.set_defaults(func=_quirks_accept)
    qc = qsub.add_parser("check", help="check a quirks .json (or a probe report's proposal) with the loader's rules; exit 1 on problems")
    qc.add_argument("file", type=Path, help="a quirks .json (must be named <key>.json) or a probe report .json")
    qc.set_defaults(func=_quirks_check)
    qs = qsub.add_parser("show", help="which quirks file applies to a car, and why the others were skipped",
                         description="Search order: quirks-local/<key>.json, quirks/<key>.json, quirks-local/<WMI>.json, "
                                     "quirks/<WMI>.json; the first that loads applies.")
    qs.add_argument("key", metavar="KEY_OR_WMI",
                    help="vehicle key: VIN characters 1-8, a dash, VIN character 10 (model year), e.g. 1HGCM826-3 "
                         "(the probe report's vehicle_key); or a WMI: VIN characters 1-3, e.g. 1HG")
    qs.add_argument("--out-dir", type=Path, default=Path("."), help="the data home that holds quirks-local/")
    qs.set_defaults(func=_quirks_show)

    co = sub.add_parser("console", help="open the live console web page (read-only)")
    co.add_argument("--port", default=None, help="adapter serial device (not needed with --demo)")
    co.add_argument("--protocol", default="0", help="ATSP value; 0 = automatic search (default), 2 = J1850 VPW")
    co.add_argument("--demo", action="store_true", help="use the built-in simulated car instead of an adapter; the page comes up idle and its Demo button starts the simulated run")
    co.add_argument("--scenario", default="rich", choices=["healthy", "rich", "lean"],
                    help="demo scenario: healthy; rich = coolant sensor reads cold (P0118, open loop); lean = vacuum leak (P0171, P0174)")
    co.add_argument("--http-port", type=int, default=8765, help="local web port (0 = any free port)")
    co.add_argument("--host", default="127.0.0.1", help="bind address (non-loopback needs --allow-lan)")
    co.add_argument("--allow-lan", action="store_true", help="allow binding a non-loopback address")
    co.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                    help="also accept this public host name (repeatable), for a tunnel such as Cloudflare Tunnel; the console stays bound to loopback")
    co.add_argument("--seconds", type=float, default=600.0, help="auto-stop after this many seconds")
    co.add_argument("--no-start", action="store_true", help="open the page without starting sampling")
    co.add_argument("--out-dir", type=Path, default=Path("."), help="runs/ and transcripts/ go here")
    co.add_argument("--examples-dir", type=Path, default=None,
                    help="folder of public example runs for the replay picker (default: examples/runs in the repo, if present)")
    co.add_argument("--scenarios", type=Path, default=None, metavar="FILE",
                    help="shared gauge scenarios (JSON); see docs/design.md 7b")
    co.set_defaults(func=lambda a: (console_main(a), 0)[1])
    ex = sub.add_parser("export-run", help="bundle the newest saved run(s) and transcripts into one .tgz to move to another machine")
    ex.add_argument("--out-dir", type=Path, default=Path("."), help="where runs/ and transcripts/ are")
    ex.add_argument("--dest", type=Path, default=Path("shadetree-share.tgz"), help="bundle to write")
    ex.add_argument("--latest", type=int, default=1, help="how many of the newest runs to include")
    ex.add_argument("--zip", action="store_true",
                    help="write a .zip to share instead, with the VIN's serial digits masked (also when --dest ends in .zip)")
    ex.set_defaults(func=_export_run)
    lr = sub.add_parser("label-run", help="add the make, model, year and title the console's replay picker shows (no VIN)")
    lr.add_argument("file", type=Path, help="a saved run .json")
    lr.add_argument("--make", required=True, help="e.g. Honda (at most 40 characters)")
    lr.add_argument("--model", required=True, help="e.g. Ridgeline (at most 40 characters)")
    lr.add_argument("--year", required=True, type=int, help="model year, e.g. 2024")
    lr.add_argument("--title", required=True, help="short description, e.g. 'Ridgeline 6 min drive' (at most 80 characters)")
    lr.set_defaults(func=_label_run)
    vi = sub.add_parser("vin-info", help="suggest make and model year from a vehicle key (offline); --lookup asks NHTSA for the model")
    vi.add_argument("vin", metavar="KEY_OR_PARTIAL",
                    help="vehicle key such as 1HGCM826-3, partial VIN such as 1HGCM826*3*******, or a full VIN "
                         "(reduced to the key at once; never echoed or sent)")
    vi.add_argument("--lookup", action="store_true",
                    help="ask NHTSA vPIC (one HTTPS call, sends only the key characters, no serial; cached)")
    vi.add_argument("--out-dir", type=Path, default=Path("."), help="the data home that holds the lookup cache")
    vi.set_defaults(func=_vin_info)
    for plugin in load_plugins():
        if hasattr(plugin, "cli"):
            plugin.cli(sub)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, OSError) as e:  # e.g. adapter never returned its '>' prompt
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
