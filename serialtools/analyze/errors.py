"""Error-pattern analysis: integrity failures over time, retries, NAKs, junk.

A checksum-failure rate that RISES over the capture points at noise or
termination trouble; a constant rate points at a config mismatch; retries
and NAKs point at the application layer.
"""

from __future__ import annotations

from ..core.frames import Frame
from ..decoders.base import INTEGRITY_ERRORS

ACK, NAK = 0x06, 0x15


def _decode_errors(f: Frame) -> list[str]:
    d = f.decode
    if d is None:
        return []
    return (d.get("errors") if isinstance(d, dict) else d.errors) or []


def analyze(frames: list[Frame], meta: dict | None = None,
            buckets: int = 10, retry_window_ms: float = 2000.0) -> dict:
    report: dict = {"frames": len(frames)}
    if not frames:
        return report

    by_type: dict[str, int] = {}
    integrity_frames = 0
    decoded_frames = 0
    for f in frames:
        errs = _decode_errors(f)
        if f.decode is not None:
            decoded_frames += 1
        if any(e in INTEGRITY_ERRORS for e in errs):
            integrity_frames += 1
        for e in errs:
            by_type[e] = by_type.get(e, 0) + 1
    report["decoded_frames"] = decoded_frames
    report["error_counts"] = by_type
    if decoded_frames:
        report["integrity_error_rate"] = round(integrity_frames / decoded_frames, 4)

    # Bucket integrity errors and junk density over time.
    t0, t1 = frames[0].ts, frames[-1].ts
    span = max(t1 - t0, 1e-9)
    bucket_err = [0] * buckets
    bucket_frames = [0] * buckets
    bucket_junk = [0] * buckets
    bucket_bytes = [0] * buckets
    for f in frames:
        i = min(int((f.ts - t0) / span * buckets), buckets - 1)
        bucket_frames[i] += 1
        bucket_bytes[i] += len(f.data)
        bucket_junk[i] += sum(1 for b in f.data if b in (0x00, 0xFF))
        if any(e in INTEGRITY_ERRORS for e in _decode_errors(f)):
            bucket_err[i] += 1
    report["error_timeline"] = [
        round(e / n, 3) if n else 0.0 for e, n in zip(bucket_err, bucket_frames)
    ]
    report["junk_timeline"] = [
        round(j / b, 3) if b else 0.0 for j, b in zip(bucket_junk, bucket_bytes)
    ]

    # Retries: the same direction repeating identical bytes shortly after.
    retries = 0
    for a, b in zip(frames, frames[1:]):
        if (a.dir == b.dir and a.data == b.data
                and (b.ts - a.ts) * 1000.0 <= retry_window_ms):
            retries += 1
    report["retries"] = retries

    report["ack_frames"] = sum(1 for f in frames if f.data == bytes([ACK]))
    report["nak_frames"] = sum(1 for f in frames if f.data == bytes([NAK]))
    nak_containing = sum(1 for f in frames if NAK in f.data and len(f.data) <= 4)
    if nak_containing > report["nak_frames"]:
        report["nak_containing"] = nak_containing

    report["unknown_messages"] = by_type.get("unknown_message", 0)
    return report


def _spark(vals: list[float]) -> str:
    marks = " .:-=+*#%@"
    return "".join(marks[min(int(v * (len(marks) - 1) + 0.5), len(marks) - 1)] for v in vals)


def render(report: dict) -> list[str]:
    lines = ["== errors =="]
    if not report.get("frames"):
        return lines + ["  no frames"]
    if not report.get("decoded_frames"):
        lines.append("  (no decode annotations -- run with --decoder/--profile for "
                     "checksum and conformance checks)")
    if "integrity_error_rate" in report:
        lines.append(f"  integrity errors: {report['integrity_error_rate']:.1%} of "
                     f"{report['decoded_frames']} decoded frames")
    for etype, n in sorted(report.get("error_counts", {}).items(), key=lambda kv: -kv[1]):
        lines.append(f"    {etype:<20} {n}")
    tl = report.get("error_timeline")
    if tl and any(tl):
        lines.append(f"  error rate over time   |{_spark(tl)}|  (start -> end)")
    jl = report.get("junk_timeline")
    if jl and any(v > 0.3 for v in jl):
        lines.append(f"  0x00/0xFF junk density |{_spark(jl)}|  -- baud mismatch or noise?")
    lines.append(f"  retries (same dir, same bytes, <2s): {report.get('retries', 0)}")
    if report.get("ack_frames") or report.get("nak_frames"):
        lines.append(f"  ACK frames: {report.get('ack_frames', 0)}   "
                     f"NAK frames: {report.get('nak_frames', 0)}")
    if report.get("unknown_messages"):
        lines.append(f"  messages not matching the profile: {report['unknown_messages']}")
    return lines
