from serialtools.core.detect import score


def test_ascii_scoring_accepts_control_framed_protocols():
    frame = b"\x02CP01\x03\r\n" * 10
    assert score(frame, ascii_mode=True) == 1.0


def test_ascii_scoring_rejects_baud_mismatch_soup():
    soup = bytes(range(256))
    assert score(soup, ascii_mode=True) < 0.5


def test_binary_scoring_prefers_structured_data():
    modbus = b"\x01\x03\x04\x00\x10\x00\x20\xaa\xbb" * 20
    soup = bytes([0x00, 0xFF] * 50) + bytes(range(200))
    assert score(modbus, ascii_mode=False) > score(soup, ascii_mode=False)


def test_empty_scores_zero():
    assert score(b"", ascii_mode=True) == 0.0
