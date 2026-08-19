"""Modbus RTU decoder: CRC16 validation, request/response parsing, resplit."""

from __future__ import annotations

from .base import Decoded, Decoder

FUNC_NAMES = {
    1: "read coils", 2: "read discrete inputs", 3: "read holding regs",
    4: "read input regs", 5: "write single coil", 6: "write single reg",
    7: "read exception status", 8: "diagnostics", 11: "get comm event counter",
    15: "write multiple coils", 16: "write multiple regs", 17: "report slave id",
    22: "mask write reg", 23: "read/write multiple regs",
}
EXCEPTIONS = {
    1: "illegal function", 2: "illegal data address", 3: "illegal data value",
    4: "slave device failure", 5: "acknowledge", 6: "slave device busy",
    8: "memory parity error", 10: "gateway path unavailable",
    11: "gateway target failed to respond",
}


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def crc_ok(frame: bytes) -> bool:
    return len(frame) >= 4 and crc16(frame[:-2]) == int.from_bytes(frame[-2:], "little")


def parse_pdu(addr: int, func: int, body: bytes,
              prev: Decoded | None) -> tuple[str | None, str, dict]:
    """Interpret a Modbus PDU (no CRC). Shared by RTU and ASCII decoders.
    Returns (role, summary, fields)."""
    fields: dict = {"addr": addr, "func": func & 0x7F}
    fname = FUNC_NAMES.get(func & 0x7F, f"fc{func & 0x7F}")

    if func & 0x80:
        exc = body[0] if body else -1
        fields["exception"] = exc
        return ("response",
                f"slave {addr} {fname} EXCEPTION 0x{exc:02X} "
                f"({EXCEPTIONS.get(exc, 'unknown')})", fields)

    prev_was_matching_request = (
        prev is not None and prev.role == "request"
        and prev.fields.get("addr") == addr and prev.fields.get("func") == func
    )

    if func in (1, 2, 3, 4):
        # Request: start(2) count(2). Response: bytecount(1) + data.
        if len(body) == 4 and not prev_was_matching_request:
            start = int.from_bytes(body[0:2], "big")
            count = int.from_bytes(body[2:4], "big")
            fields.update(start=start, count=count)
            return ("request", f"req: {fname} start={start} count={count} @slave {addr}", fields)
        if body and body[0] == len(body) - 1:
            fields["bytes"] = body[0]
            return ("response", f"resp: {fname} {body[0]} data bytes @slave {addr}", fields)
        if len(body) == 4:
            start = int.from_bytes(body[0:2], "big")
            count = int.from_bytes(body[2:4], "big")
            fields.update(start=start, count=count)
            return ("request", f"req: {fname} start={start} count={count} @slave {addr}", fields)
        return (None, f"{fname} @slave {addr} (unrecognized layout)", fields)

    if func in (5, 6):
        # Request and response are identical echoes: addr(2) value(2).
        if len(body) == 4:
            target = int.from_bytes(body[0:2], "big")
            value = int.from_bytes(body[2:4], "big")
            fields.update(target=target, value=value)
            role = "response" if prev_was_matching_request else "request"
            word = "resp (echo)" if role == "response" else "req"
            return (role, f"{word}: {fname} addr={target} value=0x{value:04X} @slave {addr}", fields)
        return (None, f"{fname} @slave {addr} (unrecognized layout)", fields)

    if func in (15, 16):
        # Request: start(2) count(2) bytecount(1) data. Response: start(2) count(2).
        if len(body) >= 5 and body[4] == len(body) - 5:
            start = int.from_bytes(body[0:2], "big")
            count = int.from_bytes(body[2:4], "big")
            fields.update(start=start, count=count)
            return ("request", f"req: {fname} start={start} count={count} @slave {addr}", fields)
        if len(body) == 4:
            start = int.from_bytes(body[0:2], "big")
            count = int.from_bytes(body[2:4], "big")
            fields.update(start=start, count=count)
            return ("response", f"resp: {fname} start={start} count={count} @slave {addr}", fields)
        return (None, f"{fname} @slave {addr} (unrecognized layout)", fields)

    return (None, f"{fname} @slave {addr} len={len(body)}", fields)


class ModbusRtuDecoder(Decoder):
    name = "modbus_rtu"

    def decode(self, data: bytes, prev: Decoded | None = None) -> Decoded | None:
        if len(data) < 4:
            return Decoded(self.name, False, f"short frame ({len(data)}B)",
                           errors=["short_frame"])
        if not crc_ok(data):
            addr, func = data[0], data[1]
            return Decoded(self.name, False,
                           f"CRC mismatch (addr={addr} fc={func & 0x7F}?)",
                           fields={"addr": addr, "func": func & 0x7F},
                           errors=["crc_mismatch"])
        addr, func = data[0], data[1]
        role, summary, fields = parse_pdu(addr, func, data[2:-2], prev)
        return Decoded(self.name, True, summary, role=role, fields=fields)

    def resplit(self, data: bytes) -> list[bytes] | None:
        """Greedy CRC-guided scan: split a blob into consecutive valid frames.
        Only claims a split when the entire blob is consumed by 2+ frames --
        anything less is guesswork and the frame is left alone."""
        if len(data) < 8:
            return None
        frames, start = [], 0
        while start < len(data):
            end_found = None
            for end in range(start + 4, min(start + 260, len(data)) + 1):
                if crc_ok(data[start:end]):
                    end_found = end
                    break
            if end_found is None:
                return None
            frames.append(data[start:end_found])
            start = end_found
        return frames if len(frames) >= 2 else None
