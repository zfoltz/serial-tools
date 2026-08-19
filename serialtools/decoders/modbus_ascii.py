"""Modbus ASCII decoder: ':' ... CRLF framing, LRC check, shared PDU parse."""

from __future__ import annotations

from .base import Decoded, Decoder
from .modbus_rtu import parse_pdu


def lrc(data: bytes) -> int:
    return (-sum(data)) & 0xFF


class ModbusAsciiDecoder(Decoder):
    name = "modbus_ascii"

    def decode(self, data: bytes, prev: Decoded | None = None) -> Decoded | None:
        if not data.startswith(b":"):
            return None
        body = data[1:]
        if body.endswith(b"\r\n"):
            body = body[:-2]
        elif body.endswith(b"\r") or body.endswith(b"\n"):
            body = body[:-1]
        else:
            return Decoded(self.name, False, "missing CRLF terminator",
                           errors=["bad_framing"])
        try:
            raw = bytes.fromhex(body.decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            return Decoded(self.name, False, "non-hex payload", errors=["bad_hex"])
        if len(raw) < 3:
            return Decoded(self.name, False, f"short frame ({len(raw)}B)",
                           errors=["short_frame"])
        payload, check = raw[:-1], raw[-1]
        if lrc(payload) != check:
            return Decoded(self.name, False,
                           f"LRC mismatch (addr={payload[0]} fc={payload[1] & 0x7F}?)",
                           fields={"addr": payload[0], "func": payload[1] & 0x7F},
                           errors=["checksum_mismatch"])
        addr, func = payload[0], payload[1]
        role, summary, fields = parse_pdu(addr, func, payload[2:], prev)
        return Decoded(self.name, True, summary, role=role, fields=fields)

    def resplit(self, data: bytes) -> list[bytes] | None:
        """Multiple ':'-framed messages merged into one blob split cleanly."""
        if data.count(b":") < 2:
            return None
        parts = []
        idx = data.find(b":")
        while idx != -1:
            nxt = data.find(b":", idx + 1)
            parts.append(data[idx:nxt] if nxt != -1 else data[idx:])
            idx = nxt
        return parts if len(parts) >= 2 else None
