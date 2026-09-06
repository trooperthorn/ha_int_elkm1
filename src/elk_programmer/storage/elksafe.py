"""ElkRP's at-rest encryption of secrets in its account database.

ElkRP encrypts user code rows, the globals row, and the serial number and
RP access code columns of the account row with RC4 (its ``ElkSafe.cr``
class, ``cr.cs``). The key is eight fixed bytes XORed with the first seven
characters of the account id (``M1Fns.InitKey``), and for a user code row
additionally XORed with the first seven characters of the code number
(``M1Fns.UpdateKey``). Every copy of ElkRP shares the fixed bytes, so this is
obfuscation rather than protection; it is reproduced here only so that
existing databases can be read. See docs/security.md.
"""

from __future__ import annotations

from collections.abc import Iterable

BASE_KEY = bytes([80, 23, 14, 120, 48, 223, 77, 121])


def derive_key(*modifiers: str) -> bytes:
    """``InitKey`` with the first modifier, then ``UpdateKey`` with the rest."""
    key = bytearray(BASE_KEY)
    for modifier in modifiers:
        for i, ch in enumerate(modifier[:7]):
            key[i] ^= ord(ch) & 0xFF
    return bytes(key)


def rc4(key: bytes, data: bytes) -> bytes:
    """Plain RC4; ElkRP's key schedule cycles the eight key bytes."""
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    # cr.Key runs the key-scheduling swap loop a second time with j carried over.
    for i in range(256):
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


def crypt_columns(key: bytes, values: Iterable[int]) -> list[int]:
    """``CryptRS``: XOR a run of byte columns with the keystream, in order."""
    return list(rc4(key, bytes(int(v) & 0xFF for v in values)))


def crypt_string(key: bytes, text: str) -> str:
    """``CryptString``: RC4 over the characters, with ``[ESC]00`` standing in for NUL."""
    raw = bytearray()
    i = 0
    while i < len(text):
        if text.startswith("[ESC]00", i):
            raw.append(0)
            i += 7
        else:
            raw.append(ord(text[i]) & 0xFF)
            i += 1
    out = rc4(key, bytes(raw))
    return "".join("[ESC]00" if b == 0 else chr(b) for b in out)
