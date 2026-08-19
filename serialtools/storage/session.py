"""Create, write, and read capture-session directories. Format: schema.py."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterator

from ..core.frames import Frame, LinkConfig
from .schema import SCHEMA_VERSION

DEFAULT_ROOT = "captures"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")[:40]


class SessionWriter:
    """A CaptureSession sink that persists everything.

    Raw evidence (frames.jsonl, raw/*.bin) is append-only and never rewritten;
    decoding annotations belong in decoded.jsonl, written separately.
    """

    def __init__(self, links: list[LinkConfig], wiring: str, gap_ms: float,
                 root: str = DEFAULT_ROOT, name: str = "", notes: str = "",
                 device: dict | None = None, text_formatter=None):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dirname = f"{stamp}-{_slug(name)}" if name else stamp
        self.path = os.path.abspath(os.path.join(root, dirname))
        os.makedirs(os.path.join(self.path, "raw"), exist_ok=True)

        self.meta = {
            "schema_version": SCHEMA_VERSION,
            "started": datetime.now().isoformat(timespec="seconds"),
            "ended": None,
            "wiring": wiring,
            "taps": [l.to_json() for l in links],
            "gap_ms": gap_ms,
            "notes": notes,
            "device": device or {},
            "tool": {"name": "serialtools", "version": _tool_version()},
        }
        self._write_meta()

        self._frames = open(os.path.join(self.path, "frames.jsonl"), "a", encoding="utf-8")
        self._text = open(os.path.join(self.path, "tap.log"), "a", encoding="utf-8")
        self._text.write(f"# serialtools tap {self.meta['started']} gap={gap_ms}ms "
                         + " ".join(f"{l.label}={l.port}@{l.settings()}" for l in links) + "\n")
        self._text.flush()
        self._raw: dict[str, object] = {}
        self._formatter = text_formatter
        self._closed = False

    def _write_meta(self):
        with open(os.path.join(self.path, "session.json"), "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=2)

    def sink(self, frame: Frame) -> None:
        if self._closed:
            return
        self._frames.write(json.dumps(frame.to_json()) + "\n")
        self._frames.flush()
        if self._formatter:
            self._text.write(self._formatter(frame) + "\n")
            self._text.flush()
        raw = self._raw.get(frame.src)
        if raw is None:
            safe = _slug(frame.src) or "tap"
            raw = open(os.path.join(self.path, "raw", f"{safe}.bin"), "ab")
            self._raw[frame.src] = raw
        raw.write(frame.data)

    def close(self, stats: dict[str, int] | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        self.meta["ended"] = datetime.now().isoformat(timespec="seconds")
        if stats:
            self.meta["bytes"] = stats
        self._write_meta()
        for f in [self._frames, self._text, *self._raw.values()]:
            try:
                f.close()
            except Exception:
                pass


# -- reading ----------------------------------------------------------------

def load_session(path: str) -> dict:
    with open(os.path.join(path, "session.json"), encoding="utf-8") as f:
        return json.load(f)


def iter_frames(path: str, decoded: bool = False) -> Iterator[Frame]:
    """Yield frames from a capture dir (or directly from a .jsonl file path,
    including old rs232_tap.py logs)."""
    if os.path.isdir(path):
        name = "decoded.jsonl" if decoded else "frames.jsonl"
        file = os.path.join(path, name)
        if decoded and not os.path.exists(file):
            raise FileNotFoundError(f"{file} not found -- run `serialtools decode` first")
    else:
        file = path
    with open(file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            obj = json.loads(line)
            frame = Frame.from_json(obj)
            if "decode" in obj:
                frame.decode = obj["decode"]
            yield frame


def write_decoded(path: str, frames: list[Frame]) -> str:
    """Regenerate decoded.jsonl from annotated frames. frames.jsonl untouched."""
    out = os.path.join(path, "decoded.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for frame in frames:
            obj = frame.to_json()
            if frame.decode is not None:
                d = frame.decode
                obj["decode"] = d if isinstance(d, dict) else d.to_json()
            f.write(json.dumps(obj) + "\n")
    return out


def list_captures(root: str = DEFAULT_ROOT) -> list[dict]:
    if not os.path.isdir(root):
        return []
    out = []
    for entry in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, entry)
        meta_file = os.path.join(path, "session.json")
        if not os.path.isfile(meta_file):
            continue
        try:
            meta = load_session(path)
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "dir": path,
            "started": meta.get("started"),
            "ended": meta.get("ended"),
            "wiring": meta.get("wiring"),
            "taps": [t.get("label") for t in meta.get("taps", [])],
            "notes": meta.get("notes", ""),
        })
    return out


def _tool_version() -> str:
    from .. import __version__
    return __version__
