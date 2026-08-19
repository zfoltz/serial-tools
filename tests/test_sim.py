from serialtools.sim.device import DeviceSimulator
from tests.conftest import make_frames


def test_from_capture_pairs_and_uses_median_latency(conversation):
    sim = DeviceSimulator.from_capture(conversation)
    poll = b"\x01\x03\x00\x00\x00\x02\xc4\x0b"
    assert sim.lookup(poll) is not None
    assert sim.lookup(poll)[0:3] == b"\x01\x03\x04"
    assert 19.0 < sim.delay_ms < 21.0


def test_lookup_normalizes_terminators():
    sim = DeviceSimulator({b"CP\r": b"CP01\r"})
    assert sim.lookup(b"CP\r\n") == b"CP01\r"   # PLC sends CRLF, capture had CR
    assert sim.lookup(b"XX\r") is None


def test_from_profile_sim_table():
    profile = {"device": {"name": "t"}, "framing": {"terminator": "CR"},
               "sim": {"CP": "CP01", "VR": "0501"}}
    sim = DeviceSimulator.from_profile(profile)
    assert sim.lookup(b"CP\r") == b"CP01\r"
