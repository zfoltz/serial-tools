"""Automatic line-setting detection: brute-force baud/framing until it decodes.

Ported intact from rs232_tap.py -- the scoring and pass/retry behavior are
field-proven; only the config plumbing changed (DetectOptions instead of the
CLI namespace).
"""

from __future__ import annotations

import itertools
import sys
import threading
import time
from dataclasses import dataclass

import serial

from .frames import LinkConfig, ascii_render
from .ports import open_port

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


@dataclass
class DetectOptions:
    ascii_mode: bool = True         # False = score as a binary protocol
    seconds: float = 2.0            # listen time per candidate setting
    threshold: float = 0.95         # clean fraction required to lock on
    min_bytes: int = 8              # ignore samples shorter than this
    passes: int = 0                 # give up after N full sweeps (0 = forever)
    wait: float = 0                 # give up if silent this long before starting (0 = forever)


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


def wait_for_activity(port: str, opts: DetectOptions, stop: threading.Event) -> bool:
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
                  f"(an earlier tap still running?), or it is not a real "
                  f"serial device.\n    {e}", file=sys.stderr)
            return False

        waited += step
        if waited <= step or waited % 20 < step:
            print(f"[*] {port}: silent for {waited:.0f}s -- nothing is reaching pin 2. "
                  f"Waiting. Check the tap wire, the ground, and that the PLC is "
                  f"actually transmitting.", file=sys.stderr)
        if opts.wait and waited >= opts.wait:
            print(f"[!] {port}: no activity after {waited:.0f}s, giving up.", file=sys.stderr)
            return False
    return False


def detect(port: str, opts: DetectOptions, stop: threading.Event) -> LinkConfig | None:
    """Cycle through every candidate setting until the data decodes.

    Keeps looping over the full list rather than giving up after one pass:
    a PLC that polls every few seconds can easily stay silent through an
    otherwise-correct candidate.
    """
    combos = [(b, bs, par) for b in AUTO_BAUDS for bs, par in AUTO_FRAMING]
    mode = "ASCII" if opts.ascii_mode else "binary"
    # Don't sweep a dead line -- confirm there is traffic first.
    if not wait_for_activity(port, opts, stop):
        return None

    print(f"[*] {port}: traffic seen. Detecting ({len(combos)} combinations, "
          f"{opts.seconds:g}s each, scoring as {mode}). Ctrl+C to stop.",
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
                data = sample(port, baud, bytesize, parity, opts.seconds, stop)
            except serial.SerialException as e:
                open_failures += 1
                open_error = e
                continue
            if len(data) < opts.min_bytes:
                continue
            silent = False
            s = score(data, opts.ascii_mode)
            print(f"    {baud:>6} {bytesize}{parity}1  {len(data):>5}B  {s:>4.0%}  "
                  f"|{ascii_render(data[:40])}|", file=sys.stderr)
            if best is None or s > best[0]:
                best = (s, baud, bytesize, parity, data)
            if s >= opts.threshold:
                preview = ascii_render(data[:48])
                print(f"[+] {port}: locked {baud} {bytesize}{parity}1 "
                      f"({s:.0%} clean, {len(data)}B)  |{preview}|", file=sys.stderr)
                return LinkConfig(port, port, baud, bytesize, parity, "1",
                                  detected=True, detect_score=s)

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
                  f"{opts.threshold:.0%}. Best so far {baud} {bytesize}{parity}1 "
                  f"at {s:.0%}: |{ascii_render(data[:48])}|", file=sys.stderr)
            if opts.passes and pass_no >= opts.passes:
                print(f"[!] {port}: giving up after {pass_no} passes, using best guess.",
                      file=sys.stderr)
                return LinkConfig(port, port, baud, bytesize, parity, "1",
                                  detected=True, detect_score=s)
        if opts.passes and pass_no >= opts.passes:
            return None
    return None
