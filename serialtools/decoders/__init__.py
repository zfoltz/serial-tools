"""Decoder registry and TOML profile loading.

Adding a protocol later (DF1, BACnet MS/TP, ...) is one new module plus one
entry in DECODERS. Adding a proprietary ASCII device is just a TOML profile.
"""

from __future__ import annotations

import os
import tomllib

from .ascii_profile import AsciiProfileDecoder
from .base import Decoded, Decoder, INTEGRITY_ERRORS
from .modbus_ascii import ModbusAsciiDecoder
from .modbus_rtu import ModbusRtuDecoder

DECODERS = {
    "modbus_rtu": ModbusRtuDecoder,
    "modbus_ascii": ModbusAsciiDecoder,
    "ascii": AsciiProfileDecoder,
}

_PROFILE_DIRS = [
    "profiles",                                   # cwd
    os.path.join(os.path.dirname(__file__), "..", "profiles"),  # packaged
]


def list_decoders() -> list[str]:
    return sorted(DECODERS)


def list_profiles() -> list[str]:
    names = set()
    for d in _PROFILE_DIRS:
        if os.path.isdir(d):
            names.update(f[:-5] for f in os.listdir(d) if f.endswith(".toml"))
    return sorted(names)


def load_profile(name_or_path: str) -> dict:
    candidates = [name_or_path]
    if not name_or_path.endswith(".toml"):
        candidates += [os.path.join(d, f"{name_or_path}.toml") for d in _PROFILE_DIRS]
    for path in candidates:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                profile = tomllib.load(f)
            profile.setdefault("_path", os.path.abspath(path))
            return profile
    raise FileNotFoundError(
        f"profile {name_or_path!r} not found (looked for a .toml in "
        f"{', '.join(_PROFILE_DIRS)}). Known: {', '.join(list_profiles()) or 'none'}")


def decode_frames(frames, decoder: Decoder, resplit: bool = True):
    """Annotate a frame list with a decoder, optionally re-framing merged
    frames first. Returns (frames, resplit_count, ok_count, err_count);
    seq is reassigned when resplitting changed the frame count."""
    from ..core.frames import Frame

    resplit_count = 0
    if resplit:
        out: list[Frame] = []
        for f in frames:
            parts = decoder.resplit(f.data)
            if parts:
                resplit_count += 1
                for i, part in enumerate(parts):
                    out.append(Frame(f.ts + i * 1e-6, f.src, part, dir=f.dir,
                                     dir_conf=f.dir_conf,
                                     gap_ms=f.gap_ms if i == 0 else 0.0))
            else:
                out.append(f)
        frames = out

    prev = None
    ok = err = 0
    for f in frames:
        d = decoder.decode(f.data, prev)
        if d is not None:
            f.decode = d
            prev = d
            ok += d.ok
            err += not d.ok
    if resplit_count:
        for i, f in enumerate(frames):
            f.seq = i
    return frames, resplit_count, ok, err


def resolve(decoder: str | None = None, profile: str | None = None) -> Decoder | None:
    """CLI/MCP entry: --decoder name and/or --profile name -> a Decoder."""
    if profile and not decoder:
        decoder = "ascii"
    if not decoder:
        return None
    try:
        cls = DECODERS[decoder]
    except KeyError:
        raise ValueError(f"unknown decoder {decoder!r}; known: {', '.join(list_decoders())}")
    if decoder == "ascii":
        return cls(load_profile(profile) if profile else None)
    return cls()
