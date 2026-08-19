import time

from serialtools.core.capture import CaptureSession
from serialtools.core.frames import Frame
from serialtools.core.sources import ReplaySource


def _wait_done(session, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if all(not t.is_alive() for t in session._threads):
            break
        time.sleep(0.01)
    session.join()


def test_two_sources_interleave_in_timestamp_order():
    a = [Frame(100.0 + i, "A", b"a%d" % i) for i in range(5)]
    b = [Frame(100.5 + i, "B", b"b%d" % i) for i in range(5)]
    out = []
    session = CaptureSession(
        [ReplaySource(a, "A", realtime=False, rebase=False),
         ReplaySource(b, "B", realtime=False, rebase=False)],
        sinks=[out.append])
    session.start()
    _wait_done(session)

    assert len(out) == 10
    assert [f.seq for f in out] == list(range(10))
    assert [f.ts for f in out] == sorted(f.ts for f in out)
    assert [f.src for f in out] == ["A", "B"] * 5
    assert session.stats["A"] == sum(len(f.data) for f in a)


def test_transforms_run_before_sinks():
    frames = [Frame(100.0, "BUS", b"\x01\x03")]
    seen = []

    def tag(f):
        f.dir = "MASTER"

    session = CaptureSession([ReplaySource(frames, "BUS", realtime=False, rebase=False)],
                             wiring="rs485-2w", transforms=[tag], sinks=[seen.append])
    session.start()
    _wait_done(session)
    assert seen[0].dir == "MASTER"
    assert seen[0].src == "BUS"


def test_gap_ms_computed_between_frames():
    frames = [Frame(100.0, "A", b"x"), Frame(100.25, "A", b"y")]
    out = []
    session = CaptureSession([ReplaySource(frames, "A", realtime=False, rebase=False)],
                             sinks=[out.append])
    session.start()
    _wait_done(session)
    assert out[0].gap_ms is None
    assert abs(out[1].gap_ms - 250.0) < 1.0
