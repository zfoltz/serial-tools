"""Frame sources: things that produce Frames for a CaptureSession.

SerialSource is rs232_tap.py's reader() -- one live tap, split into frames on
an idle gap. ReplaySource plays a stored capture back through the same
pipeline, which is how everything downstream gets developed without hardware.
"""

from __future__ import annotations

import sys
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Iterable

import serial

from .frames import Frame, LinkConfig
from .ports import open_port

EmitFn = Callable[[Frame], None]


class FrameSource(ABC):
    label: str = "?"

    @abstractmethod
    def run(self, emit: EmitFn, stop: threading.Event) -> None:
        """Produce frames until stop is set or the source is exhausted.
        Runs in its own thread; must set `stop` on unrecoverable errors."""


class SerialSource(FrameSource):
    """One live tap. Splits the byte stream into frames on an idle gap."""

    def __init__(self, link: LinkConfig, gap_ms: float = 15.0, max_frame: int = 4096,
                 on_bytes: Callable[[str, bytes], None] | None = None):
        self.link = link
        self.label = link.label
        self.gap_ms = gap_ms
        self.max_frame = max_frame
        self.on_bytes = on_bytes  # raw-chunk hook: stats, raw dumps

    def run(self, emit: EmitFn, stop: threading.Event) -> None:
        link = self.link
        try:
            ser = open_port(link.port, link.baud, link.bytesize, link.parity,
                            link.stopbits, self.gap_ms / 1000.0)
        except serial.SerialException as e:
            print(f"[!] {link.label}: cannot open {link.port}: {e}", file=sys.stderr)
            if "denied" in str(e).lower():
                print(f"[!] That usually means another program already has {link.port} open -- "
                      f"most often an earlier tap that is still running.\n"
                      f"    Check with:  Get-CimInstance Win32_Process -Filter \"Name like "
                      f"'%python%'\" | Select-Object ProcessId, CommandLine", file=sys.stderr)
            stop.set()
            return

        ser.reset_input_buffer()
        print(f"[+] {link.label}: listening on {link.port} at {link.settings()}", file=sys.stderr)

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
                    print(f"[!] {link.label}: read failed ({e}) -- adapter unplugged?",
                          file=sys.stderr)
                    stop.set()
                    break

                if chunk:
                    if not buf:
                        started = time.time()
                    buf += chunk
                    if self.on_bytes:
                        self.on_bytes(link.label, bytes(chunk))
                    # A line that never goes idle would buffer forever; cap it.
                    while len(buf) >= self.max_frame:
                        emit(Frame(started, link.label, bytes(buf[:self.max_frame])))
                        del buf[:self.max_frame]
                        started = time.time()
                elif buf:
                    emit(Frame(started, link.label, bytes(buf)))
                    buf.clear()
        finally:
            if buf:
                emit(Frame(started, link.label, bytes(buf)))
            ser.close()


class ReplaySource(FrameSource):
    """Feed stored frames back into the pipeline.

    speed > 1 compresses the original timing; realtime=False emits as fast as
    possible (for tests). Timestamps are rebased to now so downstream gap and
    ordering logic behaves exactly as it would live.
    """

    def __init__(self, frames: Iterable[Frame], label: str | None = None,
                 speed: float = 1.0, realtime: bool = True, rebase: bool = True):
        self.frames = list(frames)
        self.label = label or (self.frames[0].src if self.frames else "REPLAY")
        self.speed = max(speed, 1e-6)
        self.realtime = realtime
        self.rebase = rebase

    def run(self, emit: EmitFn, stop: threading.Event) -> None:
        if not self.frames:
            return
        t0 = self.frames[0].ts
        wall0 = time.time()
        for f in self.frames:
            if stop.is_set():
                return
            rel = (f.ts - t0) / self.speed
            if self.realtime:
                delay = wall0 + rel - time.time()
                if delay > 0:
                    # Sleep in slices so stop stays responsive.
                    end = time.time() + delay
                    while not stop.is_set():
                        remaining = end - time.time()
                        if remaining <= 0:
                            break
                        time.sleep(min(remaining, 0.1))
                    if stop.is_set():
                        return
            ts = (wall0 + rel) if self.rebase else f.ts
            emit(Frame(ts, f.src, f.data, dir=f.dir, dir_conf=f.dir_conf))
