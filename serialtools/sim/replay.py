"""Replay a stored capture onto a real (or com0com virtual) serial port,
preserving the original inter-frame timing. The standard way to develop and
demo against real traffic with no plant in sight:

    serialtools replay captures\\20260819-... --port COM20
    serialtools tap -p COM21            # in another window
"""

from __future__ import annotations

import sys
import time

import serial

from ..core.frames import Frame
from ..core.ports import BYTESIZE, PARITY, STOPBITS


def open_tx(port: str, baud: int, bytesize: int = 8, parity: str = "N",
            stopbits: str = "1"):
    """A port we intend to WRITE to -- unlike ports.open_port, which is the
    receive-only tap opener. Never point this at a live production line."""
    return serial.serial_for_url(
        port, baudrate=baud, bytesize=BYTESIZE[bytesize], parity=PARITY[parity],
        stopbits=STOPBITS[stopbits], timeout=0.2,
        rtscts=False, dsrdtr=False, xonxoff=False,
    )


def play(frames: list[Frame], port: str, baud: int, speed: float = 1.0,
         only_dir: str | None = None, loop: bool = False,
         bytesize: int = 8, parity: str = "N") -> int:
    todo = [f for f in frames if only_dir is None or only_dir in (f.dir, f.src)]
    if not todo:
        sys.exit(f"nothing to replay (dir filter {only_dir!r} matched no frames)")
    ser = open_tx(port, baud, bytesize, parity)
    print(f"[+] replaying {len(todo)} frames onto {port} @ {baud} "
          f"{bytesize}{parity}1, speed x{speed:g}"
          + (f", direction {only_dir}" if only_dir else "") + ". Ctrl+C to stop.",
          file=sys.stderr)
    sent = 0
    try:
        while True:
            t0 = todo[0].ts
            wall0 = time.time()
            for f in todo:
                target = wall0 + (f.ts - t0) / max(speed, 1e-6)
                delay = target - time.time()
                if delay > 0:
                    time.sleep(delay)
                ser.write(f.data)
                ser.flush()
                sent += 1
            if not loop:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        print(f"[+] replayed {sent} frames", file=sys.stderr)
    return sent
