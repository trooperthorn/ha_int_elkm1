"""Tests for entry-owned transport lifecycle behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from elkm1_lib import Elk
from elkm1_lib.connection import Connection
from elkm1_lib.message import MessageEncode
from elkm1_lib.notify import Notifier

from custom_components.elkm1.helpers.baud_probe import STANDARD_BAUD_RATES, _try_baud
from custom_components.elkm1.helpers.transport import (
    DEFAULT_HEARTBEAT_TIMEOUT,
    ElkConnectionManager,
    _entry_heartbeat,
    _entry_read_stream,
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
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_manager_defaults_to_the_standard_heartbeat_timeout() -> None:
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))

    assert manager.connection._elkm1ha_heartbeat_timeout == DEFAULT_HEARTBEAT_TIMEOUT


def test_manager_accepts_a_scaled_heartbeat_timeout() -> None:
    """A poll interval longer than the default heartbeat window must not force reconnects."""
    manager = ElkConnectionManager(
        Elk({"url": "elk://127.0.0.1:2101"}), heartbeat_timeout=250.0
    )

    assert manager.connection._elkm1ha_heartbeat_timeout == 250.0


async def test_entry_heartbeat_uses_the_configured_timeout() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    connection._writer = MagicMock()
    connection._elkm1ha_heartbeat_timeout = 250.0

    with patch("custom_components.elkm1.helpers.transport.asyncio.timeout") as mock_timeout:
        mock_timeout.return_value.__aenter__ = AsyncMock(side_effect=asyncio.CancelledError)
        mock_timeout.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(asyncio.CancelledError):
            await _entry_heartbeat(connection)

    mock_timeout.assert_called_once_with(250.0)


def test_manager_does_not_patch_global_connection_class() -> None:
    """Constructing a manager changes only its entry's connection instance."""
    original_connect = Connection.connect
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))

    assert Connection.connect is original_connect
    assert manager.connection.connect is not original_connect


@pytest.mark.parametrize(
    ("wire_command", "response"),
    [("cw", "CR"), ("rw", "RR"), ("tr", "TR"), ("ts", "TR")],
)
def test_entry_send_adds_missing_documented_response_metadata(wire_command, response) -> None:
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))
    manager.connection._writer = MagicMock()

    manager.connection.send(MessageEncode(f"08{wire_command}0100", None))

    assert manager.connection._write_queue[0].response_cmd == response


def test_entry_send_rejects_disconnected_or_paused_transport() -> None:
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))
    message = MessageEncode("06vn00", "VN")

    with pytest.raises(ConnectionError, match="disconnected"):
        manager.connection.send(message)

    manager.connection._writer = MagicMock()
    manager.connection._paused = True
    with pytest.raises(ConnectionError, match="paused"):
        manager.connection.send(message)


async def test_read_stream_validates_before_response_correlation() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    connection._awaiting_response_command = "VN"
    valid = _wire("VN", "050003080000")
    corrupt = valid[:-1] + ("0" if valid[-1] != "0" else "1")

    await _entry_read_stream(connection, _Reader(f"{corrupt}\r".encode()))
    assert not connection._response_received.is_set()

    await _entry_read_stream(connection, _Reader(f"{valid}\n".encode()))
    assert connection._response_received.is_set()


async def test_read_stream_rejects_overlength_complete_frame() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    unknown: list[dict] = []
    notifier.attach("unknown", lambda **payload: unknown.append(payload))
    overlength = _wire("ZZ", "A" * 1100)

    await _entry_read_stream(connection, _Reader(f"{overlength}\r\n".encode()))

    assert unknown == []


async def test_read_stream_decodes_all_lights_and_complete_keypad_status() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    all_lights: list[dict] = []
    keypad_details: list[dict] = []
    notifier.attach("PC_ALL", lambda **payload: all_lights.append(payload))
    notifier.attach("KC_DETAIL", lambda **payload: keypad_details.append(payload))
    pc = _wire("PC", "A0002")
    kc = _wire("KC", "01112010000200000000")

    await _entry_read_stream(connection, _Reader(f"{pc}\r\n{kc}\r".encode()))

    assert all_lights == [{"house_index": 0, "aggregate_code": 2}]
    assert keypad_details == [
        {
            "keypad": 0,
            "key": 11,
            "function_key_lights": (2, 0, 1, 0, 0, 0),
            "bypass_requires_code": False,
            "beep_chime_by_area": (2, 0, 0, 0, 0, 0, 0, 0),
        }
    ]


async def test_invalid_supplemental_keypad_fields_do_not_stop_stream() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    versions: list[dict] = []
    details: list[dict] = []
    notifier.attach("VN", lambda **payload: versions.append(payload))
    notifier.attach("KC_DETAIL", lambda **payload: details.append(payload))
    malformed_kc = _wire("KC", "0111X010000200000000")
    version = _wire("VN", "050003080000")

    await _entry_read_stream(connection, _Reader(f"{malformed_kc}\r{version}\n".encode()))

    assert details == []
    assert versions == [{"elkm1_version": "5.0.3", "xep_version": "8.0.0"}]


async def test_baud_probe_ignores_unsolicited_frame_before_vn() -> None:
    writer = _Writer()
    unsolicited = _wire("XK", "0102030405060708")
    version = _wire("VN", "050003080000")
    reader = _Reader(f"{unsolicited}\r\n{version}\r\n".encode())

    with patch(
        "custom_components.elkm1.helpers.baud_probe.serialx.open_serial_connection",
        AsyncMock(return_value=(reader, writer)),
    ):
        opened = await _try_baud("COM1", 14400)

    assert opened == (reader, writer)
    assert 14400 in STANDARD_BAUD_RATES
    assert 57600 not in STANDARD_BAUD_RATES


async def test_stop_cancels_backoff_connect_task() -> None:
    """An unload cannot leave a reconnect/backoff task running."""
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))
    entered_backoff = asyncio.Event()

    async def _fail_connect(*_args, **_kwargs):
        raise OSError("offline")

    async def _backoff(_delay: float) -> None:
        entered_backoff.set()
        await asyncio.Event().wait()

    with (
        patch("asyncio.open_connection", _fail_connect),
        patch("custom_components.elkm1.helpers.transport.asyncio.sleep", _backoff),
    ):
        connect_task = manager.start()
        await entered_backoff.wait()
        await manager.async_stop()

    assert connect_task.cancelled()
    assert manager.transport_state == "stopped"
    assert not any(
        task.get_name().startswith("elkm1-") and not task.done()
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
    )
