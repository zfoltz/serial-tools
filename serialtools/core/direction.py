"""Direction inference for 2-wire half-duplex RS485 taps.

One adapter sees both directions interleaved; half-duplex guarantees
turnaround gaps, so the idle-gap splitter already separates the frames.
This module assigns each frame a logical direction, layered:

1. Protocol (authoritative): if a decoder annotated the frame with a
   request/response role, use it.
2. Timing/shape heuristic: the master's polls are short, near-identical,
   and start conversations after the long idle; slaves answer within a
   short turnaround. Frames are grouped by a (length-bucket, prefix)
   signature and the conversation-starting signature is called MASTER.
3. Manual: first_is="master"/"slave" forces the first frame's role and
   strict alternation is assumed.

`src` is never touched, so a wrong inference is recoverable with
`serialtools decode --redirect`.
"""

from __future__ import annotations

from .frames import Frame

MASTER = "MASTER"
SLAVE = "SLAVE"


def _role_of(frame: Frame) -> str | None:
    d = frame.decode
    if d is None:
        return None
    role = d.get("role") if isinstance(d, dict) else d.role
    if role == "request":
        return MASTER
    if role == "response":
        return SLAVE
    return None


def _signature(frame: Frame) -> tuple:
    # Exact length matters: a Modbus reply echoes the poll's first two bytes
    # (addr, func), so the prefix alone cannot tell the two apart.
    return (len(frame.data), bytes(frame.data[:2]))


def infer(frames: list[Frame], first_is: str | None = None) -> float:
    """Assign frame.dir/dir_conf in place for a batch. Returns overall
    confidence (fraction of frames assigned by protocol or consistent
    alternation)."""
    if not frames:
        return 0.0

    dirs: list[str | None] = [_role_of(f) for f in frames]
    from_protocol = sum(1 for d in dirs if d is not None)

    if first_is:
        forced = MASTER if first_is.lower().startswith("m") else SLAVE
        other = SLAVE if forced == MASTER else MASTER
        for i, f in enumerate(frames):
            f.dir = forced if i % 2 == 0 else other
            f.dir_conf = 1.0 if dirs[i] == f.dir else 0.8
        return 1.0

    if from_protocol == 0:
        # Heuristic: the signature that most often opens a conversation
        # (arrives after a gap much larger than the turnaround) is the master.
        gaps = [f.gap_ms for f in frames if f.gap_ms is not None]
        gaps_sorted = sorted(gaps)
        turnaround = gaps_sorted[len(gaps_sorted) // 2] if gaps_sorted else 0.0
        opener_votes: dict[tuple, int] = {}
        for f in frames:
            if f.gap_ms is None or f.gap_ms > max(turnaround * 3, 50.0):
                opener_votes[_signature(f)] = opener_votes.get(_signature(f), 0) + 1
        if opener_votes:
            # Every signature that repeatedly opens conversations is a master
            # poll variant (masters with several poll types have several).
            # A slave frame can open at most once in a while (after a fault).
            master_sigs = {s for s, v in opener_votes.items() if v >= 2}
            if not master_sigs:
                master_sigs = {max(opener_votes, key=opener_votes.get)}
            for i, f in enumerate(frames):
                dirs[i] = MASTER if _signature(f) in master_sigs else SLAVE
        else:
            dirs[0] = MASTER  # give alternation an anchor and hope

    # Fill remaining unknowns by alternating away from the nearest known frame.
    known = [i for i, d in enumerate(dirs) if d is not None]
    if not known:
        dirs[0] = MASTER
        known = [0]
    for i in range(len(dirs)):
        if dirs[i] is None:
            nearest = min(known, key=lambda k: abs(k - i))
            dirs[i] = dirs[nearest] if (i - nearest) % 2 == 0 else _flip(dirs[nearest])

    # Confidence: how well the final assignment alternates (a half-duplex
    # request/response link should rarely have two same-direction frames
    # in a row, except master retries).
    flips = sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)
    alternation = flips / max(len(dirs) - 1, 1)
    conf = max(alternation, from_protocol / len(frames))

    for f, d in zip(frames, dirs):
        f.dir = d
        f.dir_conf = round(1.0 if _role_of(f) else conf, 3)
    return conf


def _flip(d: str) -> str:
    return SLAVE if d == MASTER else MASTER


class LiveDirection:
    """CaptureSession transform for live 2-wire capture. Uses decoder roles
    when present, else alternation from the last confident frame."""

    def __init__(self, first_is: str | None = None):
        self._last: str | None = (
            None if first_is is None
            else (SLAVE if first_is.lower().startswith("m") else MASTER))
        # _last holds the PREVIOUS frame's direction, so a forced first
        # frame needs the opposite stored.

    def __call__(self, frame: Frame) -> None:
        role = _role_of(frame)
        if role is not None:
            frame.dir, frame.dir_conf = role, 1.0
        elif self._last is not None:
            frame.dir, frame.dir_conf = _flip(self._last), 0.5
        else:
            frame.dir, frame.dir_conf = MASTER, 0.3
        self._last = frame.dir
