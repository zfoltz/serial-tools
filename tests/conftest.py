import pytest

from serialtools.core.frames import Frame


def make_frames(spec):
    """spec: list of (ts, dir, data). Builds Frames with seq and gap_ms filled
    the way the capture writer would."""
    frames = []
    last = None
    for i, (ts, direction, data) in enumerate(spec):
        gap = None if last is None else (ts - last) * 1000.0
        frames.append(Frame(ts=ts, src=direction, data=data, seq=i,
                            dir=direction, gap_ms=gap))
        last = ts
    return frames


@pytest.fixture
def conversation():
    """A clean MASTER/SLAVE exchange: 5 polls 1s apart, replies 20ms later,
    with poll #3 unanswered and a 12s silence before the final poll."""
    spec = []
    t = 100.0
    for i in range(5):
        spec.append((t, "MASTER", b"\x01\x03\x00\x00\x00\x02\xc4\x0b"))
        if i != 2:  # poll 3 goes unanswered
            spec.append((t + 0.020, "SLAVE", bytes([0x01, 0x03, 0x04, i, i, i, i, 0x00, 0x00])))
        t += 12.0 if i == 3 else 1.0
    return make_frames(spec)
