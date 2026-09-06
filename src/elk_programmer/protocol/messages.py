"""Message bodies of the RP programming protocol.

Every request is ``opcode, sub, item-hi, item-lo`` followed by an optional
payload. A configuration record type is chosen by opcode: reading uses the
base opcode and writing uses the base opcode plus 0x80. Replies repeat the
opcode in byte 0 and carry record bytes from byte 4. Opcode values and byte
positions are quoted from the decompiled ElkRP forms; docs/protocol.md cites
the line for each. Nothing here has been exercised against a panel yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

WRITE_BIT = 0x80
SYSTEM = 0x7F
GROUP_CRC = 0x7E
KEEPALIVE_SUB = 0xA5


class Record(IntEnum):
    """Read opcodes for configuration records; write is value + 0x80."""

    USER_CODE = 0x01
    DESCRIPTION = 0x02
    AREA = 0x03
    KEYPAD = 0x04
    ZONE = 0x05
    GLOBAL = 0x07
    TELEPHONE = 0x08
    REPORT_CODES_A = 0x09
    REPORT_CODES_B = 0x0A
    REPORT_CODES_C = 0x0B
    REPORT_CODES_D = 0x0C
    VOICE_MESSAGE = 0x0D
    X10 = 0x0E
    WIRELESS = 0x0F
    REPORT_CODES_E = 0x10
    RULES = 0x79


REPLY_DATA_OFFSET = 4
REPLY_LENGTH_MIN = 4

ACK_RESULT = 4102
NAK_RESULT = 4117


@dataclass(frozen=True)
class Request:
    """A message body plus what ElkRP expects back and how hard it retries."""

    body: bytes
    expect: int
    attempts: int = 4
    timeout_ms: int = 800
    description: str = ""


def header(opcode: int, sub: int, item: int) -> bytes:
    if not 0 <= item <= 0xFFFF:
        raise ValueError(f"item {item} out of range")
    return bytes([opcode & 0xFF, sub & 0xFF, (item >> 8) & 0xFF, item & 0xFF])


def read_record(record: Record, item: int, sub: int = 0) -> Request:
    return Request(
        header(record, sub, item), expect=record, description=f"read {record.name} {item}"
    )


def write_record(record: Record, item: int, payload: bytes, sub: int = 0) -> Request:
    op = record | WRITE_BIT
    return Request(
        header(op, sub, item) + payload, expect=op, description=f"write {record.name} {item}"
    )


def record_crc(record: Record, item: int) -> Request:
    """Ask the panel for the 16-bit CRC of one stored record."""
    return Request(
        header(GROUP_CRC, record, item), expect=GROUP_CRC, description=f"crc {record.name} {item}"
    )


def group_crcs() -> Request:
    """Ask for the table of 56 group CRCs (reply bytes 4..115)."""
    return Request(
        header(GROUP_CRC, 0x7F, 0), expect=GROUP_CRC, timeout_ms=2500, description="group crcs"
    )


def login(rp_code: str) -> Request:
    """Plain RP login: ``7F 00 00 01`` then the six code digits, last digit first."""
    digits = [int(c) for c in rp_code if c.isdigit()]
    if len(digits) > 6:
        raise ValueError("RP access code is at most six digits")
    digits = [0] * (6 - len(digits)) + digits
    return Request(
        header(SYSTEM, 0, 1) + bytes(reversed(digits)),
        expect=SYSTEM,
        timeout_ms=1600,
        description="login",
    )


def keepalive() -> Request:
    return Request(
        header(SYSTEM, 0, KEEPALIVE_SUB),
        expect=SYSTEM,
        attempts=2,
        timeout_ms=5000,
        description="keepalive",
    )


def disconnect() -> Request:
    return Request(
        bytes([SYSTEM, 0x01, 0x00, KEEPALIVE_SUB]),
        expect=SYSTEM,
        attempts=2,
        timeout_ms=500,
        description="disconnect",
    )


def read_time() -> Request:
    return Request(header(SYSTEM, 0, 3), expect=SYSTEM, description="read clock")


def read_anti_takeover() -> Request:
    return Request(header(SYSTEM, 0, 0x0C), expect=SYSTEM, attempts=3, timeout_ms=1500)


def version_query() -> Request:
    return Request(header(SYSTEM, 0, 0x11), expect=SYSTEM, description="version")


@dataclass(frozen=True)
class LoginReply:
    """The fields ElkRP reads out of the 0x7F login reply."""

    status: int
    firmware: str
    serial_number: str
    hardware: str
    boot: str
    event_list: str
    minimum_rp_version: str

    @property
    def in_bootloader(self) -> bool:
        return int(self.firmware.split(".")[0]) < 4


def parse_login_reply(body: bytes) -> LoginReply:
    if len(body) < 4 or body[0] != SYSTEM:
        raise ValueError("not a login reply")

    def ver(off: int, n: int) -> str:
        if len(body) < off + n:
            return ""
        return ".".join(str(b) for b in body[off : off + n])

    serial = ""
    if len(body) >= 12:
        serial = "".join(f"{b & 0xF:X}" for b in body[8:12])
    return LoginReply(
        status=body[1],
        firmware=ver(4, 3),
        serial_number=serial,
        hardware=ver(12, 2),
        boot=ver(14, 3),
        event_list=ver(19, 3),
        minimum_rp_version=ver(22, 3),
    )


def is_panel_disconnect(body: bytes) -> bool:
    return len(body) >= 2 and body[0] == SYSTEM and body[1] == 0x01
