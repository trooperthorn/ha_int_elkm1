"""Host-side baud-rate auto-detection for Elk-M1 serial connections.

Each documented rate is tried and confirmed by a real `vn` reply; see docs/protocol.md.
"""

from __future__ import annotations

import asyncio
import logging

import serialx

from .elk.message import checksum, decode, vn_encode
from .framing import MAX_FRAME_CHARS, extract_frames

_LOGGER = logging.getLogger(__name__)

# G34 rates, fastest first; sweep order is fixed. See docs/protocol.md.
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

# Generous on purpose: the manual says multi-second command latency is normal.
PROBE_RESPONSE_TIMEOUT = 2.0

# DTR toggles on every serial port open by default; some panels/UART bridges
# treat that as a reset and need a moment to recover before they'll answer a
# probe - see docs/protocol.md's DTR-reset/settling note. Confirmed by a real
# production incident: every baud rate in a sweep failed once, right after
# the panel was physically reconnected, then succeeded after a full Home
# Assistant restart gave the hardware more elapsed time to settle. See
# docs/decisions.md 2026-09-05.
PORT_SETTLE_DELAY = 0.5

_DECODE_ERRORS = (ValueError, AttributeError)
_PROBE_ERRORS = (TimeoutError, asyncio.IncompleteReadError, OSError, ValueError)


class BaudProbeError(Exception):
    """Raised when no standard baud rate produced a valid panel reply."""


def _build_vn_command() -> bytes:
    encoded = vn_encode()
    return f"{encoded.message}{checksum(encoded.message)}\r\n".encode()


async def _try_baud(
    port: str, baud: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """Open `port` at `baud` and send vn; return the open stream pair on a valid reply.

    On failure the port is closed before returning None; on success the
    open connection is handed to the caller.
    """
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await serialx.open_serial_connection(url=port, baudrate=baud)
        await asyncio.sleep(PORT_SETTLE_DELAY)
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
                    # Ignore unsolicited broadcasts until the requested vn reply arrives.
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

    Tries `cached_baud` first (if given), then the standard rates. Raises
    BaudProbeError if nothing responds. The caller owns closing the
    returned reader/writer.
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
    """Validation-only variant of open_probed_serial(): detect baud, then close."""
    baud, _reader, writer = await open_probed_serial(port, cached_baud)
    writer.close()
    return baud
