from serialtools.core.frames import Frame, ascii_render


def test_json_roundtrip():
    f = Frame(ts=1755600000.123456, src="PLC-OUT", data=b"\x02CP01\r",
              seq=42, gap_ms=13.2)
    obj = f.to_json()
    assert obj["seq"] == 42
    assert obj["dir"] == "PLC-OUT"
    assert "dir_conf" not in obj  # only serialized when < 1.0
    back = Frame.from_json(obj)
    assert back.data == f.data
    assert back.src == "PLC-OUT"
    assert back.seq == 42


def test_old_rs232_tap_jsonl_still_loads():
    old = {"ts": 1723000000.5, "iso": "2024-08-07T...", "dir": "PLC>DEV",
           "len": 3, "hex": "435031", "ascii": "CP1"}
    f = Frame.from_json(old)
    assert f.data == b"CP1"
    assert f.src == "PLC>DEV" and f.dir == "PLC>DEV"
    assert f.seq == -1


def test_ascii_render():
    assert ascii_render(b"AB\x02\xff") == "AB.."
