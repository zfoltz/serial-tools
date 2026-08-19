"""serialtools command line.

    serialtools list                          show serial ports
    serialtools detect [-p COM3] [--binary]   find baud/framing on the wire
    serialtools tap [...]                     passive capture (the main tool)
    serialtools decode <capture> ...          annotate a capture with a protocol decoder
    serialtools analyze <capture> [--json]    summary / timing / error report
    serialtools diff <good> <bad>             compare captures
    serialtools replay <capture> --port COMx  play a capture onto a port
    serialtools sim <capture|profile> --port COMx   answer requests like the device did
    serialtools term --port COMx [...]        interactive terminal (impersonate the PLC)
    serialtools mcp [--allow-tx]              MCP server for Claude Code
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from . import __version__, analyze as analyze_pkg, decoders
from .core import direction as direction_mod
from .core.capture import CaptureSession
from .core.detect import DetectOptions, detect
from .core.frames import LinkConfig, WIRING_MODES
from .core.ports import PARITY, STOPBITS, discover_ports, show_ports
from .core.sources import ReplaySource, SerialSource
from .storage import session as storage
from .viewer import live as viewer


def parse_port(spec: str) -> tuple[str, str | None]:
    """'COM3=PLC-OUT' -> ('COM3', 'PLC-OUT');  'COM3' -> ('COM3', None)"""
    if "=" in spec:
        port, label = spec.split("=", 1)
        return port.strip(), label.strip()
    return spec.strip(), None


def _add_detect_args(ap):
    ap.add_argument("--binary", action="store_true",
                    help="score detection as a binary protocol instead of ASCII")
    ap.add_argument("--detect-seconds", type=float, default=2.0, metavar="S",
                    help="listen time per candidate setting (default 2). Raise it if the "
                         "PLC polls slowly.")
    ap.add_argument("--detect-threshold", type=float, default=0.95, metavar="F",
                    help="fraction of bytes that must decode cleanly to lock on (default 0.95)")
    ap.add_argument("--detect-min-bytes", type=int, default=8, metavar="N",
                    help="ignore samples shorter than this (default 8)")
    ap.add_argument("--detect-passes", type=int, default=0, metavar="N",
                    help="give up after N full sweeps (default 0 = keep trying forever)")
    ap.add_argument("--detect-wait", type=float, default=0, metavar="S",
                    help="give up if the line stays silent this long before detection "
                         "even starts (default 0 = wait forever)")


def _add_settings_args(ap):
    ap.add_argument("-p", "--port", action="append", default=[], metavar="COMx[=LABEL]",
                    help="tap to listen on; repeat for the second direction. Omit to use "
                         "every port found. Labels are optional; avoid '>' in them, "
                         "PowerShell reads it as redirection.")
    ap.add_argument("-b", "--baud", type=int, help="baud rate. Omit to auto-detect.")
    ap.add_argument("--bytesize", type=int, choices=[5, 6, 7, 8], help="data bits (default auto)")
    ap.add_argument("--parity", choices=list(PARITY), help="parity (default auto)")
    ap.add_argument("--stopbits", choices=list(STOPBITS), default="1", help="stop bits (default 1)")


def _add_decoder_args(ap):
    ap.add_argument("--decoder", choices=decoders.list_decoders(),
                    help="protocol decoder to annotate frames with")
    ap.add_argument("--profile", metavar="NAME",
                    help="device profile (TOML) for the ascii decoder; implies --decoder ascii. "
                         f"Known: {', '.join(decoders.list_profiles()) or '(none found)'}")


def _detect_options(args) -> DetectOptions:
    return DetectOptions(
        ascii_mode=not args.binary,
        seconds=args.detect_seconds,
        threshold=args.detect_threshold,
        min_bytes=args.detect_min_bytes,
        passes=args.detect_passes,
        wait=args.detect_wait,
    )


def _resolve_links(args, stop: threading.Event) -> list[LinkConfig]:
    """Ports + settings -> LinkConfigs, auto-detecting whatever wasn't given."""
    if args.port:
        requested = [parse_port(s) for s in args.port]
    else:
        found = discover_ports()
        if not found:
            sys.exit("No serial ports found. Plug in the USB adapter and try again.")
        print(f"[*] found {len(found)} port(s): {', '.join(found)}", file=sys.stderr)
        requested = [(p, None) for p in found]

    manual = args.baud is not None
    opts = _detect_options(args)
    links: list[LinkConfig] = []
    try:
        for port, label in requested:
            if manual:
                link = LinkConfig(port, label or port, args.baud,
                                  args.bytesize or 8, args.parity or "N", args.stopbits)
            else:
                found_link = detect(port, opts, stop)
                if found_link is None:
                    print(f"[!] {port}: no settings found, skipping.", file=sys.stderr)
                    continue
                link = found_link
                if label:
                    link.label = label
                if args.bytesize:
                    link.bytesize = args.bytesize
                if args.parity:
                    link.parity = args.parity
            links.append(link)
    except KeyboardInterrupt:
        print("\n[+] detection cancelled", file=sys.stderr)
        sys.exit(0)
    return links


def _decode_transform(decoder):
    """Live decoding as a CaptureSession transform; keeps request context."""
    state = {"prev": None}

    def transform(frame: Frame):
        d = decoder.decode(frame.data, state["prev"])
        if d is not None:
            frame.decode = d
            state["prev"] = d
    return transform


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def cmd_list(args) -> int:
    show_ports()
    return 0


def cmd_detect(args) -> int:
    stop = threading.Event()
    links = _resolve_links(args, stop)
    if not links:
        return 1
    print("\nDetected settings:")
    for l in links:
        print(f"  {l.port:<10} {l.settings()}")
    print("\nCapture with:  serialtools tap " +
          " ".join(f"-p {l.port}" for l in links) +
          f" -b {links[0].baud} --bytesize {links[0].bytesize} --parity {links[0].parity}")
    return 0


def cmd_tap(args) -> int:
    use_color = not args.no_color and sys.stdout.isatty()
    stop = threading.Event()
    links = _resolve_links(args, stop)
    if not links:
        sys.exit("No usable taps. Check wiring and that the link is carrying traffic.")

    if args.detect_only:
        return cmd_detect_print(links)

    if args.wiring == "rs485-2w":
        if len(links) > 1:
            sys.exit("rs485-2w wiring is one tap on the bus -- give exactly one -p")
        if links[0].label == links[0].port:
            links[0].label = "BUS"

    decoder = decoders.resolve(args.decoder, args.profile)
    transforms = []
    if decoder:
        transforms.append(_decode_transform(decoder))
    if args.wiring == "rs485-2w":
        transforms.append(direction_mod.LiveDirection(args.first_is))

    sources = [SerialSource(link, gap_ms=args.gap, max_frame=args.max_frame)
               for link in links]
    session = CaptureSession(sources, wiring=args.wiring, gap_ms=args.gap,
                             transforms=transforms)

    writer = None
    if not args.no_log:
        device = {"profile": args.profile} if args.profile else None
        writer = storage.SessionWriter(links, args.wiring, args.gap,
                                       root=args.captures_root, name=args.name,
                                       notes=args.notes, device=device,
                                       text_formatter=viewer.text_formatter(args.width))
        session.add_sink(writer.sink)
        print(f"[+] logging to {writer.path}", file=sys.stderr)

    view = None
    if args.live:
        view = viewer.LiveView(session, width=args.width)
        session.add_sink(view.sink)
        view.start()
    else:
        session.add_sink(viewer.console_sink(args.width, use_color))

    print(f"[+] frame gap {args.gap}ms. Ctrl+C to stop.\n", file=sys.stderr)
    session.start()
    try:
        while not session.stop.is_set():
            time.sleep(0.2)
            if view:
                view.tick()
    except KeyboardInterrupt:
        pass
    finally:
        session.join()
        if view:
            view.stop()
        if writer:
            writer.close(session.stats)
        elapsed = session.elapsed()
        print(f"\n[+] stopped after {elapsed:.1f}s", file=sys.stderr)
        for label, n in session.stats.items():
            print(f"    {label:<12} {n} bytes ({n / max(elapsed, 1):.1f} B/s)", file=sys.stderr)
        if not session.stats:
            print("    no data captured -- check wiring, ground, and that the link is active",
                  file=sys.stderr)
    return 0


def cmd_detect_print(links) -> int:
    print("\nDetected settings:")
    for l in links:
        print(f"  {l.port:<10} {l.settings()}")
    return 0


def _load_capture(path: str, prefer_decoded: bool = False):
    """-> (frames, meta or None)"""
    import os
    meta = None
    if os.path.isdir(path):
        try:
            meta = storage.load_session(path)
        except FileNotFoundError:
            pass
        decoded_file = os.path.join(path, "decoded.jsonl")
        use_decoded = prefer_decoded and os.path.exists(decoded_file)
        frames = list(storage.iter_frames(path, decoded=use_decoded))
    else:
        frames = list(storage.iter_frames(path))
    return frames, meta


def cmd_decode(args) -> int:
    import os
    decoder = decoders.resolve(args.decoder, args.profile)
    if decoder is None:
        sys.exit("give --decoder and/or --profile")
    frames, meta = _load_capture(args.capture)
    if not frames:
        sys.exit("no frames in capture")

    frames, resplit_count, ok, err = decoders.decode_frames(
        frames, decoder, resplit=not args.no_resplit)

    wiring = (meta or {}).get("wiring")
    if wiring == "rs485-2w" or args.redirect:
        conf = direction_mod.infer(frames, first_is=args.first_is)
        print(f"[+] direction inference confidence {conf:.0%}", file=sys.stderr)

    if os.path.isdir(args.capture):
        out_path = storage.write_decoded(args.capture, frames)
        print(f"[+] wrote {out_path}", file=sys.stderr)
    print(f"[+] {len(frames)} frames ({resplit_count} resplit), "
          f"{ok} decoded clean, {err} with errors", file=sys.stderr)
    if args.show:
        for f in frames:
            print(viewer.format_frame(f, width=16, use_color=False))
    return 0


def cmd_analyze(args) -> int:
    frames, meta = _load_capture(args.capture, prefer_decoded=True)
    if not frames:
        sys.exit("no frames in capture")
    if args.decoder or args.profile:
        decoder = decoders.resolve(args.decoder, args.profile)
        prev = None
        for f in frames:
            if f.decode is None:
                d = decoder.decode(f.data, prev)
                if d is not None:
                    f.decode, prev = d, d
    report = analyze_pkg.full_report(frames, meta)
    if args.json:
        import json
        print(json.dumps(report, indent=2))
    else:
        print(analyze_pkg.render_text(report))
    return 0


def cmd_diff(args) -> int:
    from .analyze import diff as diff_mod
    good, good_meta = _load_capture(args.good, prefer_decoded=True)
    bad, bad_meta = _load_capture(args.bad, prefer_decoded=True)
    report = diff_mod.analyze(good, bad, good_meta, bad_meta)
    if args.json:
        import json
        print(json.dumps(report, indent=2))
    else:
        print("\n".join(diff_mod.render(report)))
    return 0


def cmd_replay(args) -> int:
    from .sim import replay as replay_mod
    frames, meta = _load_capture(args.capture)
    if not frames:
        sys.exit("no frames in capture")
    baud = args.baud
    if baud is None and meta and meta.get("taps"):
        baud = meta["taps"][0].get("baud", 9600)
    replay_mod.play(frames, args.port, baud or 9600, speed=args.speed,
                    only_dir=args.dir, loop=args.loop)
    return 0


def cmd_sim(args) -> int:
    import os
    from .sim.device import DeviceSimulator
    if os.path.isdir(args.source) or args.source.endswith(".jsonl"):
        frames, meta = _load_capture(args.source, prefer_decoded=True)
        sim = DeviceSimulator.from_capture(frames)
        baud = args.baud
        if baud is None and meta and meta.get("taps"):
            baud = meta["taps"][0].get("baud", 9600)
    else:
        profile = decoders.load_profile(args.source)
        sim = DeviceSimulator.from_profile(profile)
        baud = args.baud
    if args.delay_ms is not None:
        sim.delay_ms = args.delay_ms
    sim.serve(args.port, baud or 9600)
    return 0


def cmd_term(args) -> int:
    from .core.frames import ascii_render
    from .sim.replay import open_tx

    profile = decoders.load_profile(args.profile) if args.profile else None
    if args.crlf:
        term = b"\r\n"
    elif profile:
        from .decoders.ascii_profile import _to_bytes
        term = _to_bytes(profile.get("framing", {}).get("terminator", "CR"))
    else:
        term = b"\r"

    def render(b: bytes) -> str:
        return "".join(chr(x) if 32 <= x < 127 else f"<{x:02X}>" for x in b)

    ser = open_tx(args.port, args.baud)
    print(f"open {args.port} @ {args.baud} 8N1, terminator {term!r}", file=sys.stderr)
    if profile:
        known = ", ".join(profile.get("commands", {}))
        print(f"profile {profile.get('device', {}).get('name')}: {known}", file=sys.stderr)

    def send_and_print(cmd: str):
        ser.reset_input_buffer()
        ser.write(cmd.encode("ascii", "replace") + term)
        ser.flush()
        got = bytearray()
        end = time.time() + args.wait
        while time.time() < end:
            chunk = ser.read(256)
            if chunk:
                got += chunk
                end = time.time() + 0.4  # keep reading while data flows
        print(f">>> {cmd}")
        print(f"    {render(bytes(got)) if got else '(no response)'}")

    try:
        if args.commands:
            for cmd in args.commands:
                send_and_print(cmd)
        else:
            print("interactive -- type a command, empty line or Ctrl+C to quit", file=sys.stderr)
            while True:
                try:
                    cmd = input("> ").strip()
                except EOFError:
                    break
                if not cmd:
                    break
                send_and_print(cmd)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
    return 0


def cmd_mcp(args) -> int:
    from .mcp.server import run
    return run(allow_tx=args.allow_tx)


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="serialtools",
        description="Industrial serial (RS232/RS485) tap, decode, and analysis toolkit.")
    ap.add_argument("--version", action="version", version=f"serialtools {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list serial ports").set_defaults(fn=cmd_list)

    d = sub.add_parser("detect", help="auto-detect line settings on the wire")
    _add_settings_args(d)
    _add_detect_args(d)
    d.set_defaults(fn=cmd_detect)

    t = sub.add_parser(
        "tap", help="passive capture (the main tool)",
        epilog="Wire tap RXD (DB9 pin 2) to the line you want to watch and tap GND "
               "(pin 5) to the link's signal ground. Leave pin 3 disconnected. "
               "See WIRING.md.")
    _add_settings_args(t)
    _add_detect_args(t)
    _add_decoder_args(t)
    t.add_argument("--wiring", choices=WIRING_MODES, default="rs232",
                   help="rs232 / rs485-4w: one tap per direction. rs485-2w: one tap "
                        "sees both directions, inferred (default rs232)")
    t.add_argument("--first-is", choices=["master", "slave"],
                   help="rs485-2w only: force the first frame's side")
    t.add_argument("--detect-only", action="store_true",
                   help="report the detected settings and exit without capturing")
    t.add_argument("--gap", type=float, default=15.0, metavar="MS",
                   help="idle time that ends a frame, in ms (default 15). Modbus RTU wants "
                        "about 3.5 character times: ~4ms at 9600, ~2ms at 19200.")
    t.add_argument("--max-frame", type=int, default=4096, help="force a frame break after N bytes")
    t.add_argument("--width", type=int, default=16, help="hex bytes per line (default 16)")
    t.add_argument("--name", default="", help="capture directory name suffix")
    t.add_argument("--notes", default="", help="free-text note stored in session.json")
    t.add_argument("--captures-root", default=storage.DEFAULT_ROOT,
                   help="where capture dirs go (default captures/)")
    t.add_argument("--no-log", action="store_true", help="console only, no capture dir")
    t.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    t.add_argument("--live", action="store_true", help="pinned status header (needs rich)")
    t.set_defaults(fn=cmd_tap)

    de = sub.add_parser("decode", help="annotate a capture with a protocol decoder")
    de.add_argument("capture", help="capture dir or .jsonl file")
    _add_decoder_args(de)
    de.add_argument("--redirect", action="store_true",
                    help="(re-)infer 2-wire direction even if wiring isn't rs485-2w")
    de.add_argument("--first-is", choices=["master", "slave"])
    de.add_argument("--no-resplit", action="store_true",
                    help="don't let the decoder re-frame merged frames")
    de.add_argument("--show", action="store_true", help="print decoded frames")
    de.set_defaults(fn=cmd_decode)

    an = sub.add_parser("analyze", help="summary / timing / error report")
    an.add_argument("capture", help="capture dir or .jsonl file")
    _add_decoder_args(an)
    an.add_argument("--json", action="store_true")
    an.set_defaults(fn=cmd_analyze)

    df = sub.add_parser("diff", help="compare a good capture against a bad one")
    df.add_argument("good")
    df.add_argument("bad")
    df.add_argument("--json", action="store_true")
    df.set_defaults(fn=cmd_diff)

    rp = sub.add_parser("replay", help="play a capture onto a port (com0com for testing)")
    rp.add_argument("capture")
    rp.add_argument("--port", required=True)
    rp.add_argument("--baud", type=int, help="default: from session.json")
    rp.add_argument("--speed", type=float, default=1.0)
    rp.add_argument("--dir", help="only this direction/tap label")
    rp.add_argument("--loop", action="store_true")
    rp.set_defaults(fn=cmd_replay)

    sm = sub.add_parser("sim", help="simulate the device from a capture or profile")
    sm.add_argument("source", help="capture dir, .jsonl, or profile name")
    sm.add_argument("--port", required=True)
    sm.add_argument("--baud", type=int)
    sm.add_argument("--delay-ms", type=float, help="reply delay (default: median from capture)")
    sm.set_defaults(fn=cmd_sim)

    tm = sub.add_parser("term", help="interactive terminal -- impersonate the PLC. "
                                     "NEVER on a tap wired receive-only; see WIRING.md")
    tm.add_argument("commands", nargs="*", help="commands to send; empty = interactive")
    tm.add_argument("--port", required=True)
    tm.add_argument("--baud", type=int, default=9600)
    tm.add_argument("--profile", help="device profile for terminator + command list")
    tm.add_argument("--crlf", action="store_true", help="CR LF terminator (PLC PRTXT style)")
    tm.add_argument("--wait", type=float, default=2.0, help="seconds to listen per command")
    tm.set_defaults(fn=cmd_term)

    mc = sub.add_parser("mcp", help="run the MCP server (stdio) for Claude Code")
    mc.add_argument("--allow-tx", action="store_true",
                    help="register the send_bytes tool (transmitting!). Off by default.")
    mc.set_defaults(fn=cmd_mcp)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
