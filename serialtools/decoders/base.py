"""Decoder plugin interface.

A decoder turns one frame of bytes into a Decoded annotation. Semantics:

- decode() returns None when the bytes are clearly not this protocol.
- Decoded.ok means INTEGRITY: framing recognized and checksum/CRC valid.
- Decoded.errors carries both integrity problems ("crc_mismatch",
  "short_frame", "no_terminator", "checksum_mismatch") and conformance
  notes ("unknown_message", "unexpected_response"). Analyzers separate the
  two by name; ok reflects integrity only.
- Decoded.role feeds direction inference on 2-wire RS485 taps.
- prev is the previous Decoded on the same link, so a response can be
  interpreted in the context of the request it answers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

INTEGRITY_ERRORS = {"crc_mismatch", "checksum_mismatch", "short_frame",
                    "no_terminator", "bad_framing", "bad_hex", "non_ascii"}


@dataclass
class Decoded:
    proto: str
    ok: bool
    summary: str
    role: str | None = None  # "request" | "response" | None
    fields: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        d = {"proto": self.proto, "ok": self.ok, "summary": self.summary}
        if self.role:
            d["role"] = self.role
        if self.fields:
            d["fields"] = self.fields
        if self.errors:
            d["errors"] = self.errors
        return d


class Decoder(ABC):
    name: str = "?"

    def resplit(self, data: bytes) -> list[bytes] | None:
        """Optionally re-frame a blob the idle-gap splitter merged wrongly
        (e.g. a Modbus RTU length+CRC-guided scan). None = keep as-is."""
        return None

    @abstractmethod
    def decode(self, data: bytes, prev: Decoded | None = None) -> Decoded | None:
        ...
