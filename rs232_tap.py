#!/usr/bin/env python3
"""
rs232_tap.py -- passive RS232 line sniffer with automatic port/baud detection.

Listens on one or two receive-only serial taps wired across a live RS232 link
and prints every frame it sees, timestamped and labelled by direction, while
writing the same thing to a log file.

By default it finds the adapters itself and brute-forces the line settings,
locking on when the traffic decodes as clean ASCII. Just run it:

    python rs232_tap.py

The adapters are never allowed to transmit: only pin 2 (RXD) and pin 5 (GND)
should be connected on the tap side. See WIRING.md.

Other examples
--------------
  python rs232_tap.py --list                        # show serial ports
  python rs232_tap.py --detect-only                 # work out the settings, don't capture
  python rs232_tap.py -p COM3 -p COM4               # auto baud, but only these ports
  python rs232_tap.py -p COM3=PLC-OUT -b 9600       # skip detection entirely
  python rs232_tap.py --binary                      # score frames as binary, not ASCII
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import queue
import string
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial is not installed.  Run:  python -m pip install pyserial")


PARITY = {
    "N": serial.PARITY_NONE,
    "E": serial.PARITY_EVEN,
    "O": serial.PARITY_ODD,
    "M": serial.PARITY_MARK,
    "S": serial.PARITY_SPACE,
}
BYTESIZE = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}
STOPBITS = {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE, "2": serial.STOPBITS_TWO}

# Ordered most-likely-first, so detection usually locks in the first few tries.
AUTO_BAUDS = [9600, 19200, 38400, 115200, 57600, 4800, 2400, 1200]
AUTO_FRAMING = [(8, "N"), (7, "E"), (7, "O"), (8, "E"), (8, "O"), (7, "N")]

# What counts as "it decoded": printable ASCII, plus the C0 control codes that
# ASCII instrument protocols actually frame with (STX/ETX/ACK/NAK and friends).
# Leaving these out makes a perfectly good <STX>...<ETX> protocol score ~90%
# and never lock.
ASCII_CTRL = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x09, 0x0A, 0x0B, 0x0C, 0x0D,
              0x15, 0x16, 0x17, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F}
ASCII_OK = set(range(0x20, 0x7F)) | ASCII_CTRL
PRINTABLE = set(bytes(string.printable[:-5], "ascii"))

COLORS = ["\033[36m", "\033[33m", "\033[35m", "\033[32m"]  # cyan, yellow, magenta, green
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass
class Link:
    """One tap: a port plus the line settings to read it with."""
    port: str
    label: str
    baud: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: str = "1"

    def settings(self) -> str:
        return f"{self.baud} {self.bytesize}{self.parity}{self.stopbits}"


@dataclass
class Frame:
    ts: float
    label: str
    color: str
    data: bytes
    gap_ms: float | None  # idle time since the previous frame on any tap


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------

def ascii_render(data: bytes) -> str:
    return "".join(chr(b) if b in PRINTABLE else "." for b in data)


def format_frame(f: Frame, width: int, use_color: bool) -> str:
    stamp = datetime.fromtimestamp(f.ts).strftime("%H:%M:%S.%f")[:-3]
    gap = f"+{f.gap_ms:8.1f}ms" if f.gap_ms is not None else " " * 11
    head = f"{stamp} {gap}  {f.label:<9} {len(f.data):>4}B"

    if use_color:
        head = f"{DIM}{stamp} {gap}{RESET}  {f.color}{f.label:<9}{RESET} {DIM}{len(f.data):>4}B{RESET}"

    if len(f.data) <= width:
        hexpart = " ".join(f"{b:02X}" for b in f.data)
        return f"{head}  {hexpart:<{width * 3}} |{ascii_render(f.data)}|"

    lines = [head]
    for off in range(0, len(f.data), width):
        row = f.data[off:off + width]
        hexpart = " ".join(f"{b:02X}" for b in row)
        lines.append(f"    {off:04X}  {hexpart:<{width * 3}} |{ascii_render(row)}|")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# auto-detection
# --------------------------------------------------------------------------

def open_port(port: str, baud: int, bytesize: int, parity: str, stopbits: str, timeout: float):
    """serial_for_url passes plain names like COM3 straight through, and also
    accepts rfc2217://host:port for a networked serial server."""
    ser = serial.serial_for_url(
        port,
        baudrate=baud,
        bytesize=BYTESIZE[bytesize],
        parity=PARITY[parity],
        stopbits=STOPBITS[stopbits],
        timeout=timeout,
        rtscts=False,
        dsrdtr=False,
        xonxoff=False,
    )
    # Never drive the line. Adapters assert these on open by default.
    for attr in ("rts", "dtr"):
        try:
            setattr(ser, attr, False)
        except (OSError, serial.SerialException, NotImplementedError):
            pass
    return ser


def sample(port: str, baud: int, bytesize: int, parity: str, seconds: float,
           stop: threading.Event) -> bytes:
    """Listen briefly at one set of line settings and return whatever arrived.

    Raises SerialException if the port cannot be opened at all -- the caller
    must treat that differently from an open-but-silent line, or it will spin.
    """
    ser = open_port(port, baud, bytesize, parity, "1", 0.1)
    try:
        ser.reset_input_buffer()
        data = bytearray()
        end = time.time() + seconds
        while time.time() < end and not stop.is_set():
            try:
                data += ser.read(512)
            except serial.SerialException:
                break
        return bytes(data)
    finally:
        try:
            ser.close()
        except Exception:
            pass


def score(data: bytes, ascii_mode: bool) -> float:
    """How much does this look like real data rather than baud-mismatch soup?"""
    if not data:
        return 0.0
    if ascii_mode:
        return sum(1 for b in data if b in ASCII_OK) / len(data)
    # Binary protocols: wrong baud yields high entropy and lots of 0x00/0xFF.
    junk = sum(1 for b in data if b in (0x00, 0xFF)) / len(data)
    uniq = len(set(data))
    return (1 - junk) * (1 - min(uniq / 64.0, 1.0))


def wait_for_activity(port: str, cfg, stop: threading.Event) -> bool:
    """Is anything at all arriving on this port?

    A toggling line produces bytes at *any* baud rate, so one cheap listen
    answers this -- far better than a 48-combo sweep that is guaranteed to
    find nothing on a dead line and takes 96s to say so.
    """
    waited = 0.0
    step = 2.0
    while not stop.is_set():
        try:
            if sample(port, 9600, 8, "N", step, stop):
                return True
        except serial.SerialException as e:
            print(f"[!] {port}: cannot be opened -- another program has it "
                  f"(an earlier rs232_tap still running?), or it is not a real "
                  f"serial device.\n    {e}", file=sys.stderr)
            return False

        waited += step
        if waited <= step or waited % 20 < step:
            print(f"[*] {port}: silent for {waited:.0f}s -- nothing is reaching pin 2. "
                  f"Waiting. Check the tap wire, the ground, and that the PLC is "
                  f"actually transmitting.", file=sys.stderr)
        if cfg.detect_wait and waited >= cfg.detect_wait:
            print(f"[!] {port}: no activity after {waited:.0f}s, giving up.", file=sys.stderr)
            return False
    return False


def detect(port: str, cfg, stop: threading.Event) -> Link | None:
    """Cycle through every candidate setting until the data decodes.

    Keeps looping over the full list rather than giving up after one pass:
    a PLC that polls every few seconds can easily stay silent through an
    otherwise-correct candidate.
    """
    combos = [(b, bs, par) for b in AUTO_BAUDS for bs, par in AUTO_FRAMING]
    mode = "ASCII" if cfg.ascii_mode else "binary"
    # Don't sweep a dead line -- confirm there is traffic first.
    if not wait_for_activity(port, cfg, stop):
        return None

    print(f"[*] {port}: traffic seen. Detecting ({len(combos)} combinations, "
          f"{cfg.detect_seconds:g}s each, scoring as {mode}). Ctrl+C to stop.",
          file=sys.stderr)

    best: tuple[float, int, int, str, bytes] | None = None
    silent = True

    for pass_no in itertools.count(1):
        pass_start = time.time()
        open_failures = 0
        open_error = None

        for baud, bytesize, parity in combos:
            if stop.is_set():
                return None
            try:
                data = sample(port, baud, bytesize, parity, cfg.detect_seconds, stop)
            except serial.SerialException as e:
                open_failures += 1
                open_error = e
                continue
            if len(data) < cfg.detect_min_bytes:
                continue
            silent = False
            s = score(data, cfg.ascii_mode)
            print(f"    {baud:>6} {bytesize}{parity}1  {len(data):>5}B  {s:>4.0%}  "
                  f"|{ascii_render(data[:40])}|", file=sys.stderr)
            if best is None or s > best[0]:
                best = (s, baud, bytesize, parity, data)
            if s >= cfg.detect_threshold:
                preview = ascii_render(data[:48])
                print(f"[+] {port}: locked {baud} {bytesize}{parity}1 "
                      f"({s:.0%} clean, {len(data)}B)  |{preview}|", file=sys.stderr)
                return Link(port, port, baud, bytesize, parity, "1")

        # An unopenable port never blocks, so retrying it would spin forever.
        if open_failures == len(combos):
            print(f"[!] {port}: cannot be opened -- in use by another program, or not a "
                  f"real serial device ({open_error}). Skipping.", file=sys.stderr)
            return None

        # Belt and braces: never let a pass complete fast enough to busy-loop.
        if time.time() - pass_start < 1.0:
            time.sleep(1.0)

        if silent:
            print(f"[!] {port}: pass {pass_no} saw no data at all. Check the tap wiring, "
                  f"ground, and that the link is active.", file=sys.stderr)
        else:
            s, baud, bytesize, parity, data = best  # type: ignore[misc]
            print(f"[!] {port}: pass {pass_no} found nothing above "
                  f"{cfg.detect_threshold:.0%}. Best so far {baud} {bytesize}{parity}1 "
                  f"at {s:.0%}: |{ascii_render(data[:48])}|", file=sys.stderr)
            if cfg.detect_passes and pass_no >= cfg.detect_passes:
                print(f"[!] {port}: giving up after {pass_no} passes, using best guess.",
                      file=sys.stderr)
                return Link(port, port, baud, bytesize, parity, "1")
        if cfg.detect_passes and pass_no >= cfg.detect_passes:
            return None
    return None


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------

def reader(link: Link, color: str, cfg, out_q: queue.Queue, stop: threading.Event,
           raw_dir: str | None, stats: dict):
    """One thread per tap. Splits the byte stream into frames on an idle gap."""
    try:
        ser = open_port(link.port, link.baud, link.bytesize, link.parity,
                        link.stopbits, cfg.gap / 1000.0)
    except serial.SerialException as e:
        print(f"[!] {link.label}: cannot open {link.port}: {e}", file=sys.stderr)
        if "denied" in str(e).lower():
            print(f"[!] That usually means another program already has {link.port} open -- "
                  f"most often an earlier rs232_tap that is still running.\n"
                  f"    Check with:  Get-CimInstance Win32_Process -Filter \"Name like "
                  f"'%python%'\" | Select-Object ProcessId, CommandLine", file=sys.stderr)
        stop.set()
        return

    ser.reset_input_buffer()
    print(f"[+] {link.label}: listening on {link.port} at {link.settings()}", file=sys.stderr)

    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in link.label)
    raw = open(os.path.join(raw_dir, f"{safe}.bin"), "ab") if raw_dir else None
    buf = bytearray()
    started = 0.0

    try:
        while not stop.is_set():
            try:
                chunk = ser.read(1)
                if chunk:
                    pending = ser.in_waiting
                    if pending:
                        chunk += ser.read(pending)
            except serial.SerialException as e:
                print(f"[!] {link.label}: read failed ({e}) -- adapter unplugged?", file=sys.stderr)
                stop.set()
                break

            if chunk:
                if not buf:
                    started = time.time()
                buf += chunk
                stats[link.label] = stats.get(link.label, 0) + len(chunk)
                if raw:
                    raw.write(chunk)
                # A line that never goes idle would buffer forever; cap it.
                while len(buf) >= cfg.max_frame:
                    out_q.put(Frame(started, link.label, color, bytes(buf[:cfg.max_frame]), None))
                    del buf[:cfg.max_frame]
                    started = time.time()
            elif buf:
                out_q.put(Frame(started, link.label, color, bytes(buf), None))
                buf.clear()
    finally:
        if buf:
            out_q.put(Frame(started, link.label, color, bytes(buf), None))
        if raw:
            raw.close()
        ser.close()


def writer(out_q: queue.Queue, stop: threading.Event, cfg, logf, jsonf):
    """Single output thread. Holds frames briefly so two taps interleave in
    true timestamp order rather than thread-scheduling order."""
    hold = max(cfg.gap * 2, 40) / 1000.0
    pending: list[Frame] = []
    last_ts: float | None = None
    use_color = cfg.color

    def emit(f: Frame):
        nonlocal last_ts
        f.gap_ms = None if last_ts is None else (f.ts - last_ts) * 1000.0
        last_ts = f.ts
        print(format_frame(f, cfg.width, use_color), flush=True)
        if logf:
            logf.write(format_frame(f, cfg.width, False) + "\n")
            logf.flush()
        if jsonf:
            jsonf.write(json.dumps({
                "ts": round(f.ts, 6),
                "iso": datetime.fromtimestamp(f.ts).isoformat(),
                "dir": f.label,
                "len": len(f.data),
                "hex": f.data.hex(),
                "ascii": ascii_render(f.data),
            }) + "\n")
            jsonf.flush()

    while True:
        draining = stop.is_set()
        try:
            item = out_q.get(timeout=0.05)
            if item is None:
                draining = True
            else:
                pending.append(item)
        except queue.Empty:
            if draining and not pending:
                return

        pending.sort(key=lambda x: x.ts)
        now = time.time()
        while pending and (draining or pending[0].ts + hold <= now):
            emit(pending.pop(0))

        if draining and out_q.empty() and not pending:
            return


# --------------------------------------------------------------------------

def parse_port(spec: str) -> tuple[str, str | None]:
    """'COM3=PLC-OUT' -> ('COM3', 'PLC-OUT');  'COM3' -> ('COM3', None)"""
    if "=" in spec:
        port, label = spec.split("=", 1)
        return port.strip(), label.strip()
    return spec.strip(), None


def discover_ports() -> list[str]:
    return [p.device for p in list_ports.comports()]


def show_ports():
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found. Plug in the USB adapter and try again.")
        return
    for p in ports:
        print(f"{p.device:<8} {p.description}")
        if p.hwid and p.hwid != "n/a":
            print(f"{'':<8} {p.hwid}")


def main():
    ap = argparse.ArgumentParser(
        description="Passive RS232 tap. With no arguments it finds the adapters and "
                    "line settings by itself, then logs both directions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Wire tap RXD (DB9 pin 2) to the line you want to watch and tap GND "
               "(pin 5) to the link's signal ground. Leave pin 3 disconnected.")
    ap.add_argument("-p", "--port", action="append", default=[], metavar="COMx[=LABEL]",
                    help="tap to listen on; repeat for the second direction. Omit to use "
                         "every port found. Labels are optional; avoid '>' in them, "
                         "PowerShell reads it as redirection.")
    ap.add_argument("-b", "--baud", type=int,
                    help="baud rate. Omit to auto-detect.")
    ap.add_argument("--bytesize", type=int, choices=[5, 6, 7, 8], help="data bits (default auto)")
    ap.add_argument("--parity", choices=list(PARITY), help="parity (default auto)")
    ap.add_argument("--stopbits", choices=list(STOPBITS), default="1", help="stop bits (default 1)")
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
    ap.add_argument("--detect-only", action="store_true",
                    help="report the detected settings and exit without capturing")
    ap.add_argument("--gap", type=float, default=15.0, metavar="MS",
                    help="idle time that ends a frame, in ms (default 15). Modbus RTU wants "
                         "about 3.5 character times: ~4ms at 9600, ~2ms at 19200.")
    ap.add_argument("--max-frame", type=int, default=4096, help="force a frame break after N bytes")
    ap.add_argument("--width", type=int, default=16, help="hex bytes per line (default 16)")
    ap.add_argument("--log", metavar="FILE", help="text log path (default logs/tap-<timestamp>.log)")
    ap.add_argument("--jsonl", metavar="FILE", help="also write one JSON object per frame")
    ap.add_argument("--raw-dir", metavar="DIR", help="also dump the raw byte stream per direction")
    ap.add_argument("--no-log", action="store_true", help="console only, no log file")
    ap.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    cfg = ap.parse_args()
    cfg.color = not cfg.no_color and sys.stdout.isatty()
    cfg.ascii_mode = not cfg.binary

    if cfg.list:
        show_ports()
        return

    # Which ports? Whatever was asked for, else everything present.
    if cfg.port:
        requested = [parse_port(s) for s in cfg.port]
    else:
        found = discover_ports()
        if not found:
            sys.exit("No serial ports found. Plug in the USB adapter and try again.")
        print(f"[*] found {len(found)} port(s): {', '.join(found)}", file=sys.stderr)
        requested = [(p, None) for p in found]

    stop = threading.Event()

    # Settings: use whatever was given on the command line, detect the rest.
    manual = cfg.baud is not None
    links: list[Link] = []
    try:
        for port, label in requested:
            if manual:
                link = Link(port, label or port, cfg.baud,
                            cfg.bytesize or 8, cfg.parity or "N", cfg.stopbits)
            else:
                found_link = detect(port, cfg, stop)
                if found_link is None:
                    print(f"[!] {port}: no settings found, skipping.", file=sys.stderr)
                    continue
                link = found_link
                if label:
                    link.label = label
                if cfg.bytesize:
                    link.bytesize = cfg.bytesize
                if cfg.parity:
                    link.parity = cfg.parity
            links.append(link)
    except KeyboardInterrupt:
        print("\n[+] detection cancelled", file=sys.stderr)
        return

    if not links:
        sys.exit("No usable taps. Check wiring and that the link is carrying traffic.")

    if cfg.detect_only:
        print("\nDetected settings:")
        for l in links:
            print(f"  {l.port:<10} {l.settings()}")
        print("\nCapture with:  python rs232_tap.py " +
              " ".join(f"-p {l.port}" for l in links) +
              f" -b {links[0].baud} --bytesize {links[0].bytesize} --parity {links[0].parity}")
        return

    here = os.path.dirname(os.path.abspath(__file__))
    logf = jsonf = None
    if not cfg.no_log:
        path = cfg.log or os.path.join(here, "logs", f"tap-{datetime.now():%Y%m%d-%H%M%S}.log")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        logf = open(path, "a", encoding="utf-8")
        logf.write(f"\n# rs232_tap {datetime.now().isoformat()} gap={cfg.gap}ms "
                   + " ".join(f"{l.label}={l.port}@{l.settings()}" for l in links) + "\n")
        logf.flush()
        print(f"[+] logging to {path}", file=sys.stderr)
    if cfg.jsonl:
        os.makedirs(os.path.dirname(os.path.abspath(cfg.jsonl)) or ".", exist_ok=True)
        jsonf = open(cfg.jsonl, "a", encoding="utf-8")
    if cfg.raw_dir:
        os.makedirs(cfg.raw_dir, exist_ok=True)

    out_q: queue.Queue = queue.Queue()
    stats: dict[str, int] = {}
    threads = []

    for i, link in enumerate(links):
        t = threading.Thread(target=reader,
                             args=(link, COLORS[i % len(COLORS)], cfg, out_q,
                                   stop, cfg.raw_dir, stats),
                             daemon=True, name=f"tap-{link.label}")
        t.start()
        threads.append(t)

    w = threading.Thread(target=writer, args=(out_q, stop, cfg, logf, jsonf),
                         daemon=True, name="writer")
    w.start()

    print(f"[+] frame gap {cfg.gap}ms. Ctrl+C to stop.\n", file=sys.stderr)
    started = time.time()

    try:
        while not stop.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        out_q.put(None)
        w.join(timeout=3)
        for t in threads:
            t.join(timeout=2)
        elapsed = time.time() - started
        print(f"\n[+] stopped after {elapsed:.1f}s", file=sys.stderr)
        for label, n in stats.items():
            print(f"    {label:<12} {n} bytes ({n / max(elapsed, 1):.1f} B/s)", file=sys.stderr)
        if not stats:
            print("    no data captured -- check wiring, ground, and that the link is active",
                  file=sys.stderr)
        for f in (logf, jsonf):
            if f:
                f.close()


if __name__ == "__main__":
    main()
