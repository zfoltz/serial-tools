"""Console output: frame formatting and sinks.

Default output is plain scrolling text, exactly rs232_tap.py's format (it
works redirected and over remote shells), with an optional decode-summary
line. LiveView (--live, needs rich) pins a small status header above it.
"""

from __future__ import annotations

import sys
import time

from ..core.frames import Frame, ascii_render

COLORS = ["\033[36m", "\033[33m", "\033[35m", "\033[32m"]  # cyan, yellow, magenta, green
DIM = "\033[2m"
RED = "\033[31m"
RESET = "\033[0m"


def _decode_line(frame: Frame, use_color: bool) -> str:
    d = frame.decode
    if d is None:
        return ""
    if not isinstance(d, dict):
        d = d.to_json()
    mark = "ok " if d.get("ok") else "ERR"
    text = f"{'':>23}  {mark} {d.get('proto', '?')}: {d.get('summary', '')}"
    if d.get("errors"):
        text += f"  [{', '.join(d['errors'])}]"
    if use_color:
        color = DIM if d.get("ok") else RED
        return f"\n{color}{text}{RESET}"
    return "\n" + text


def format_frame(frame: Frame, width: int = 16, use_color: bool = False,
                 color: str = "") -> str:
    from datetime import datetime
    stamp = datetime.fromtimestamp(frame.ts).strftime("%H:%M:%S.%f")[:-3]
    gap = f"+{frame.gap_ms:8.1f}ms" if frame.gap_ms is not None else " " * 11
    label = frame.dir if frame.dir else frame.src
    if frame.dir_conf < 1.0:
        label = f"{label}?"
    head = f"{stamp} {gap}  {label:<9} {len(frame.data):>4}B"
    if use_color:
        head = (f"{DIM}{stamp} {gap}{RESET}  {color}{label:<9}{RESET} "
                f"{DIM}{len(frame.data):>4}B{RESET}")

    if len(frame.data) <= width:
        hexpart = " ".join(f"{b:02X}" for b in frame.data)
        body = f"{head}  {hexpart:<{width * 3}} |{ascii_render(frame.data)}|"
    else:
        lines = [head]
        for off in range(0, len(frame.data), width):
            row = frame.data[off:off + width]
            hexpart = " ".join(f"{b:02X}" for b in row)
            lines.append(f"    {off:04X}  {hexpart:<{width * 3}} |{ascii_render(row)}|")
        body = "\n".join(lines)
    return body + _decode_line(frame, use_color)


class ColorMap:
    """Stable label -> ANSI color assignment."""

    def __init__(self):
        self._map: dict[str, str] = {}

    def get(self, label: str) -> str:
        if label not in self._map:
            self._map[label] = COLORS[len(self._map) % len(COLORS)]
        return self._map[label]


def console_sink(width: int = 16, use_color: bool = True, file=None):
    colors = ColorMap()
    out = file or sys.stdout

    def sink(frame: Frame):
        print(format_frame(frame, width, use_color, colors.get(frame.dir)),
              file=out, flush=True)
    return sink


def text_formatter(width: int = 16):
    """Formatter for the tap.log file: same layout, no color."""
    return lambda frame: format_frame(frame, width, use_color=False)


class LiveView:
    """rich-based wrapper: pinned status header, frames scroll above it.

    Usage: view = LiveView(session); session.add_sink(view.sink);
    view.start(); ... view.stop()
    """

    def __init__(self, session, width: int = 16):
        try:
            from rich.console import Console
            from rich.live import Live
            from rich.text import Text
        except ImportError:
            raise SystemExit("--live needs rich. Run:  python -m pip install rich")
        self._Text = Text
        self.console = Console()
        self.session = session
        self.width = width
        self.colors = ColorMap()
        self.decode_errors = 0
        self.last_frame_at: float | None = None
        self.live = Live(self._render(), console=self.console,
                         refresh_per_second=4, transient=True)

    def _render(self):
        s = self.session
        parts = [f"{label}: {n}B ({n / max(s.elapsed(), 1):.0f} B/s)"
                 for label, n in sorted(s.stats.items())]
        silence = (time.time() - self.last_frame_at) if self.last_frame_at else None
        line1 = "  ".join(parts) or "waiting for data..."
        line2 = (f"frames {s.frame_count}   decode errors {self.decode_errors}   "
                 f"silent {silence:.1f}s" if silence is not None
                 else f"frames {s.frame_count}   decode errors {self.decode_errors}")
        text = self._Text()
        text.append(line1 + "\n", style="bold")
        style2 = "red" if (silence or 0) > 10 or self.decode_errors else "dim"
        text.append(line2, style=style2)
        return text

    def sink(self, frame: Frame):
        self.last_frame_at = time.time()
        d = frame.decode
        if d is not None:
            ok = d.get("ok") if isinstance(d, dict) else d.ok
            if not ok:
                self.decode_errors += 1
        self.console.print(format_frame(frame, self.width, use_color=False))
        self.live.update(self._render())

    def start(self):
        self.live.start()

    def tick(self):
        self.live.update(self._render())

    def stop(self):
        self.live.stop()
