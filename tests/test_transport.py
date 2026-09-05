"""Tests for entry-owned transport lifecycle behavior."""

from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.elkm1.helpers.baud_probe import (
    STANDARD_BAUD_RATES,
    BaudProbeError,
    _try_baud,
)
from custom_components.elkm1.helpers.elk import Elk
from custom_components.elkm1.helpers.elk.connection import Connection
from custom_components.elkm1.helpers.elk.const import SettingFormat, ThermostatSetting
from custom_components.elkm1.helpers.elk.message import (
    MessageEncode,
    cw_encode,
    rw_encode,
    tr_encode,
    ts_encode,
)
from custom_components.elkm1.helpers.elk.notify import Notifier
from custom_components.elkm1.helpers.transport import (
    DEFAULT_HEARTBEAT_TIMEOUT,
    ConnectionTimeoutError,
    ElkConnectionManager,
    InvalidAuthError,
    _async_close_transport,
    _entry_connect,
    _entry_heartbeat,
    _entry_read_stream,
    _failure_category,
    validate_network_connection,
    validate_serial_port,
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

    assert manager.connection.heartbeat_timeout == DEFAULT_HEARTBEAT_TIMEOUT


def test_manager_accepts_a_scaled_heartbeat_timeout() -> None:
    """A poll interval longer than the default heartbeat window must not force reconnects."""
    manager = ElkConnectionManager(
        Elk({"url": "elk://127.0.0.1:2101"}), heartbeat_timeout=250.0
    )

    assert manager.connection.heartbeat_timeout == 250.0


async def test_entry_heartbeat_uses_the_configured_timeout() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    connection.writer = MagicMock()
    connection.heartbeat_timeout = 250.0

    with patch("custom_components.elkm1.helpers.transport.asyncio.timeout") as mock_timeout:
        mock_timeout.return_value.__aenter__ = AsyncMock(side_effect=asyncio.CancelledError)
        mock_timeout.return_value.__aexit__ = AsyncMock(return_value=False)
        with pytest.raises(asyncio.CancelledError):
            await _entry_heartbeat(connection)

    mock_timeout.assert_called_once_with(250.0)


def test_manager_owns_a_private_connection_instance() -> None:
    """Constructing a manager changes only its entry's own connection state,
    never a second entry's - the class itself carries no monkey-patched or
    shared mutable state (see docs/decisions.md 2026-09-05).
    """
    manager_a = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))
    manager_b = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2102"}))

    assert manager_a.connection is not manager_b.connection
    manager_a.connection.heartbeat_timeout = 999.0
    assert manager_b.connection.heartbeat_timeout != 999.0


@pytest.mark.parametrize(
    ("encode", "response"),
    [
        (lambda: cw_encode(0, 1, SettingFormat.NUMBER), "CR"),
        (lambda: rw_encode(dt.datetime(2026, 1, 1, tzinfo=dt.UTC)), "RR"),
        (lambda: tr_encode(0), "TR"),
        (lambda: ts_encode(0, 70, ThermostatSetting.HEAT_SETPOINT), "TR"),
    ],
)
def test_entry_send_carries_the_documented_response_metadata(encode, response) -> None:
    """cw/rw/tr/ts declare their real reply directly in their own encoder
    (fixed relative to elkm1-lib 2.2.15, which declared none - see
    docs/decisions.md 2026-09-05), and Connection.send() must queue it
    unmodified.
    """
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))
    manager.connection.writer = MagicMock()

    manager.connection.send(encode())

    assert manager.connection._write_queue[0].response_cmd == response


def test_entry_send_rejects_disconnected_or_paused_transport() -> None:
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))
    message = MessageEncode("06vn00", "VN")

    with pytest.raises(ConnectionError, match="disconnected"):
        manager.connection.send(message)

    manager.connection.writer = MagicMock()
    manager.connection._paused = True
    with pytest.raises(ConnectionError, match="paused"):
        manager.connection.send(message)


async def test_read_stream_validates_before_response_correlation() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    connection.awaiting_response_command = "VN"
    valid = _wire("VN", "050003080000")
    corrupt = valid[:-1] + ("0" if valid[-1] != "0" else "1")

    await _entry_read_stream(connection, _Reader(f"{corrupt}\r".encode()))
    assert not connection.response_received.is_set()

    await _entry_read_stream(connection, _Reader(f"{valid}\n".encode()))
    assert connection.response_received.is_set()


async def test_read_stream_rejects_overlength_complete_frame() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    unknown: list[dict] = []
    notifier.attach("unknown", lambda **payload: unknown.append(payload))
    overlength = _wire("ZZ", "A" * 1100)

    await _entry_read_stream(connection, _Reader(f"{overlength}\r\n".encode()))

    assert unknown == []


async def test_read_stream_discards_overlength_unterminated_input() -> None:
    """An unterminated stream that never completes a frame must not grow forever."""
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    unknown: list[dict] = []
    notifier.attach("unknown", lambda **payload: unknown.append(payload))
    unterminated = "A" * 1100

    await _entry_read_stream(connection, _Reader(unterminated.encode()))

    assert unknown == []


async def test_read_stream_skips_frames_that_decode_to_none() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    version = _wire("VN", "050003080000")
    versions: list[dict] = []
    notifier.attach("VN", lambda **payload: versions.append(payload))

    await _entry_read_stream(connection, _Reader(f"Username: \r{version}\n".encode()))

    assert versions == [{"elkm1_version": "5.0.3", "xep_version": "8.0.0"}]


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


@pytest.mark.parametrize(
    ("err", "category"),
    [
        (BaudProbeError("no reply"), "serial_probe"),
        (TimeoutError(), "timeout"),
        (OSError("offline"), "transport"),
        (ConnectionError("closed"), "transport"),
        (ValueError("bad"), "configuration"),
        (RuntimeError("other"), "configuration"),
    ],
)
def test_failure_category_classifies_every_transport_error(err, category) -> None:
    assert _failure_category(err) == category


async def test_entry_heartbeat_raises_when_not_paused() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    connection.writer = MagicMock()
    connection.heartbeat_timeout = 0.01

    with pytest.raises(ConnectionError, match="heartbeat timed out"):
        await _entry_heartbeat(connection)


async def test_entry_heartbeat_ignores_timeout_while_paused() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    connection.writer = MagicMock()
    connection.heartbeat_timeout = 0.01
    connection._paused = True

    async def _clear_writer_after_first_timeout() -> None:
        await asyncio.sleep(0.03)
        connection.writer = None
        connection.heartbeat_event.set()

    watcher = asyncio.create_task(_clear_writer_after_first_timeout())
    await _entry_heartbeat(connection)
    await watcher


async def test_async_close_transport_cancels_gathers_and_closes_writer() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    connection.writer = _Writer()
    hung = asyncio.create_task(asyncio.Event().wait(), name="elkm1-hung")
    connection.tasks.add(hung)

    await _async_close_transport(connection, {hung})

    assert hung.cancelled()
    assert connection.tasks == set()
    assert connection.writer is None


async def test_async_close_transport_handles_no_tasks_and_no_wait_closed() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    writer = MagicMock(spec=["write", "close"])
    connection.writer = writer

    await _async_close_transport(connection, set())

    writer.close.assert_called_once()
    assert connection.writer is None


async def test_async_close_transport_awaits_wait_closed_when_present() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    writer = MagicMock(spec=["write", "close", "wait_closed"])
    writer.wait_closed = AsyncMock()
    connection.writer = writer

    await _async_close_transport(connection, set())

    writer.wait_closed.assert_awaited_once()


async def test_async_close_transport_suppresses_wait_closed_errors() -> None:
    notifier = Notifier()
    connection = Connection("elk://test", notifier)
    writer = MagicMock(spec=["write", "close", "wait_closed"])
    writer.wait_closed = AsyncMock(side_effect=ConnectionError("already gone"))
    connection.writer = writer

    await _async_close_transport(connection, set())

    assert connection.writer is None


async def test_wrap_baud_callback_records_and_forwards_detection() -> None:
    seen: list[int] = []
    manager = ElkConnectionManager(
        Elk({"url": "elk://127.0.0.1:2101"}), on_baud_detected=seen.append
    )

    assert manager.connection.on_baud_detected is not None
    manager.connection.on_baud_detected(9600)

    assert manager.detected_baud == 9600
    assert seen == [9600]


async def test_wrap_baud_callback_tolerates_no_user_callback() -> None:
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))

    manager.connection.on_baud_detected(19200)

    assert manager.detected_baud == 19200


def test_manager_caches_the_supplied_baud_at_construction() -> None:
    manager = ElkConnectionManager(Elk({"url": "serial://COM1"}), cached_baud=38400)

    assert manager.connection.cached_baud == 38400


def test_on_transport_connected_counts_only_reconnects() -> None:
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))

    manager._on_transport_connected()
    assert manager.transport_state == "connected"
    assert manager.reconnect_count == 0

    manager._on_transport_connected()
    assert manager.reconnect_count == 1


def test_mark_disconnected_leaves_a_stopped_manager_stopped() -> None:
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))

    manager.transport_state = "connected"
    manager.mark_disconnected()
    assert manager.transport_state == "reconnecting"

    manager.transport_state = "stopped"
    manager.mark_disconnected()
    assert manager.transport_state == "stopped"


async def test_async_stop_closes_an_active_writer_and_drains_tasks() -> None:
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))
    writer = MagicMock(spec=["write", "close", "wait_closed"])
    writer.wait_closed = AsyncMock()
    manager.connection.writer = writer
    lingering = asyncio.create_task(asyncio.Event().wait(), name="elkm1-lingering")
    manager.connection.tasks.add(lingering)

    await manager.async_stop()

    assert manager.transport_state == "stopped"
    assert manager.connection.writer is None
    assert lingering.cancelled()
    writer.wait_closed.assert_awaited_once()


async def test_entry_connect_serial_success_then_closes_on_stream_end() -> None:
    """A successful serial open detects/caches baud and fires connect callbacks;
    when the read stream ends cleanly the loop tears down and backs off.
    """
    notifier = Notifier()
    connection = Connection("serial://COM1:9600", notifier)
    on_baud = MagicMock()
    on_connected = MagicMock()
    on_failure = MagicMock()
    connection.on_baud_detected = on_baud
    connection.on_transport_connected = on_connected
    connection.on_failure = on_failure
    connection.retry_delay = 1

    reader = _Reader(b"")
    writer = _Writer()
    backoff_entered = asyncio.Event()

    async def _backoff(_delay: float) -> None:
        backoff_entered.set()
        await asyncio.Event().wait()

    with (
        patch(
            "custom_components.elkm1.helpers.transport.open_probed_serial",
            AsyncMock(return_value=(9600, reader, writer)),
        ),
        patch("custom_components.elkm1.helpers.transport.asyncio.sleep", _backoff),
    ):
        task = asyncio.create_task(_entry_connect(connection))
        await backoff_entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert connection.cached_baud == 9600
    on_baud.assert_called_once_with(9600)
    on_connected.assert_called_once()
    assert on_failure.call_args[0][0] == "transport"
    assert writer.closed


async def test_entry_connect_retries_after_connect_failure() -> None:
    connection = Connection("elk://127.0.0.1:2101", Notifier())
    on_failure = MagicMock()
    connection.on_failure = on_failure
    connection.retry_delay = 1
    backoff_entered = asyncio.Event()

    async def _fail_connect(*_args, **_kwargs):
        raise ValueError("bad host")

    async def _backoff(delay: float) -> None:
        backoff_entered.set()
        await asyncio.Event().wait()

    with (
        patch("asyncio.open_connection", _fail_connect),
        patch("custom_components.elkm1.helpers.transport.asyncio.sleep", _backoff),
    ):
        task = asyncio.create_task(_entry_connect(connection))
        await backoff_entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert connection.retry_delay == 2
    on_failure.assert_called_once_with("configuration", "bad host")


async def test_entry_connect_retries_again_then_cancels_during_the_next_attempt() -> None:
    """After a backoff sleep returns, the loop must retry (not just back off once);
    cancelling during that next open attempt must propagate cleanly.
    """
    connection = Connection("elk://127.0.0.1:2101", Notifier())
    call_count = 0
    second_attempt_started = asyncio.Event()

    async def _fail_then_hang(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            second_attempt_started.set()
            await asyncio.Event().wait()
        raise OSError("offline")

    with (
        patch("asyncio.open_connection", _fail_then_hang),
        patch(
            "custom_components.elkm1.helpers.transport.asyncio.sleep",
            AsyncMock(return_value=None),
        ),
    ):
        task = asyncio.create_task(_entry_connect(connection))
        await second_attempt_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert call_count == 2


async def test_entry_connect_propagates_cancellation_while_streaming() -> None:
    """Cancelling the owning task while streams are up must close them cleanly."""
    connection = Connection("elk://127.0.0.1:2101", Notifier())

    class _HangingReader:
        async def read(self, _size: int) -> bytes:
            await asyncio.Event().wait()
            return b""

    writer = _Writer()

    with patch(
        "custom_components.elkm1.helpers.transport.asyncio.open_connection",
        AsyncMock(return_value=(_HangingReader(), writer)),
    ):
        task = asyncio.create_task(_entry_connect(connection))
        for _ in range(1000):
            if connection.tasks:
                break
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert connection.tasks == set()
    assert writer.closed
    assert connection.writer is None


async def test_entry_connect_surfaces_a_read_stream_exception() -> None:
    connection = Connection("elk://127.0.0.1:2101", Notifier())
    on_failure = MagicMock()
    connection.on_failure = on_failure
    connection.retry_delay = 1

    class _BrokenReader:
        async def read(self, _size: int) -> bytes:
            raise OSError("link reset")

    writer = _Writer()
    backoff_entered = asyncio.Event()

    async def _backoff(_delay: float) -> None:
        backoff_entered.set()
        await asyncio.Event().wait()

    with (
        patch(
            "custom_components.elkm1.helpers.transport.asyncio.open_connection",
            AsyncMock(return_value=(_BrokenReader(), writer)),
        ),
        patch("custom_components.elkm1.helpers.transport.asyncio.sleep", _backoff),
    ):
        task = asyncio.create_task(_entry_connect(connection))
        await backoff_entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert on_failure.call_args[0][0] == "transport"
    assert on_failure.call_args[0][1] == "link reset"


async def test_validate_serial_port_delegates_to_probe_baud() -> None:
    with patch(
        "custom_components.elkm1.helpers.transport.probe_baud",
        AsyncMock(return_value=57600),
    ) as mock_probe:
        result = await validate_serial_port("COM3", cached_baud=38400)

    assert result == 57600
    mock_probe.assert_called_once_with("COM3", 38400)


async def test_validate_network_connection_succeeds_on_version_and_login(
    monkeypatch,
) -> None:
    fire_tasks: list[asyncio.Task[None]] = []

    def _fake_start(self: ElkConnectionManager) -> None:
        async def _fire() -> None:
            await asyncio.sleep(0)
            self.elk._notifier.notify("VN", {})
            self.elk._notifier.notify("login", {"succeeded": True})

        fire_tasks.append(asyncio.create_task(_fire()))

    monkeypatch.setattr(ElkConnectionManager, "start", _fake_start)

    await validate_network_connection(
        "elk://127.0.0.1:2101", userid="6", password="secret", timeout=5.0
    )


async def test_validate_network_connection_raises_on_rejected_login(monkeypatch) -> None:
    fire_tasks: list[asyncio.Task[None]] = []

    def _fake_start(self: ElkConnectionManager) -> None:
        async def _fire() -> None:
            await asyncio.sleep(0)
            self.elk._notifier.notify("login", {"succeeded": False})

        fire_tasks.append(asyncio.create_task(_fire()))

    monkeypatch.setattr(ElkConnectionManager, "start", _fake_start)

    with pytest.raises(InvalidAuthError):
        await validate_network_connection("elk://127.0.0.1:2101", timeout=5.0)


async def test_validate_network_connection_times_out_with_no_response(monkeypatch) -> None:
    monkeypatch.setattr(ElkConnectionManager, "start", lambda self: None)

    with pytest.raises(ConnectionTimeoutError):
        await validate_network_connection("elk://127.0.0.1:2101", timeout=0.02)
