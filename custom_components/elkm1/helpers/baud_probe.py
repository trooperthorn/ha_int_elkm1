"""Host-side baud-rate auto-detection for Elk-M1 serial connections.

The Elk-M1 RS232 ASCII protocol (manual v1.90, section 2) has no command to
query or set the panel's own serial baud rate: it is a fixed panel-side
Global Programming setting with no wire-level handshake and no RTS/CTS flow
control honored by the panel. "Auto-detect" therefore means trying each
manufacturer-documented rate on the host side and confirming it against a
real reply to the `vn` (version request) command, not any protocol-level
negotiation with the panel.

Message construction/validation reuses elkm1_lib.message's vn_encode()/
decode() so the checksum and framing logic used here stays identical to
the one place elkm1-lib already implements it correctly, rather than
re-deriving the protocol by hand a second time.
"""

from __future__ import annotations

import asyncio
import logging

import serial_asyncio_fast
from elkm1_lib.message import decode, vn_encode

from .framing import MAX_FRAME_CHARS, extract_frames

_LOGGER = logging.getLogger(__name__)

# Installation manual Global G34 values, fastest first. The current protocol
# guide describes 9600-115200; legacy rates remain last for older panels.
STANDARD_BAUD_RATES: tuple[int, ...] = (
    115200,
    38400,
    19200,
    14400,
    9600,
    4800,
    2400,
    1200,
    300,
)

# The protocol manual notes multi-second command latency is normal for some
# commands; vn is lightweight, but a generous margin avoids false negatives
# on a slow/busy panel.
PROBE_RESPONSE_TIMEOUT = 2.0
_DECODE_ERRORS = (ValueError, AttributeError)
_PROBE_ERRORS = (TimeoutError, asyncio.IncompleteReadError, OSError, ValueError)


class BaudProbeError(Exception):
    """Raised when no standard baud rate produced a valid panel reply."""


def _checksum(msg: str) -> str:
    """Two's-complement mod-256 checksum, matching elkm1_lib.Connection._write_stream."""
    return f"{(256 - sum(ord(c) for c in msg)) % 256:02X}"


def _build_vn_command() -> bytes:
    encoded = vn_encode()
    return f"{encoded.message}{_checksum(encoded.message)}\r\n".encode()


async def _try_baud(
    port: str, baud: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """Open `port` at `baud` and send vn; return the open stream pair on a valid reply.

    On failure the port is closed before returning None. On success the
    connection is left open and handed back to the caller, so a winning
    probe doesn't have to close and immediately reopen the same serial
    port a second time before real use - besides the wasted round trip,
    rapid close/reopen can trip DTR-reset or settling quirks on some
    USB-serial adapters.
    """
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await serial_asyncio_fast.open_serial_connection(url=port, baudrate=baud)
        writer.write(_build_vn_command())
        await writer.drain()
        read_buffer = ""
        async with asyncio.timeout(PROBE_RESPONSE_TIMEOUT):
            while True:
                data = await reader.read(500)
                if not data:
                    break
                read_buffer += data.decode("ISO-8859-1")
                frames, read_buffer = extract_frames(read_buffer)
                if len(read_buffer) > MAX_FRAME_CHARS:
                    break
                for frame in frames:
                    if len(frame) > MAX_FRAME_CHARS:
                        continue
                    try:
                        result = decode(frame)
                    except _DECODE_ERRORS:
                        continue
                    # ELK traffic is asynchronous. Ignore valid broadcasts and
                    # continue until the specifically requested VN arrives.
                    if result and result[0] == "VN":
                        return reader, writer
    except _PROBE_ERRORS:
        if writer is not None:
            writer.close()
        return None

    writer.close()
    return None


async def open_probed_serial(
    port: str, cached_baud: int | None = None
) -> tuple[int, asyncio.StreamReader, asyncio.StreamWriter]:
    """Detect the panel's baud rate on `port` and return the open connection at it.

    Tries `cached_baud` first (if given) so reconnects lock on immediately
    instead of re-sweeping every rate, then falls through the standard
    rates. Raises BaudProbeError if nothing responds. The returned reader/
    writer are the live connection from the winning attempt - the caller
    owns closing it.
    """
    order = list(STANDARD_BAUD_RATES)
    if cached_baud is not None:
        order = [cached_baud, *[b for b in order if b != cached_baud]]

    for baud in order:
        _LOGGER.debug("Probing %s at %s baud", port, baud)
        opened = await _try_baud(port, baud)
        if opened is not None:
            _LOGGER.info("Elk-M1 panel responded on %s at %s baud", port, baud)
            reader, writer = opened
            return baud, reader, writer

    raise BaudProbeError(f"No standard baud rate produced a valid reply on {port}")


async def probe_baud(port: str, cached_baud: int | None = None) -> int:
    """Validation-only variant of open_probed_serial(): detect baud, then close.

    For callers (config-flow validation, USB port discovery) that only need
    a yes/this-is-an-Elk-panel-at-this-baud answer and don't want to keep
    the connection open afterward.
    """
    baud, _reader, writer = await open_probed_serial(port, cached_baud)
    writer.close()
    return baud
