import pytest

from serialtools.decoders import decode_frames, load_profile, resolve
from serialtools.decoders.ascii_profile import AsciiProfileDecoder
from serialtools.decoders.modbus_ascii import ModbusAsciiDecoder, lrc
from serialtools.decoders.modbus_rtu import ModbusRtuDecoder, crc16
from tests.conftest import make_frames


def rtu(payload: bytes) -> bytes:
    return payload + crc16(payload).to_bytes(2, "little")


class TestModbusRtu:
    dec = ModbusRtuDecoder()

    def test_request_fc3(self):
        d = self.dec.decode(rtu(b"\x01\x03\x00\x00\x00\x02"))
        assert d.ok and d.role == "request"
        assert d.fields == {"addr": 1, "func": 3, "start": 0, "count": 2}
        assert "read holding" in d.summary

    def test_response_fc3_after_request(self):
        req = self.dec.decode(rtu(b"\x01\x03\x00\x00\x00\x02"))
        d = self.dec.decode(rtu(b"\x01\x03\x04\x12\x34\x56\x78"), prev=req)
        assert d.ok and d.role == "response"
        assert d.fields["bytes"] == 4

    def test_exception_response(self):
        d = self.dec.decode(rtu(b"\x03\x83\x02"))
        assert d.ok and d.role == "response"
        assert d.fields["exception"] == 2
        assert "illegal data address" in d.summary

    def test_crc_mismatch(self):
        frame = bytearray(rtu(b"\x01\x03\x00\x00\x00\x02"))
        frame[-1] ^= 0xFF
        d = self.dec.decode(bytes(frame))
        assert not d.ok and "crc_mismatch" in d.errors

    def test_write_single_echo_needs_context(self):
        req = self.dec.decode(rtu(b"\x01\x06\x00\x10\x00\x99"))
        assert req.role == "request"
        echo = self.dec.decode(rtu(b"\x01\x06\x00\x10\x00\x99"), prev=req)
        assert echo.role == "response"

    def test_resplit_merged_frames(self):
        blob = rtu(b"\x01\x03\x00\x00\x00\x02") + rtu(b"\x01\x03\x04\x12\x34\x56\x78")
        parts = self.dec.resplit(blob)
        assert parts is not None and len(parts) == 2
        assert all(self.dec.decode(p).ok for p in parts)

    def test_resplit_leaves_single_frames_alone(self):
        assert self.dec.resplit(rtu(b"\x01\x03\x00\x00\x00\x02")) is None

    def test_short_frame(self):
        d = self.dec.decode(b"\x01\x03")
        assert not d.ok and "short_frame" in d.errors


class TestModbusAscii:
    dec = ModbusAsciiDecoder()

    @staticmethod
    def frame(payload: bytes) -> bytes:
        return b":" + (payload + bytes([lrc(payload)])).hex().upper().encode() + b"\r\n"

    def test_request(self):
        d = self.dec.decode(self.frame(b"\x01\x03\x00\x00\x00\x02"))
        assert d.ok and d.role == "request"

    def test_lrc_mismatch(self):
        payload = b"\x01\x03\x00\x00\x00\x02"
        bad = b":" + (payload + bytes([lrc(payload) ^ 0xFF])).hex().upper().encode() + b"\r\n"
        d = self.dec.decode(bad)
        assert not d.ok and "checksum_mismatch" in d.errors

    def test_not_this_protocol(self):
        assert self.dec.decode(b"\x01\x03\x00\x00") is None


class TestAsciiProfile:
    dec = AsciiProfileDecoder(load_profile("vici"))

    def test_command(self):
        d = self.dec.decode(b"GO05\r")
        assert d.ok and d.role == "request"
        assert d.fields["pos"] == "05"

    def test_response(self):
        d = self.dec.decode(b"CP03\r")
        assert d.ok and d.role == "response"
        assert d.fields["pos"] == "03"

    def test_unknown_message_flagged(self):
        d = self.dec.decode(b"XQZZY\r")
        assert d.ok  # framing fine -- conformance problem, not integrity
        assert "unknown_message" in d.errors

    def test_missing_terminator(self):
        d = self.dec.decode(b"CP")
        assert not d.ok and "no_terminator" in d.errors

    def test_crlf_also_accepted(self):
        assert self.dec.decode(b"CP\r\n").ok

    def test_resplit_on_terminator(self):
        parts = self.dec.resplit(b"CP\rGO05\r")
        assert parts == [b"CP\r", b"GO05\r"]

    def test_xor_checksum_profile(self):
        prof = {"framing": {"terminator": "CR"}, "checksum": {"type": "xor"}}
        dec = AsciiProfileDecoder(prof)
        body = b"CP01"
        chk = 0
        for b in body:
            chk ^= b
        assert dec.decode(body + bytes([chk]) + b"\r").ok
        assert "checksum_mismatch" in dec.decode(body + bytes([chk ^ 1]) + b"\r").errors

    def test_no_profile_generic_ascii(self):
        d = AsciiProfileDecoder(None).decode(b"HELLO\r\n")
        assert d.ok and d.fields["text"] == "HELLO"


def test_resolve_and_decode_frames():
    dec = resolve("modbus_rtu")
    merged = rtu(b"\x01\x03\x00\x00\x00\x02") + rtu(b"\x01\x03\x04\xaa\xbb\xcc\xdd")
    frames = make_frames([(100.0, "BUS", merged)])
    frames, resplit_count, ok, err = decode_frames(frames, dec)
    assert resplit_count == 1 and len(frames) == 2
    assert ok == 2 and err == 0
    assert frames[0].decode.role == "request"
    assert frames[1].decode.role == "response"
    assert [f.seq for f in frames] == [0, 1]


def test_resolve_profile_implies_ascii():
    dec = resolve(profile="vici")
    assert "VICI" in dec.name


def test_resolve_unknown_decoder():
    with pytest.raises(ValueError):
        resolve("df1")
