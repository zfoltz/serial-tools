"""Core dataclasses shared by every serialtools component."""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

PRINTABLE = set(bytes(string.printable[:-5], "ascii"))

WIRING_MODES = ("rs232", "rs485-4w", "rs485-2w")


def ascii_render(data: bytes) -> str:
    return "".join(chr(b) if b in PRINTABLE else "." for b in data)


@dataclass
class LinkConfig:
    """One tap: a port plus the line settings to read it with."""

    port: str
    label: str
    baud: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: str = "1"
    detected: bool = False
    detect_score: float | None = None

    def settings(self) -> str:
        return f"{self.baud} {self.bytesize}{self.parity}{self.stopbits}"

    def to_json(self) -> dict:
        d = {
            "port": self.port,
            "label": self.label,
            "baud": self.baud,
            "framing": f"{self.bytesize}{self.parity}{self.stopbits}",
            "detected": self.detected,
        }
        if self.detect_score is not None:
            d["detect_score"] = round(self.detect_score, 3)
        return d


@dataclass
class Frame:
    """One burst of bytes from one tap, delimited by line idle time.

    `src` is the physical tap the bytes were measured on and is never changed.
    `dir` is the logical direction: on rs232/rs485-4w it equals `src`; on a
    2-wire half-duplex bus it is inferred, with `dir_conf` saying how surely.
    """

    ts: float
    src: str
    data: bytes
    seq: int = -1
    dir: str = ""
    dir_conf: float = 1.0
    gap_ms: float | None = None
    decode: Any = None  # decoders.base.Decoded once a decoder has run

    def __post_init__(self):
        if not self.dir:
            self.dir = self.src

    def to_json(self) -> dict:
        obj = {
            "seq": self.seq,
            "ts": round(self.ts, 6),
            "iso": datetime.fromtimestamp(self.ts).isoformat(),
            "src": self.src,
            "dir": self.dir,
            "len": len(self.data),
            "hex": self.data.hex(),
            "ascii": ascii_render(self.data),
        }
        if self.dir_conf < 1.0:
            obj["dir_conf"] = round(self.dir_conf, 3)
        if self.gap_ms is not None:
            obj["gap_ms"] = round(self.gap_ms, 3)
        return obj

    @classmethod
    def from_json(cls, obj: dict) -> "Frame":
        """Tolerates pre-package rs232_tap.py JSONL, which had no seq/src."""
        dir_ = obj.get("dir", "?")
        return cls(
            ts=obj["ts"],
            src=obj.get("src", dir_),
            data=bytes.fromhex(obj["hex"]),
            seq=obj.get("seq", -1),
            dir=dir_,
            dir_conf=obj.get("dir_conf", 1.0),
            gap_ms=obj.get("gap_ms"),
        )
