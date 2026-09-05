"""Tests for host-side baud-rate auto-detection.

tests/test_transport.py already covers _try_baud's happy path (ignoring an
unsolicited frame before the VN reply); this file covers the remaining
branches plus open_probed_serial()/probe_baud().
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.elkm1.helpers.baud_probe import (
    STANDARD_BAUD_RATES,
    BaudProbeError,
    _try_baud,
    open_probed_serial,
    probe_baud,
)


def _wire(command: str, data: str = "") -> str:
    message = f"{len(data) + 6:02X}{command}{data}00"
    checksum = (256 - sum(map(ord, message))) % 256
    return f"{message}{checksum:02X}"


class _Reader:
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = iter((*chunks, b""))

    async def read(self, _size: int) -> bytes:
        return next(self._chunks)


class _Writer:
    def __init__(self) -> None:
        self.closed = False

    def write(self, _data: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


async def test_try_baud_returns_none_when_stream_ends_without_reply() -> None:
    reader = _Reader(b"")
    writer = _Writer()

    with patch(
        "custom_components.elkm1.helpers.baud_probe.serialx.open_serial_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        result = await _try_baud("COM1", 9600)

    assert result is None
    assert writer.closed is True


async def test_try_baud_returns_none_and_closes_when_buffer_exceeds_max_frame() -> None:
    huge = "X" * 5000
    reader = _Reader(huge.encode())
    writer = _Writer()

    with patch(
        "custom_components.elkm1.helpers.baud_probe.serialx.open_serial_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        result = await _try_baud("COM1", 9600)

    assert result is None
    assert writer.closed is True


async def test_try_baud_ignores_oversized_frame_and_keeps_reading() -> None:
    oversized = _wire("ZZ", "A" * 1100)
    version = _wire("VN", "050003080000")
    reader = _Reader(f"{oversized}\r\n{version}\r\n".encode())
    writer = _Writer()

    with patch(
        "custom_components.elkm1.helpers.baud_probe.serialx.open_serial_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        result = await _try_baud("COM1", 9600)

    assert result == (reader, writer)


async def test_try_baud_ignores_undecodable_frame_and_keeps_reading() -> None:
    corrupt = _wire("VN", "050003080000")[:-1] + "9"
    version = _wire("VN", "050003080000")
    reader = _Reader(f"{corrupt}\r\n{version}\r\n".encode())
    writer = _Writer()

    with patch(
        "custom_components.elkm1.helpers.baud_probe.serialx.open_serial_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        result = await _try_baud("COM1", 9600)

    assert result == (reader, writer)


async def test_try_baud_returns_none_when_connection_open_fails() -> None:
    with patch(
        "custom_components.elkm1.helpers.baud_probe.serialx.open_serial_connection",
        AsyncMock(side_effect=OSError("port busy")),
    ):
        result = await _try_baud("COM1", 9600)

    assert result is None


async def test_try_baud_closes_writer_on_timeout() -> None:
    reader = MagicMock()
    reader.read = AsyncMock(side_effect=TimeoutError)
    writer = _Writer()

    with patch(
        "custom_components.elkm1.helpers.baud_probe.serialx.open_serial_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        result = await _try_baud("COM1", 9600)

    assert result is None
    assert writer.closed is True


async def test_open_probed_serial_tries_cached_baud_first() -> None:
    version = _wire("VN", "050003080000")
    reader = _Reader(f"{version}\r\n".encode())
    writer = _Writer()

    calls: list[int] = []

    async def _fake_try_baud(_port: str, baud: int):
        calls.append(baud)
        if baud == 4800:
            return reader, writer
        return None

    with patch(
        "custom_components.elkm1.helpers.baud_probe._try_baud",
        AsyncMock(side_effect=_fake_try_baud),
    ):
        baud, got_reader, got_writer = await open_probed_serial("COM1", cached_baud=4800)

    assert baud == 4800
    assert got_reader is reader
    assert got_writer is writer
    assert calls[0] == 4800
    assert calls.count(4800) == 1


async def test_open_probed_serial_falls_through_standard_rates_without_cache() -> None:
    async def _fake_try_baud(_port: str, baud: int):
        return None

    with patch(
        "custom_components.elkm1.helpers.baud_probe._try_baud",
        AsyncMock(side_effect=_fake_try_baud),
    ) as mock_try, pytest.raises(BaudProbeError, match="COM1"):
        await open_probed_serial("COM1")

    assert mock_try.await_count == len(STANDARD_BAUD_RATES)


async def test_probe_baud_closes_the_connection_and_returns_detected_rate() -> None:
    writer = _Writer()

    with patch(
        "custom_components.elkm1.helpers.baud_probe.open_probed_serial",
        AsyncMock(return_value=(19200, MagicMock(), writer)),
    ):
        baud = await probe_baud("COM1")

    assert baud == 19200
    assert writer.closed is True
