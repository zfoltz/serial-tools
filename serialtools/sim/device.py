"""Device simulator: answer live requests on a port the way the real device
did in a capture (or the way a profile's [sim] table says to).

Lets PLC code be exercised against a simulated valve/drive: point the PLC's
serial line at the laptop, run

    serialtools sim captures\\20260819-good-run --port COM7

Request matching is on exact bytes first, then on the text with framing
stripped, so a PLC sending CRLF still matches a capture made with CR.
"""

from __future__ import annotations

import sys
import time

from ..core.direction import MASTER
from ..core.frames import Frame, ascii_render
from ..analyze.timing import _request_dir
from .replay import open_tx


def _norm(data: bytes) -> bytes:
    return data.strip(b"\r\n\x00")


class DeviceSimulator:
    def __init__(self, table: dict[bytes, bytes], terminator: bytes = b"",
                 delay_ms: float = 20.0):
        self.table = table
        self.norm_table = {_norm(k): v for k, v in table.items()}
        self.terminator = terminator
        self.delay_ms = delay_ms

    @classmethod
    def from_capture(cls, frames: list[Frame], delay_ms: float = 20.0) -> "DeviceSimulator":
        """Pair each request with the response that followed it; latest wins."""
        req_dir = MASTER if any(f.dir == MASTER for f in frames) else _request_dir(frames)
        if req_dir is None:
            sys.exit("cannot tell requests from responses in this capture -- "
                     "run `serialtools decode` on it first (roles feed the pairing)")
        table: dict[bytes, bytes] = {}
        pending: Frame | None = None
        latencies = []
        for f in frames:
            if f.dir == req_dir:
                pending = f
            elif pending is not None:
                table[pending.data] = f.data
                latencies.append((f.ts - pending.ts) * 1000.0)
                pending = None
        if not table:
            sys.exit("no request/response pairs found in the capture")
        if latencies:
            latencies.sort()
            delay_ms = latencies[len(latencies) // 2]
        return cls(table, delay_ms=delay_ms)

    @classmethod
    def from_profile(cls, profile: dict, delay_ms: float = 20.0) -> "DeviceSimulator":
        sim = profile.get("sim", {})
        if not sim:
            sys.exit(f"profile {profile.get('device', {}).get('name', '?')!r} has no "
                     f"[sim] table -- add one:\n  [sim]\n  CP = \"CP01\"\n"
                     f"or build the simulator from a capture instead")
        from ..decoders.ascii_profile import _to_bytes
        term = _to_bytes(profile.get("framing", {}).get("terminator", "CR"))
        table = {req.encode("latin-1") + term: resp.encode("latin-1") + term
                 for req, resp in sim.items()}
        return cls(table, terminator=term, delay_ms=delay_ms)

    def lookup(self, request: bytes) -> bytes | None:
        return self.table.get(request) or self.norm_table.get(_norm(request))

    def serve(self, port: str, baud: int, bytesize: int = 8, parity: str = "N",
              gap_ms: float = 15.0) -> None:
        ser = open_tx(port, baud, bytesize, parity)
        ser.timeout = gap_ms / 1000.0
        print(f"[+] simulating device on {port} @ {baud} {bytesize}{parity}1, "
              f"{len(self.table)} known requests, reply delay {self.delay_ms:.0f}ms. "
              f"Ctrl+C to stop.", file=sys.stderr)
        buf = bytearray()
        try:
            while True:
                chunk = ser.read(1)
                if chunk:
                    buf += chunk
                    buf += ser.read(ser.in_waiting)
                    if self.terminator and buf.endswith(self.terminator):
                        self._answer(ser, bytes(buf))
                        buf.clear()
                elif buf:  # idle gap ends the request when there's no terminator
                    self._answer(ser, bytes(buf))
                    buf.clear()
        except KeyboardInterrupt:
            pass
        finally:
            ser.close()

    def _answer(self, ser, request: bytes) -> None:
        response = self.lookup(request)
        stamp = time.strftime("%H:%M:%S")
        if response is None:
            print(f"{stamp}  ?? |{ascii_render(request)}| unknown request, no reply",
                  file=sys.stderr)
            return
        time.sleep(self.delay_ms / 1000.0)
        ser.write(response)
        ser.flush()
        print(f"{stamp}  |{ascii_render(request)}| -> |{ascii_render(response)}|",
              file=sys.stderr)
