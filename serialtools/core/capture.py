"""CaptureSession: sources in, ordered/annotated frames out to pluggable sinks.

The writer keeps rs232_tap.py's hold-and-sort trick: frames are held briefly
so two taps interleave in true timestamp order rather than thread-scheduling
order. It then assigns the monotonic seq, computes the inter-frame gap, runs
any transforms (live decoder, direction inference), and fans out to sinks.

A sink is any callable taking a Frame. A transform is any callable taking a
Frame and mutating it in place (e.g. setting frame.decode or frame.dir).
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from typing import Callable

from .frames import Frame, WIRING_MODES
from .sources import FrameSource

Sink = Callable[[Frame], None]
Transform = Callable[[Frame], None]


class CaptureSession:
    def __init__(self, sources: list[FrameSource], wiring: str = "rs232",
                 gap_ms: float = 15.0, sinks: list[Sink] | None = None,
                 transforms: list[Transform] | None = None):
        if wiring not in WIRING_MODES:
            raise ValueError(f"wiring must be one of {WIRING_MODES}, not {wiring!r}")
        self.sources = sources
        self.wiring = wiring
        self.gap_ms = gap_ms
        self.sinks: list[Sink] = list(sinks or [])
        self.transforms: list[Transform] = list(transforms or [])
        self.stats: dict[str, int] = {}   # label -> bytes seen
        self.frame_count = 0
        self.started_at: float | None = None
        self.stop = threading.Event()
        self._q: queue.Queue = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._writer_thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def add_sink(self, sink: Sink) -> None:
        self.sinks.append(sink)

    def start(self) -> None:
        self.started_at = time.time()
        for src in self.sources:
            t = threading.Thread(target=self._run_source, args=(src,),
                                 daemon=True, name=f"tap-{src.label}")
            t.start()
            self._threads.append(t)
        self._writer_thread = threading.Thread(target=self._writer, daemon=True, name="writer")
        self._writer_thread.start()

    def _run_source(self, src: FrameSource) -> None:
        try:
            src.run(lambda f: self._q.put((f, time.time())), self.stop)
        except Exception as e:  # a crashed source must not hang the session
            print(f"[!] {src.label}: source failed: {e}", file=sys.stderr)
            self.stop.set()

    def request_stop(self) -> None:
        self.stop.set()
        self._q.put(None)

    def join(self, timeout: float = 5.0) -> None:
        self.request_stop()
        if self._writer_thread:
            self._writer_thread.join(timeout=timeout)
        for t in self._threads:
            t.join(timeout=2)

    @property
    def running(self) -> bool:
        return self._writer_thread is not None and self._writer_thread.is_alive()

    def elapsed(self) -> float:
        return time.time() - self.started_at if self.started_at else 0.0

    def run_until_interrupt(self) -> None:
        """Foreground mode for the CLI: block until Ctrl+C or a source dies."""
        try:
            while not self.stop.is_set():
                # Replay sessions end on their own once every source finishes.
                if all(not t.is_alive() for t in self._threads):
                    break
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            self.join()

    # -- the writer --------------------------------------------------------

    def _writer(self) -> None:
        # Frames are held for `hold` after ARRIVAL (not their timestamp -- a
        # replayed capture carries old timestamps) so that two taps interleave
        # in true timestamp order rather than thread-scheduling order.
        hold = max(self.gap_ms * 2, 40) / 1000.0
        pending: list[tuple[Frame, float]] = []
        last_ts: float | None = None
        seq = 0

        def emit(f: Frame):
            nonlocal last_ts, seq
            f.seq = seq
            seq += 1
            f.gap_ms = None if last_ts is None else (f.ts - last_ts) * 1000.0
            last_ts = f.ts
            self.stats[f.src] = self.stats.get(f.src, 0) + len(f.data)
            for tf in self.transforms:
                try:
                    tf(f)
                except Exception as e:
                    print(f"[!] transform {tf!r} failed on frame {f.seq}: {e}", file=sys.stderr)
            self.frame_count += 1
            for sink in self.sinks:
                try:
                    sink(f)
                except Exception as e:
                    print(f"[!] sink {sink!r} failed on frame {f.seq}: {e}", file=sys.stderr)

        while True:
            draining = self.stop.is_set()
            try:
                item = self._q.get(timeout=0.05)
                if item is None:
                    draining = True
                else:
                    pending.append(item)
            except queue.Empty:
                if draining and not pending:
                    return

            pending.sort(key=lambda x: x[0].ts)
            now = time.time()
            while pending and (draining or pending[0][1] + hold <= now):
                emit(pending.pop(0)[0])

            if draining and self._q.empty() and not pending:
                return
