"""MCP server exposing the taps to Claude Code (stdio transport).

Register:
    claude mcp add serialtools -- python -m serialtools.mcp
    claude mcp add serialtools-tx -- python -m serialtools.mcp --allow-tx

Transmit safety, three independent gates:
1. send_bytes is not registered at all unless the server started with
   --allow-tx -- in normal operation the tool does not exist.
2. Every call must pass confirm="SEND <port>" exactly.
3. The target port must not belong to a running tap session (taps are wired
   receive-only), and every transmit is appended to captures/tx-audit.jsonl.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime

try:
    from mcp.server import MCPServer as FastMCP  # mcp >= 2.0
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from .. import analyze as analyze_pkg, decoders
from ..core import direction as direction_mod
from ..core.capture import CaptureSession
from ..core.detect import DetectOptions, detect
from ..core.frames import Frame, LinkConfig, WIRING_MODES
from ..core.ports import port_details
from ..core.sources import SerialSource
from ..storage import session as storage
from ..viewer.live import text_formatter

RING_SIZE = 10_000

mcp = FastMCP(
    "serialtools",
    instructions=(
        "Passive serial (RS232/RS485) tap toolkit for troubleshooting PLC-to-device "
        "links. Typical flow: list_ports -> detect_settings -> start_tap -> poll "
        "get_frames with the returned next_seq cursor -> analyze_capture / stop_tap. "
        "Taps are wired receive-only and never transmit."),
)

_sessions: dict[str, dict] = {}
_lock = threading.Lock()


def _frame_obj(f: Frame) -> dict:
    obj = f.to_json()
    if f.decode is not None:
        obj["decode"] = f.decode if isinstance(f.decode, dict) else f.decode.to_json()
    return obj


@mcp.tool()
def list_ports() -> list[dict]:
    """List serial ports (device, description, hwid, whether a tap session of
    ours currently holds it)."""
    with _lock:
        in_use = {link.port: sid for sid, s in _sessions.items()
                  if s["session"].running for link in s["links"]}
    out = []
    for p in port_details():
        p["in_use_by_session"] = in_use.get(p["device"])
        out.append(p)
    return out


@mcp.tool()
def detect_settings(port: str, mode: str = "ascii", seconds: float = 2.0,
                    max_passes: int = 2, max_silent_wait: float = 15.0) -> dict:
    """Brute-force baud/framing on a tapped line. Traffic must be flowing.
    mode: 'ascii' (default) or 'binary' (e.g. Modbus RTU). Bounded: gives up
    after max_passes sweeps or max_silent_wait seconds of silence."""
    opts = DetectOptions(ascii_mode=(mode != "binary"), seconds=seconds,
                         passes=max_passes, wait=max_silent_wait)
    link = detect(port, opts, threading.Event())
    if link is None:
        return {"detected": False,
                "hint": "no traffic decoded -- check the tap wiring/ground, make sure "
                        "the PLC is talking, or try mode='binary'"}
    return {"detected": True, "port": link.port, "baud": link.baud,
            "bytesize": link.bytesize, "parity": link.parity,
            "score": link.detect_score}


@mcp.tool()
def start_tap(ports: list[str], baud: int, wiring: str = "rs232",
              bytesize: int = 8, parity: str = "N", gap_ms: float = 15.0,
              decoder: str | None = None, profile: str | None = None,
              first_is: str | None = None, notes: str = "", name: str = "") -> dict:
    """Start a passive capture. ports: ["COM3=PLC-OUT", "COM4=DEV-OUT"] (labels
    optional). baud is required -- call detect_settings first if unknown.
    wiring: rs232 | rs485-4w (one port per direction) | rs485-2w (ONE port,
    both directions inferred). decoder/profile add live protocol decoding.
    Frames stream into a ring buffer (get_frames) and a capture dir on disk."""
    if wiring not in WIRING_MODES:
        return {"error": f"wiring must be one of {WIRING_MODES}"}
    if wiring == "rs485-2w" and len(ports) != 1:
        return {"error": "rs485-2w wiring is one tap on the bus -- pass exactly one port"}

    links = []
    for spec in ports:
        port, _, label = spec.partition("=")
        label = label or ("BUS" if wiring == "rs485-2w" else port)
        links.append(LinkConfig(port.strip(), label.strip(), baud, bytesize, parity))

    try:
        dec = decoders.resolve(decoder, profile)
    except (ValueError, FileNotFoundError) as e:
        return {"error": str(e)}

    transforms = []
    if dec:
        state = {"prev": None}

        def decode_tf(f: Frame, _state=state, _dec=dec):
            d = _dec.decode(f.data, _state["prev"])
            if d is not None:
                f.decode = d
                _state["prev"] = d
        transforms.append(decode_tf)
    if wiring == "rs485-2w":
        transforms.append(direction_mod.LiveDirection(first_is))

    session = CaptureSession(
        [SerialSource(l, gap_ms=gap_ms) for l in links],
        wiring=wiring, gap_ms=gap_ms, transforms=transforms)

    ring: deque = deque(maxlen=RING_SIZE)
    session.add_sink(lambda f: ring.append(_frame_obj(f)))
    writer = storage.SessionWriter(
        links, wiring, gap_ms, name=name or "mcp", notes=notes,
        device={"profile": profile} if profile else None,
        text_formatter=text_formatter())
    session.add_sink(writer.sink)

    session_id = uuid.uuid4().hex[:8]
    with _lock:
        _sessions[session_id] = {"session": session, "writer": writer,
                                 "ring": ring, "links": links}
    session.start()
    return {"session_id": session_id, "capture_dir": writer.path,
            "taps": [l.to_json() for l in links],
            "note": "poll get_frames(session_id) for traffic; stop_tap when done"}


def _get(session_id: str) -> dict:
    with _lock:
        if session_id not in _sessions:
            raise ValueError(f"unknown session {session_id!r}; "
                             f"known: {list(_sessions) or 'none'}")
        return _sessions[session_id]


@mcp.tool()
def tap_status(session_id: str) -> dict:
    """Byte/frame counters and health of a running tap."""
    s = _get(session_id)
    sess: CaptureSession = s["session"]
    return {
        "running": sess.running,
        "duration_s": round(sess.elapsed(), 1),
        "frames": sess.frame_count,
        "bytes_per_tap": sess.stats,
        "capture_dir": s["writer"].path,
        "hint": None if sess.stats else
                "no bytes yet -- check tap wiring/ground and that the link is active",
    }


@mcp.tool()
def get_frames(session_id: str, since_seq: int = 0, max_frames: int = 200) -> dict:
    """Cursor read of captured frames (includes live decode annotations if a
    decoder was set). Pass the returned next_seq as since_seq next time.
    dropped > 0 means the ring wrapped and that many frames are only on disk."""
    s = _get(session_id)
    ring = list(s["ring"])
    dropped = 0
    if ring and since_seq < ring[0]["seq"]:
        dropped = ring[0]["seq"] - since_seq
    frames = [f for f in ring if f["seq"] >= since_seq][:max_frames]
    next_seq = (frames[-1]["seq"] + 1) if frames else since_seq
    return {"frames": frames, "next_seq": next_seq, "dropped": dropped,
            "buffered": len(ring)}


@mcp.tool()
def stop_tap(session_id: str) -> dict:
    """Stop a tap, close its capture dir, return final stats."""
    s = _get(session_id)
    sess: CaptureSession = s["session"]
    sess.join()
    s["writer"].close(sess.stats)
    with _lock:
        _sessions.pop(session_id, None)
    return {"capture_dir": s["writer"].path, "frames": sess.frame_count,
            "bytes_per_tap": sess.stats, "duration_s": round(sess.elapsed(), 1)}


@mcp.tool()
def list_captures() -> list[dict]:
    """List capture directories under captures/."""
    return storage.list_captures()


@mcp.tool()
def decode_capture(capture_dir: str, decoder: str | None = None,
                   profile: str | None = None, first_is: str | None = None) -> dict:
    """Decode a stored capture: writes decoded.jsonl (raw frames untouched),
    re-inferring 2-wire direction if the capture is rs485-2w."""
    try:
        dec = decoders.resolve(decoder, profile)
    except (ValueError, FileNotFoundError) as e:
        return {"error": str(e)}
    if dec is None:
        return {"error": "give decoder and/or profile"}
    frames = list(storage.iter_frames(capture_dir))
    if not frames:
        return {"error": "no frames in capture"}
    meta = storage.load_session(capture_dir)
    frames, resplit_count, ok, err = decoders.decode_frames(frames, dec)
    result: dict = {"frames": len(frames), "resplit": resplit_count,
                    "decoded_ok": ok, "decode_errors": err}
    if meta.get("wiring") == "rs485-2w":
        result["direction_confidence"] = round(
            direction_mod.infer(frames, first_is=first_is), 3)
    result["decoded_file"] = storage.write_decoded(capture_dir, frames)
    return result


@mcp.tool()
def analyze_capture(capture_dir: str, analysis: str = "all") -> dict:
    """Run offline analysis: 'summary' | 'timing' (latency, unanswered
    requests, silences) | 'errors' (checksum failures over time, retries,
    NAKs) | 'all'. Uses decoded.jsonl when present (run decode_capture first
    for checksum/conformance checks)."""
    decoded = os.path.exists(os.path.join(capture_dir, "decoded.jsonl"))
    frames = list(storage.iter_frames(capture_dir, decoded=decoded))
    if not frames:
        return {"error": "no frames in capture"}
    try:
        meta = storage.load_session(capture_dir)
    except FileNotFoundError:
        meta = None
    sections = ("summary", "timing", "errors") if analysis == "all" else (analysis,)
    if any(s not in analyze_pkg.SECTIONS for s in sections):
        return {"error": f"analysis must be one of {list(analyze_pkg.SECTIONS)} or 'all'"}
    report = analyze_pkg.full_report(frames, meta, sections)
    report["_used_decoded"] = decoded
    return report


# -- transmit (only exists with --allow-tx) ---------------------------------

def _register_send(server: FastMCP) -> None:
    @server.tool()
    def send_bytes(port: str, data_hex: str, confirm: str, baud: int = 9600,
                   bytesize: int = 8, parity: str = "N",
                   append: str = "", read_reply_s: float = 2.0) -> dict:
        """TRANSMIT bytes on a port and read the reply -- impersonating the PLC
        or the device. Only for a port wired for talking, NEVER a receive-only
        tap. confirm must be exactly "SEND <port>" (e.g. "SEND COM7"): ask the
        user before sending anything they didn't explicitly request. append:
        "CR", "CRLF" or "" added after the hex bytes."""
        expected = f"SEND {port}"
        if confirm != expected:
            return {"error": f'refused: confirm must be exactly "{expected}". '
                             f"Confirm with the user first -- this drives a real line."}
        with _lock:
            tapped = {l.port for s in _sessions.values() for l in s["links"]
                      if s["session"].running}
        if port in tapped:
            return {"error": f"refused: {port} belongs to a running tap session. "
                             f"Taps are wired receive-only; transmitting into one "
                             f"is always a mistake. stop_tap first."}
        try:
            data = bytes.fromhex(data_hex.replace(" ", ""))
        except ValueError:
            return {"error": "data_hex is not valid hex"}
        if append.upper() == "CR":
            data += b"\r"
        elif append.upper() == "CRLF":
            data += b"\r\n"

        from ..sim.replay import open_tx
        os.makedirs(storage.DEFAULT_ROOT, exist_ok=True)
        audit_path = os.path.join(storage.DEFAULT_ROOT, "tx-audit.jsonl")
        entry = {"at": datetime.now().isoformat(timespec="seconds"), "port": port,
                 "baud": baud, "hex": data.hex()}
        with open(audit_path, "a", encoding="utf-8") as audit:
            audit.write(json.dumps(entry) + "\n")

        ser = open_tx(port, baud, bytesize, parity)
        try:
            ser.reset_input_buffer()
            ser.write(data)
            ser.flush()
            reply = bytearray()
            end = time.time() + read_reply_s
            while time.time() < end:
                chunk = ser.read(256)
                if chunk:
                    reply += chunk
                    end = time.time() + 0.4
        finally:
            ser.close()
        from ..core.frames import ascii_render
        return {"sent_hex": data.hex(), "reply_hex": reply.hex(),
                "reply_ascii": ascii_render(bytes(reply)),
                "audit": audit_path}


def run(allow_tx: bool = False) -> int:
    if allow_tx:
        _register_send(mcp)
    mcp.run()
    return 0
