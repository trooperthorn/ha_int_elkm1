"""Framing and message tests against the byte sequences ElkRP is known to send."""

from __future__ import annotations

from elk_programmer.protocol import messages as m
from elk_programmer.protocol.framing import Decoder, Event, Kind, crc16, encode_frame


def test_crc_matches_elkrp_keepalive_and_disconnect() -> None:
    assert crc16(bytes.fromhex("7F0000A5")) == 0x73D4
    assert crc16(bytes.fromhex("7F0100A5")) == 0x44E4
    assert crc16(bytes.fromhex("03000001")) == 0x8BFD


def test_encode_frame_known_vectors() -> None:
    assert encode_frame(m.keepalive().body) == bytes.fromhex("10027F0000A5100373D4")
    assert encode_frame(m.disconnect().body) == bytes.fromhex("10027F0100A5100344E4")
    assert encode_frame(m.read_record(m.Record.AREA, 1).body) == bytes.fromhex(
        "10020300000110038BFD"
    )


def test_dle_in_body_is_doubled_but_counted_once() -> None:
    body = bytes([0x83, 0x00, 0x00, 0x10, 0x10, 0x41])
    frame = encode_frame(body)
    assert frame[2:-4] == bytes([0x83, 0x00, 0x00, 0x10, 0x10, 0x10, 0x10, 0x41])
    crc = crc16(body)
    assert frame[-2:] == bytes([crc >> 8, crc & 0xFF])
    events = Decoder().feed(frame)
    assert events == [Event(Kind.MESSAGE, body)]


def test_decoder_ack_nak_crc_error_and_debug() -> None:
    d = Decoder()
    assert [e.kind for e in d.feed(bytes([0x10, 0x06, 0x10, 0x15]))] == [Kind.ACK, Kind.NAK]
    bad = bytearray(encode_frame(b"\x7f\x00\x00\xa5"))
    bad[-1] ^= 0xFF
    assert d.feed(bytes(bad))[0].kind == Kind.CRC_ERROR
    debug = encode_frame(b"\xffhello")
    assert d.feed(debug)[0].kind == Kind.DEBUG
    # Split delivery across reads must still produce one message.
    frame = encode_frame(b"\x03\x00\x00\x01" + bytes(24))
    assert d.feed(frame[:5]) == []
    assert d.feed(frame[5:])[0].body == b"\x03\x00\x00\x01" + bytes(24)


def test_login_body_reverses_digits_and_pads() -> None:
    assert m.login("246801").body == bytes.fromhex("7F000001") + bytes([1, 0, 8, 6, 4, 2])
    assert m.login("1234").body[4:] == bytes([4, 3, 2, 1, 0, 0])


def test_record_requests() -> None:
    assert m.read_record(m.Record.ZONE, 208).body == bytes.fromhex("050000D0")
    w = m.write_record(m.Record.AREA, 1, bytes(24))
    assert w.body[:4] == bytes.fromhex("83000001") and len(w.body) == 28 and w.expect == 0x83
    assert m.record_crc(m.Record.AREA, 1).body == bytes.fromhex("7E030001")
    assert m.group_crcs().body == bytes.fromhex("7E7F0000")


def test_parse_login_reply() -> None:
    body = bytearray(43)
    body[0] = 0x7F
    body[4:7] = bytes([5, 3, 18])
    body[8:12] = bytes([0x0, 0x0, 0xA, 0xB])
    body[12:14] = bytes([2, 1])
    body[22:25] = bytes([2, 0, 41])
    r = m.parse_login_reply(bytes(body))
    assert r.firmware == "5.3.18" and r.serial_number == "00AB" and r.hardware == "2.1"
    assert r.minimum_rp_version == "2.0.41" and r.status == 0 and not r.in_bootloader
    assert m.is_panel_disconnect(bytes.fromhex("7F0100A5"))
