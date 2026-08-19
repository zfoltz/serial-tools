from serialtools.core.direction import MASTER, SLAVE, LiveDirection, infer
from serialtools.core.frames import Frame
from tests.conftest import make_frames


def _bus_conversation(n=6):
    """One tap (BUS) seeing master polls (same 8 bytes, 1s apart) and slave
    replies 20ms later -- no decode annotations."""
    spec = []
    t = 100.0
    for i in range(n):
        spec.append((t, "BUS", b"\x01\x03\x00\x00\x00\x02\xc4\x0b"))
        spec.append((t + 0.020, "BUS", bytes([0x01, 0x03, 0x04, i, 1, 2, 3, 9, 9])))
        t += 1.0
    return make_frames(spec)


def test_heuristic_finds_master_by_conversation_opener():
    frames = _bus_conversation()
    conf = infer(frames)
    assert conf > 0.8
    assert [f.dir for f in frames] == [MASTER, SLAVE] * 6
    assert all(f.src == "BUS" for f in frames)  # src never touched


def test_protocol_roles_are_authoritative():
    frames = _bus_conversation(4)
    # Annotate only the polls; replies must follow by alternation.
    for f in frames[::2]:
        f.decode = {"proto": "modbus_rtu", "ok": True, "role": "request", "summary": ""}
    infer(frames)
    assert [f.dir for f in frames] == [MASTER, SLAVE] * 4
    assert all(f.dir_conf == 1.0 for f in frames[::2])


def test_first_is_override():
    frames = _bus_conversation(3)
    infer(frames, first_is="slave")
    assert frames[0].dir == SLAVE
    assert frames[1].dir == MASTER


def test_live_direction_transform():
    live = LiveDirection()
    a = Frame(100.0, "BUS", b"\x01\x03", decode={"role": "request", "ok": True,
                                                 "proto": "x", "summary": ""})
    b = Frame(100.02, "BUS", b"\x01\x03\x04")
    live(a)
    live(b)
    assert a.dir == MASTER and a.dir_conf == 1.0
    assert b.dir == SLAVE and b.dir_conf < 1.0


def test_empty():
    assert infer([]) == 0.0
