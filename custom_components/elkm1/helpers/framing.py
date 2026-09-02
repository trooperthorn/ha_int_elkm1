"""Streaming frame extraction for ELK's permitted message terminators."""

from __future__ import annotations

import re

_TERMINATOR = re.compile(r"\r\n|\r|\n")
MAX_FRAME_CHARS = 1024


def extract_frames(buffer: str) -> tuple[list[str], str]:
    """Extract complete CR/LF, CR-only, or LF-only frames from a buffer."""
    frames: list[str] = []
    start = 0
    for match in _TERMINATOR.finditer(buffer):
        frame = buffer[start : match.start()]
        if frame:
            frames.append(frame)
        start = match.end()
    return frames, buffer[start:]


def has_valid_length_and_checksum(message: str) -> bool:
    """Validate the length and two's-complement checksum of an ELK frame."""
    if len(message) < 6:
        return False
    try:
        if int(message[:2], 16) != len(message) - 2:
            return False
        checksum = int(message[-2:], 16)
    except ValueError:
        return False
    return (sum(map(ord, message[:-2])) + checksum) % 256 == 0
