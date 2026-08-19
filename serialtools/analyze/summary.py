"""Capture summary: who talked, how much, how big."""

from __future__ import annotations

from ..core.frames import Frame


def analyze(frames: list[Frame], meta: dict | None = None) -> dict:
    if not frames:
        return {"frames": 0}
    duration = max(frames[-1].ts - frames[0].ts, 1e-9)
    per_dir: dict[str, dict] = {}
    for f in frames:
        d = per_dir.setdefault(f.dir, {"frames": 0, "bytes": 0, "sizes": []})
        d["frames"] += 1
        d["bytes"] += len(f.data)
        d["sizes"].append(len(f.data))
    for d in per_dir.values():
        sizes = sorted(d.pop("sizes"))
        d["rate_bps"] = round(d["bytes"] / duration, 1)
        d["frame_len"] = {
            "min": sizes[0],
            "median": sizes[len(sizes) // 2],
            "max": sizes[-1],
        }
    report = {
        "frames": len(frames),
        "duration_s": round(duration, 3),
        "directions": per_dir,
    }
    if meta:
        report["settings"] = {
            "wiring": meta.get("wiring"),
            "taps": [f"{t.get('label')}={t.get('port')}@{t.get('baud')} {t.get('framing')}"
                     for t in meta.get("taps", [])],
            "notes": meta.get("notes", ""),
        }
    return report


def render(report: dict) -> list[str]:
    lines = ["== summary =="]
    if report.get("frames", 0) == 0:
        return lines + ["  no frames"]
    lines.append(f"  {report['frames']} frames over {report['duration_s']}s")
    if "settings" in report:
        s = report["settings"]
        lines.append(f"  wiring {s['wiring']}   " + "  ".join(s["taps"]))
        if s.get("notes"):
            lines.append(f"  notes: {s['notes']}")
    for name, d in report.get("directions", {}).items():
        fl = d["frame_len"]
        lines.append(f"  {name:<10} {d['frames']:>6} frames  {d['bytes']:>8}B "
                     f"({d['rate_bps']} B/s)  len {fl['min']}/{fl['median']}/{fl['max']} "
                     f"(min/med/max)")
    return lines
