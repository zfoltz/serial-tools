"""Request/response timing: latency, poll stability, unanswered requests.

Unanswered requests with their wall-clock timestamps are the single most
diagnostic output for "why is this link misbehaving".
"""

from __future__ import annotations

from datetime import datetime

from ..core.frames import Frame


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(int(len(sorted_vals) * p), len(sorted_vals) - 1)
    return sorted_vals[idx]


def _request_dir(frames: list[Frame]) -> str | None:
    """Which direction sends the requests? Prefer decoder roles; fall back to
    'the direction that usually speaks first in a cross-direction pair'."""
    role_votes: dict[str, int] = {}
    for f in frames:
        d = f.decode
        role = (d.get("role") if isinstance(d, dict) else getattr(d, "role", None)) if d else None
        if role == "request":
            role_votes[f.dir] = role_votes.get(f.dir, 0) + 1
    if role_votes:
        return max(role_votes, key=role_votes.get)
    leads: dict[str, int] = {}
    for a, b in zip(frames, frames[1:]):
        if a.dir != b.dir:
            leads[a.dir] = leads.get(a.dir, 0) + 1
    if not leads:
        return None
    return max(leads, key=leads.get)


def analyze(frames: list[Frame], meta: dict | None = None,
            silence_ms: float = 5000.0) -> dict:
    dirs = {f.dir for f in frames}
    report: dict = {}
    if len(dirs) < 2 or len(frames) < 2:
        report["note"] = "one direction only -- no request/response pairing possible"
    else:
        req_dir = _request_dir(frames)
        report["request_dir"] = req_dir
        latencies: list[float] = []
        unanswered: list[dict] = []
        poll_ts: list[float] = []
        pending: Frame | None = None
        for f in frames:
            if f.dir == req_dir:
                if pending is not None:
                    unanswered.append(_frame_ref(pending))
                pending = f
                poll_ts.append(f.ts)
            elif pending is not None:
                latencies.append((f.ts - pending.ts) * 1000.0)
                pending = None
        if pending is not None:
            unanswered.append(_frame_ref(pending))

        lat = sorted(latencies)
        if lat:
            report["latency_ms"] = {
                "count": len(lat),
                "min": round(lat[0], 1),
                "median": round(_percentile(lat, 0.5), 1),
                "p95": round(_percentile(lat, 0.95), 1),
                "max": round(lat[-1], 1),
            }
        periods = sorted((b - a) * 1000.0 for a, b in zip(poll_ts, poll_ts[1:]))
        if periods:
            med = _percentile(periods, 0.5)
            report["poll_period_ms"] = {
                "median": round(med, 1),
                "min": round(periods[0], 1),
                "max": round(periods[-1], 1),
            }
        report["requests"] = len(poll_ts)
        report["unanswered"] = unanswered

    silences = [
        {"at": _iso(f.ts), "seq": f.seq, "silence_ms": round(f.gap_ms, 1)}
        for f in frames if f.gap_ms is not None and f.gap_ms >= silence_ms
    ]
    report["silence_gaps"] = silences
    report["silence_threshold_ms"] = silence_ms
    return report


def _frame_ref(f: Frame) -> dict:
    from ..core.frames import ascii_render
    return {"seq": f.seq, "at": _iso(f.ts), "hex": f.data[:16].hex(),
            "ascii": ascii_render(f.data[:16])}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="milliseconds")


def render(report: dict) -> list[str]:
    lines = ["== timing =="]
    if "note" in report:
        lines.append(f"  {report['note']}")
    if "latency_ms" in report:
        l = report["latency_ms"]
        lines.append(f"  request dir: {report.get('request_dir')}")
        lines.append(f"  latency ({l['count']} pairs): min {l['min']}  median {l['median']}  "
                     f"p95 {l['p95']}  max {l['max']} ms")
    if "poll_period_ms" in report:
        p = report["poll_period_ms"]
        lines.append(f"  poll period: median {p['median']}  min {p['min']}  max {p['max']} ms")
    unanswered = report.get("unanswered", [])
    if "requests" in report:
        lines.append(f"  requests: {report['requests']}   unanswered: {len(unanswered)}")
    for u in unanswered[:20]:
        lines.append(f"    UNANSWERED seq {u['seq']} at {u['at']}  {u['hex']}")
    if len(unanswered) > 20:
        lines.append(f"    ... and {len(unanswered) - 20} more")
    gaps = report.get("silence_gaps", [])
    if gaps:
        lines.append(f"  silence gaps >= {report['silence_threshold_ms']:.0f}ms: {len(gaps)}")
        for g in gaps[:10]:
            lines.append(f"    {g['silence_ms']:.0f}ms of silence before seq {g['seq']} at {g['at']}")
        if len(gaps) > 10:
            lines.append(f"    ... and {len(gaps) - 10} more")
    else:
        lines.append("  no silence gaps")
    return lines
