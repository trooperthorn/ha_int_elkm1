"""Wire framing for the Elk-M1 RP programming protocol.

A frame is ``DLE STX <body> DLE ETX CRC-hi CRC-lo``. A ``0x10`` inside the
body is sent twice; the CRC covers the unstuffed body only and is CRC-16
with polynomial 0x1021, zero initial value, no reflection, no final XOR,
the variant commonly called CRC-16/XMODEM. ``DLE ACK`` and ``DLE NAK`` are
two-byte replies with no body or CRC. See docs/protocol.md for the source
of every rule; everything here is reconstructed from ElkRP's managed
transports, not from a published specification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

DLE = 0x10
STX = 0x02
ETX = 0x03
ACK = 0x06
NAK = 0x15
DEBUG_STREAM = 0xFF


def crc16(data: bytes, crc: int = 0) -> int:
    """CRC-16/XMODEM over ``data``, continuing from ``crc``."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_frame(body: bytes) -> bytes:
    """Frame a message body for transmission."""
    if not body:
        raise ValueError("empty body")
    out = bytearray([DLE, STX])
    for byte in body:
        out.append(byte)
        if byte == DLE:
            out.append(DLE)
    crc = crc16(body)
    out += bytes([DLE, ETX, (crc >> 8) & 0xFF, crc & 0xFF])
    return bytes(out)


class Kind(Enum):
    MESSAGE = "message"
    ACK = "ack"
    NAK = "nak"
    CRC_ERROR = "crc_error"
    DEBUG = "debug"


@dataclass(frozen=True)
class Event:
    """One thing the decoder produced: a message, a bare ACK or NAK, or an error."""

    kind: Kind
    body: bytes = b""


class _State(Enum):
    IDLE = 0
    DLE1 = 1
    BODY = 2
    DLE2 = 3
    CRC1 = 4
    CRC2 = 5


@dataclass
class Decoder:
    """Incremental receiver mirroring ElkRP's seven-state machine."""

    _state: _State = _State.IDLE
    _body: bytearray = field(default_factory=bytearray)
    _crc_hi: int = 0

    def feed(self, data: bytes) -> list[Event]:
        events: list[Event] = []
        for byte in data:
            ev = self._step(byte)
            if ev is not None:
                events.append(ev)
        return events

    def _step(self, byte: int) -> Event | None:
        st = self._state
        if st is _State.IDLE:
            if byte == DLE:
                self._state = _State.DLE1
            return None
        if st is _State.DLE1:
            if byte == STX:
                self._body = bytearray()
                self._state = _State.BODY
            elif byte == ACK:
                self._state = _State.IDLE
                return Event(Kind.ACK)
            elif byte == NAK:
                self._state = _State.IDLE
                return Event(Kind.NAK)
            elif byte != DLE:
                self._state = _State.IDLE
            return None
        if st is _State.BODY:
            if byte == DLE:
                self._state = _State.DLE2
            else:
                self._body.append(byte)
            return None
        if st is _State.DLE2:
            if byte == DLE:
                self._body.append(DLE)
                self._state = _State.BODY
            elif byte == ETX:
                self._state = _State.CRC1
            elif byte == STX:
                self._body = bytearray()
                self._state = _State.BODY
            else:
                self._state = _State.IDLE
            return None
        if st is _State.CRC1:
            self._crc_hi = byte
            self._state = _State.CRC2
            return None
        self._state = _State.IDLE
        body = bytes(self._body)
        if body[:1] == bytes([DEBUG_STREAM]):
            return Event(Kind.DEBUG, body)
        expected = crc16(body)
        if (self._crc_hi, byte) != ((expected >> 8) & 0xFF, expected & 0xFF):
            return Event(Kind.CRC_ERROR, body)
        return Event(Kind.MESSAGE, body)
