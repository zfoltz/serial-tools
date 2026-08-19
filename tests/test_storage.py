import json
import os

from serialtools.core.frames import Frame, LinkConfig
from serialtools.storage import session as storage
from serialtools.viewer.live import text_formatter


def test_session_roundtrip(tmp_path):
    links = [LinkConfig("COM3", "PLC-OUT", 9600), LinkConfig("COM4", "DEV-OUT", 9600)]
    w = storage.SessionWriter(links, "rs232", 15.0, root=str(tmp_path),
                              name="unit test!", notes="bench",
                              text_formatter=text_formatter())
    frames = [Frame(100.0, "PLC-OUT", b"CP\r", seq=0),
              Frame(100.02, "DEV-OUT", b"CP01\r", seq=1, gap_ms=20.0)]
    for f in frames:
        w.sink(f)
    w.close(stats={"PLC-OUT": 3, "DEV-OUT": 5})

    assert os.path.basename(w.path).endswith("-unit-test")  # slugged
    meta = storage.load_session(w.path)
    assert meta["wiring"] == "rs232"
    assert meta["ended"] is not None
    assert meta["bytes"] == {"PLC-OUT": 3, "DEV-OUT": 5}
    assert meta["notes"] == "bench"

    loaded = list(storage.iter_frames(w.path))
    assert [f.data for f in loaded] == [b"CP\r", b"CP01\r"]
    assert loaded[1].gap_ms == 20.0

    with open(os.path.join(w.path, "raw", "PLC-OUT.bin"), "rb") as f:
        assert f.read() == b"CP\r"
    with open(os.path.join(w.path, "tap.log"), encoding="utf-8") as f:
        text = f.read()
    assert "PLC-OUT" in text and "43 50" in text

    caps = storage.list_captures(str(tmp_path))
    assert len(caps) == 1 and caps[0]["taps"] == ["PLC-OUT", "DEV-OUT"]


def test_decoded_jsonl_written_separately(tmp_path):
    links = [LinkConfig("COM3", "BUS", 19200)]
    w = storage.SessionWriter(links, "rs485-2w", 4.0, root=str(tmp_path))
    f = Frame(100.0, "BUS", b"\x01\x03", seq=0)
    w.sink(f)
    w.close()

    raw_before = open(os.path.join(w.path, "frames.jsonl"), encoding="utf-8").read()
    f.decode = {"proto": "modbus_rtu", "ok": False, "summary": "s", "errors": ["short_frame"]}
    storage.write_decoded(w.path, [f])
    assert open(os.path.join(w.path, "frames.jsonl"), encoding="utf-8").read() == raw_before

    decoded = list(storage.iter_frames(w.path, decoded=True))
    assert decoded[0].decode["errors"] == ["short_frame"]


def test_iter_frames_reads_old_rs232_tap_jsonl(tmp_path):
    p = tmp_path / "old.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": 1.0, "iso": "x", "dir": "PLC>DEV",
                            "len": 2, "hex": "4350", "ascii": "CP"}) + "\n")
    frames = list(storage.iter_frames(str(p)))
    assert frames[0].data == b"CP" and frames[0].dir == "PLC>DEV"
