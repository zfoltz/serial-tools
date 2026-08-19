"""Offline capture analysis. Each submodule: analyze(frames, meta) -> dict,
render(report) -> list of text lines."""

from __future__ import annotations

from . import diff, errors, summary, timing
from ..core.frames import Frame

SECTIONS = {"summary": summary, "timing": timing, "errors": errors}


def full_report(frames: list[Frame], meta: dict | None = None,
                sections: tuple[str, ...] = ("summary", "timing", "errors")) -> dict:
    return {name: SECTIONS[name].analyze(frames, meta) for name in sections}


def render_text(report: dict) -> str:
    lines: list[str] = []
    for name, section_report in report.items():
        lines += SECTIONS[name].render(section_report)
        lines.append("")
    return "\n".join(lines)
