"""Compare a known-good capture against a misbehaving one."""

from __future__ import annotations

from . import errors as errors_mod
from . import summary as summary_mod
from . import timing as timing_mod
from ..core.frames import Frame


def _message_kinds(frames: list[Frame]) -> set[str]:
    kinds = set()
    for f in frames:
        d = f.decode
        if d is None:
            continue
        fields = d.get("fields", {}) if isinstance(d, dict) else d.fields
        if "command" in fields:
            kinds.add(str(fields["command"])[:24])
        elif "func" in fields:
            kinds.add(f"fc{fields['func']}@{fields.get('addr', '?')}")
        elif "response" in fields:
            kinds.add(f"resp:{fields['response']}")
    return kinds


def analyze(good: list[Frame], bad: list[Frame],
            good_meta: dict | None = None, bad_meta: dict | None = None) -> dict:
    g = {
        "summary": summary_mod.analyze(good, good_meta),
        "timing": timing_mod.analyze(good, good_meta),
        "errors": errors_mod.analyze(good, good_meta),
    }
    b = {
        "summary": summary_mod.analyze(bad, bad_meta),
        "timing": timing_mod.analyze(bad, bad_meta),
        "errors": errors_mod.analyze(bad, bad_meta),
    }

    def metric(side, *path, default=None):
        node = side
        for p in path:
            if not isinstance(node, dict) or p not in node:
                return default
            node = node[p]
        return node

    rows = []
    for label, path in [
        ("median latency ms", ("timing", "latency_ms", "median")),
        ("p95 latency ms", ("timing", "latency_ms", "p95")),
        ("poll period ms", ("timing", "poll_period_ms", "median")),
        ("requests", ("timing", "requests")),
        ("unanswered", ("timing", "unanswered")),
        ("integrity error rate", ("errors", "integrity_error_rate")),
        ("retries", ("errors", "retries")),
        ("NAK frames", ("errors", "nak_frames")),
    ]:
        gv, bv = metric(g, *path), metric(b, *path)
        if isinstance(gv, list):
            gv = len(gv)
        if isinstance(bv, list):
            bv = len(bv)
        if gv is None and bv is None:
            continue
        rows.append({"metric": label, "good": gv, "bad": bv})

    gk, bk = _message_kinds(good), _message_kinds(bad)
    return {
        "metrics": rows,
        "only_in_good": sorted(gk - bk),
        "only_in_bad": sorted(bk - gk),
        "good_error_types": metric(g, "errors", "error_counts", default={}),
        "bad_error_types": metric(b, "errors", "error_counts", default={}),
    }


def render(report: dict) -> list[str]:
    lines = ["== diff (good vs bad) ==",
             f"  {'metric':<24} {'good':>10} {'bad':>10}"]
    for row in report["metrics"]:
        lines.append(f"  {row['metric']:<24} {row['good']!s:>10} {row['bad']!s:>10}")
    new_errs = {k: v for k, v in report["bad_error_types"].items()
                if k not in report["good_error_types"]}
    if new_errs:
        lines.append("  error types only in the bad capture: "
                     + ", ".join(f"{k} x{v}" for k, v in new_errs.items()))
    if report["only_in_good"]:
        lines.append("  messages only in the GOOD capture: " + ", ".join(report["only_in_good"]))
    if report["only_in_bad"]:
        lines.append("  messages only in the BAD capture:  " + ", ".join(report["only_in_bad"]))
    return lines
