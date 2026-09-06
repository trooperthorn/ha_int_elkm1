"""Decoding and encoding of records against their specs.

A decoded record is a plain dict keyed by ElkRP field name. Text fields are
strings, voice fields are lists of six word ids, digit fields are strings of
digits, flag bytes are ints, and bit groups are exposed through
``get_bit``/``set_bit`` rather than being materialised, so the byte stays the
single source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .specs import Bit, Field, Kind, RecordSpec

Record = dict[str, Any]


SHOW_SUFFIX = "Show"


def _bytes_to_text(raw: bytes) -> str:
    return bytes(b & 0x7F for b in raw).decode("ascii", errors="replace").rstrip(" \x00")


def _text_to_bytes(text: str, length: int) -> bytes:
    data = text.encode("ascii", errors="replace")[:length]
    return data.ljust(length, b" ")


def decode_field(spec_field: Field, raw: bytes) -> Any:
    """Turn the bytes of one field into its editor value."""
    if spec_field.kind is Kind.U8:
        return raw[0]
    if spec_field.kind is Kind.U16:
        return (raw[0] << 8) | raw[1]
    if spec_field.kind is Kind.TEXT:
        return _bytes_to_text(raw)
    if spec_field.kind is Kind.CODE:
        # ElkRP stores code digits reversed: the first typed digit is the last byte
        # of the used span and unused high bytes are zero (User_Codes.cs 11446, 10730).
        return "".join(str(b % 10) for b in reversed(raw))
    if spec_field.kind is Kind.DIGITS:
        return "".join(str(b % 10) for b in raw)
    if spec_field.kind is Kind.VOICE:
        return [(raw[i] << 8) | raw[i + 1] for i in range(0, len(raw), 2)]
    return bytes(raw)


def encode_field(spec_field: Field, value: Any) -> bytes:
    """Turn an editor value back into the bytes of one field."""
    if spec_field.kind is Kind.U8:
        return bytes([int(value) & 0xFF])
    if spec_field.kind is Kind.U16:
        v = int(value)
        return bytes([(v >> 8) & 0xFF, v & 0xFF])
    if spec_field.kind is Kind.TEXT:
        return _text_to_bytes(str(value), spec_field.length)
    if spec_field.kind is Kind.CODE:
        digits = [int(c) for c in str(value) if c.isdigit()][-spec_field.length :]
        digits = [0] * (spec_field.length - len(digits)) + digits
        return bytes(reversed(digits))
    if spec_field.kind is Kind.DIGITS:
        digits = [int(c) for c in str(value) if c.isdigit()][: spec_field.length]
        return bytes(digits + [0] * (spec_field.length - len(digits)))
    if spec_field.kind is Kind.VOICE:
        words = [int(w) for w in value][: spec_field.length]
        words += [0] * (spec_field.length - len(words))
        return b"".join(bytes([(w >> 8) & 0xFF, w & 0xFF]) for w in words)
    raw = bytes(value)
    return raw[: spec_field.length].ljust(spec_field.length, b"\x00")


def decode_record(spec: RecordSpec, raw: bytes) -> Record:
    """Decode the wire bytes of one record."""
    if len(raw) != spec.size:
        raise ValueError(f"{spec.name} record is {spec.size} bytes, got {len(raw)}")
    out: Record = {}
    pos = 0
    for f in spec.fields:
        chunk = raw[pos : pos + f.size]
        out[f.name] = decode_field(f, chunk)
        if f.kind is Kind.TEXT:
            # Bit 7 of a name's first byte is the panel's "show on keypad" flag.
            out[f.name + SHOW_SUFFIX] = bool(chunk[0] & 0x80)
        pos += f.size
    return out


def encode_record(spec: RecordSpec, record: Mapping[str, Any]) -> bytes:
    """Encode one record to its wire bytes; missing fields encode as blank."""
    parts = []
    for f in spec.fields:
        value = record.get(f.name, default_value(f))
        raw = encode_field(f, value)
        if f.kind is Kind.TEXT and record.get(f.name + SHOW_SUFFIX):
            raw = bytes([raw[0] | 0x80]) + raw[1:]
        parts.append(raw)
    return b"".join(parts)


def default_value(spec_field: Field) -> Any:
    if spec_field.kind in (Kind.U8, Kind.U16):
        return 0
    if spec_field.kind in (Kind.TEXT, Kind.DIGITS, Kind.CODE):
        return ""
    if spec_field.kind is Kind.VOICE:
        return [0] * spec_field.length
    return b"\x00" * spec_field.length


def blank_record(spec: RecordSpec) -> Record:
    return {f.name: default_value(f) for f in (*spec.fields, *spec.extra)}


def record_from_columns(spec: RecordSpec, row: Mapping[str, Any]) -> Record:
    """Build a record from a database row keyed by ElkRP column name."""
    out: Record = {}
    for f in (*spec.fields, *spec.extra):
        cols = f.column_names()
        raw = bytes(int(row.get(c) or 0) & 0xFF for c in cols)
        out[f.name] = decode_field(f, raw)
        if f.kind is Kind.TEXT:
            out[f.name + SHOW_SUFFIX] = bool(raw[0] & 0x80)
    return out


def record_to_columns(spec: RecordSpec, record: Mapping[str, Any]) -> dict[str, int]:
    """Explode a record into per-byte database columns."""
    out: dict[str, int] = {}
    for f in (*spec.fields, *spec.extra):
        raw = encode_field(f, record.get(f.name, default_value(f)))
        if f.kind is Kind.TEXT and record.get(f.name + SHOW_SUFFIX):
            raw = bytes([raw[0] | 0x80]) + raw[1:]
        for col, b in zip(f.column_names(), raw, strict=True):
            out[col] = b
    return out


def get_bit(value: int, bit: Bit) -> int:
    mask = (1 << bit.width) - 1
    return (int(value) >> bit.lsb) & mask


def set_bit(value: int, bit: Bit, new: int) -> int:
    mask = (1 << bit.width) - 1
    if not 0 <= int(new) <= mask:
        raise ValueError(f"{bit.name} takes 0..{mask}, got {new}")
    cleared = int(value) & ~(mask << bit.lsb) & 0xFF
    return cleared | ((int(new) & mask) << bit.lsb)


def explain_flags(spec_field: Field, value: int) -> dict[str, int]:
    """Named view of every bit group in a flag byte, for display and diffs."""
    return {bit.name: get_bit(value, bit) for bit in spec_field.bits}
