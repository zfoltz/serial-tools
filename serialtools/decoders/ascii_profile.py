"""Profile-driven decoder for proprietary ASCII device protocols.

A new device needs no code -- just a ~20-line TOML profile:

    [device]
    name = "VICI EC actuator"

    [framing]
    terminator = "CR"          # or: start = "STX", end = "ETX"; names or hex ("0D")

    [checksum]
    type = "none"              # none | xor | sum8

    [commands]                 # request patterns -> meaning
    CP = "query current position"
    GO = { pattern = 'GO(?P<pos>\\d{1,2})', desc = "go to position" }

    [responses]                # named regex patterns
    position = 'CP(?P<pos>\\d+)'
    error    = '(?P<err>E\\d+|\\?)'

Which table matches classifies request vs response, which also feeds
2-wire RS485 direction inference. With no profile at all it acts as a
generic ASCII renderer (strip CR/LF, show the text).
"""

from __future__ import annotations

import re

from .base import Decoded, Decoder

C0_NAMES = {
    "NUL": 0x00, "SOH": 0x01, "STX": 0x02, "ETX": 0x03, "EOT": 0x04,
    "ENQ": 0x05, "ACK": 0x06, "BEL": 0x07, "BS": 0x08, "TAB": 0x09,
    "LF": 0x0A, "VT": 0x0B, "FF": 0x0C, "CR": 0x0D, "NAK": 0x15,
    "SYN": 0x16, "ETB": 0x17, "ESC": 0x1B,
}


def _to_bytes(spec: str) -> bytes:
    """'CR' -> b'\\r', 'CRLF' -> b'\\r\\n', '0D' -> b'\\r', '*' -> b'*'."""
    if spec.upper() == "CRLF":
        return b"\r\n"
    if spec.upper() in C0_NAMES:
        return bytes([C0_NAMES[spec.upper()]])
    if re.fullmatch(r"[0-9A-Fa-f]{2}(\s?[0-9A-Fa-f]{2})*", spec):
        return bytes.fromhex(spec)
    return spec.encode("latin-1")


class AsciiProfileDecoder(Decoder):
    name = "ascii"

    def __init__(self, profile: dict | None = None):
        self.profile = profile or {}
        if profile:
            device = profile.get("device", {})
            self.name = f"ascii:{device.get('name', 'profile')}"
        framing = self.profile.get("framing", {})
        self.terminator = _to_bytes(framing["terminator"]) if "terminator" in framing else None
        self.start = _to_bytes(framing["start"]) if "start" in framing else None
        self.end = _to_bytes(framing["end"]) if "end" in framing else None
        checksum = self.profile.get("checksum", {})
        self.checksum_type = checksum.get("type", "none")

        self.commands: list[tuple[re.Pattern, str]] = []
        for key, val in self.profile.get("commands", {}).items():
            if isinstance(val, dict):
                self.commands.append((re.compile(val["pattern"]), val.get("desc", key)))
            else:
                self.commands.append((re.compile(re.escape(key) + r"$"), val))
        self.responses: list[tuple[str, re.Pattern]] = [
            (rname, re.compile(pat))
            for rname, pat in self.profile.get("responses", {}).items()
        ]

    # -- framing/checksum ----------------------------------------------------

    def _strip(self, data: bytes) -> tuple[bytes, list[str]]:
        errors: list[str] = []
        if self.terminator is not None:
            if self.terminator in (b"\r", b"\n", b"\r\n"):
                # devices often answer CRLF even when commanded with CR --
                # any trailing CR/LF mix satisfies a CR/LF/CRLF terminator
                stripped = data.rstrip(b"\r\n")
                if stripped == data:
                    errors.append("no_terminator")
                data = stripped
            elif data.endswith(self.terminator):
                data = data[:-len(self.terminator)]
            else:
                errors.append("no_terminator")
        elif self.start is not None or self.end is not None:
            if self.start is not None:
                if data.startswith(self.start):
                    data = data[len(self.start):]
                else:
                    errors.append("bad_framing")
            if self.end is not None:
                if data.endswith(self.end):
                    data = data[:-len(self.end)]
                else:
                    errors.append("bad_framing")
        else:
            data = data.rstrip(b"\r\n")
        return data, errors

    def _check(self, payload: bytes) -> tuple[bytes, list[str]]:
        if self.checksum_type == "none" or len(payload) < 2:
            return payload, []
        body, check = payload[:-1], payload[-1]
        if self.checksum_type == "xor":
            calc = 0
            for b in body:
                calc ^= b
        elif self.checksum_type == "sum8":
            calc = sum(body) & 0xFF
        else:
            return payload, []
        return body, ([] if calc == check else ["checksum_mismatch"])

    # -- decode ----------------------------------------------------------------

    def decode(self, data: bytes, prev: Decoded | None = None) -> Decoded | None:
        stripped, errors = self._strip(data)
        stripped, chk_errors = self._check(stripped)
        errors += chk_errors
        try:
            text = stripped.decode("ascii")
        except UnicodeDecodeError:
            text = stripped.decode("latin-1")
            errors.append("non_ascii")
        ok = not errors

        for pattern, desc in self.commands:
            m = pattern.fullmatch(text) or pattern.match(text)
            if m:
                fields = {"command": text, **m.groupdict()}
                extra = " ".join(f"{k}={v}" for k, v in m.groupdict().items())
                summary = f"req: {desc}" + (f" ({extra})" if extra else "")
                return Decoded(self.name, ok, summary, role="request",
                               fields=fields, errors=errors)
        for rname, pattern in self.responses:
            m = pattern.search(text)
            if m:
                fields = {"response": rname, "text": text, **m.groupdict()}
                extra = " ".join(f"{k}={v}" for k, v in m.groupdict().items())
                summary = f"resp: {rname}" + (f" ({extra})" if extra else f" |{text}|")
                return Decoded(self.name, ok, summary, role="response",
                               fields=fields, errors=errors)

        if self.commands or self.responses:
            errors = errors + ["unknown_message"]
        return Decoded(self.name, ok, f"|{text}|", fields={"text": text}, errors=errors)

    def resplit(self, data: bytes) -> list[bytes] | None:
        sep = self.terminator or self.end
        if sep is None or data.count(sep) < 2:
            return None
        parts, out = data.split(sep), []
        for i, part in enumerate(parts[:-1]):
            out.append(part + sep)
        if parts[-1]:
            out.append(parts[-1])
        return out if len(out) >= 2 else None
