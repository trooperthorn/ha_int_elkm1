"""Entry-owned transport lifecycle for Elk-M1 connections."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from types import MethodType
from typing import Any

from elkm1_lib import Elk
from elkm1_lib.connection import Connection, QueuedWrite
from elkm1_lib.message import MessageEncode, decode, get_elk_command
from elkm1_lib.util import parse_url

from .baud_probe import BaudProbeError, open_probed_serial, probe_baud
from .framing import MAX_FRAME_CHARS, extract_frames, has_valid_length_and_checksum

_LOGGER = logging.getLogger(__name__)

INITIAL_RETRY_DELAY = 1
MAX_RETRY_DELAY = 60

# The manager scales the heartbeat window past the poll interval; see docs/protocol.md.
DEFAULT_HEARTBEAT_TIMEOUT = 120.0
HEARTBEAT_MARGIN = 30.0

# elkm1-lib 2.2.15 lacks these reply codes; applied per connection, never to the library globally.
RESPONSE_COMMAND_OVERRIDES: dict[str, str] = {
    "cw": "CR",
    "rw": "RR",
    "tr": "TR",
    "ts": "TR",
}


class ConnectionTimeoutError(Exception):
    """A validation connection never received an ELK response."""


class InvalidAuthError(Exception):
    """A secure M1XEP rejected the supplied credentials."""


def _entry_send(connection: Connection, msg: MessageEncode, priority_send: bool = False) -> None:
    """Queue a checksummed message, rejecting unavailable transports explicitly."""
    if connection._paused:
        raise ConnectionError("ELK-M1 command rejected while ELKRP has the panel paused")
    if connection._writer is None:
        raise ConnectionError("ELK-M1 command rejected because the transport is disconnected")

    command = msg.message[2:4]
    response = msg.response_command or RESPONSE_COMMAND_OVERRIDES.get(command)
    connection._send(QueuedWrite(msg.message, response), priority_send)


def _entry_send_raw(connection: Connection, msg: str) -> None:
    """Queue an authentication/raw line without silently dropping it."""
    if connection._paused:
        raise ConnectionError("ELK-M1 raw command rejected while the transport is paused")
    if connection._writer is None:
        raise ConnectionError("ELK-M1 raw command rejected because the transport is disconnected")
    connection._send(QueuedWrite(msg, None, raw=True), False)


def _decode_all_lights_frame(line: str) -> tuple[str, dict[str, Any]] | None:
    """Decode the valid PC house/unit 00 aggregate form rejected by elkm1-lib."""
    if (
        get_elk_command(line) != "PC"
        or len(line) < 9
        or line[5:7] != "00"
        or not has_valid_length_and_checksum(line)
    ):
        return None
    house = line[4].upper()
    if house < "A" or house > "P":
        return None
    try:
        aggregate_code = int(line[7:9])
    except ValueError:
        return None
    return (
        "PC_ALL",
        {
            "house_index": ord(house) - ord("A"),
            "aggregate_code": aggregate_code,
        },
    )


def _decode_keypad_detail(line: str) -> tuple[str, dict[str, Any]] | None:
    """Decode the KC fields elkm1-lib 2.2.15 currently discards."""
    if get_elk_command(line) != "KC" or len(line) < 27:
        return None
    try:
        keypad = int(line[4:6]) - 1
        key = int(line[6:8])
        function_key_lights = tuple(int(value) for value in line[8:14])
        beep_chime_by_area = tuple(int(value, 16) for value in line[15:23])
    except ValueError:
        return None
    return (
        "KC_DETAIL",
        {
            "keypad": keypad,
            "key": key,
            "function_key_lights": function_key_lights,
            "bypass_requires_code": line[14] == "1",
            "beep_chime_by_area": beep_chime_by_area,
        },
    )


async def _entry_read_stream(connection: Connection, reader: asyncio.StreamReader) -> None:
    """Read, validate, correlate, and dispatch all manufacturer-valid frames."""
    read_buffer = ""
    while True:
        data = await reader.read(500)
        if not data:
            break
        connection._heartbeat()
        read_buffer += data.decode("ISO-8859-1")
        frames, read_buffer = extract_frames(read_buffer)
        if len(read_buffer) > MAX_FRAME_CHARS:
            _LOGGER.error("Discarding overlength unterminated ELK-M1 input")
            read_buffer = ""

        for line in frames:
            if len(line) > MAX_FRAME_CHARS:
                _LOGGER.error("Discarding overlength ELK-M1 frame")
                continue
            _LOGGER.debug("ELK-M1 received frame '%s'", line)
            try:
                decoded = decode(line)
            except (ValueError, AttributeError) as err:
                decoded = _decode_all_lights_frame(line)
                if decoded is None:
                    _LOGGER.error("Invalid ELK-M1 message '%s': %s", line, err)
                    continue

            if decoded is None:
                continue

            # Publish supplemental KC data before the library's KC callback so the key event is complete.
            if detail := _decode_keypad_detail(line):
                connection._notifier.notify(detail[0], detail[1])

            command, payload = decoded
            if command == connection._awaiting_response_command:
                # Correlation happens only after full length/checksum/decode success.
                connection._response_received.set()
            connection._notifier.notify(command, payload)


async def _entry_connect(connection: Connection) -> None:
    """Own one entry's open, stream supervision, and reconnect loop."""
    _LOGGER.info("Connecting to ElkM1 at %s", connection._url)
    scheme, dest, param, ssl_context = parse_url(connection._url)
    cached_baud: int | None = getattr(connection, "_elkm1ha_cached_baud", None)

    while True:
        retry_delay = int(getattr(connection, "_elkm1ha_retry_delay", INITIAL_RETRY_DELAY))
        try:
            async with asyncio.timeout(30):
                if scheme == "serial":
                    baud, reader, connection._writer = await open_probed_serial(dest, cached_baud)
                    connection._elkm1ha_cached_baud = baud  # type: ignore[attr-defined]
                    cached_baud = baud
                    if callback := getattr(connection, "_elkm1ha_on_baud_detected", None):
                        callback(baud)
                else:
                    reader, connection._writer = await asyncio.open_connection(
                        host=dest, port=param, ssl=ssl_context
                    )
        except asyncio.CancelledError:
            raise
        except (TimeoutError, ValueError, OSError, BaudProbeError) as err:
            next_delay = min(MAX_RETRY_DELAY, retry_delay * 2)
            connection._elkm1ha_retry_delay = next_delay  # type: ignore[attr-defined]
            if callback := getattr(connection, "_elkm1ha_on_failure", None):
                callback(_failure_category(err), str(err))
            _LOGGER.warning(
                "Error connecting to ElkM1 (%s). Retrying in %d seconds",
                err,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            continue

        stream_tasks = {
            asyncio.create_task(_entry_read_stream(connection, reader), name="elkm1-read-stream"),
            asyncio.create_task(connection._write_stream(), name="elkm1-write-stream"),
        }
        if scheme != "serial":
            stream_tasks.add(
                asyncio.create_task(_entry_heartbeat(connection), name="elkm1-heartbeat")
            )
        connection._tasks.update(stream_tasks)
        if callback := getattr(connection, "_elkm1ha_on_transport_connected", None):
            callback()
        connection._notifier.notify("connected", {})

        failure: BaseException | None = None
        try:
            done, _pending = await asyncio.wait(stream_tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if not task.cancelled() and (task_error := task.exception()) is not None:
                    failure = task_error
                    break
            if failure is None:
                failure = ConnectionError("ELK transport stream closed")
        except asyncio.CancelledError:
            await _async_close_transport(connection, stream_tasks)
            raise

        await _async_close_transport(connection, stream_tasks)
        connection._notifier.notify("disconnected", {})
        if callback := getattr(connection, "_elkm1ha_on_failure", None):
            callback(_failure_category(failure), str(failure))
        retry_delay = int(getattr(connection, "_elkm1ha_retry_delay", INITIAL_RETRY_DELAY))
        connection._elkm1ha_retry_delay = min(  # type: ignore[attr-defined]
            MAX_RETRY_DELAY, retry_delay * 2
        )
        await asyncio.sleep(retry_delay)


async def _entry_heartbeat(connection: Connection) -> None:
    """Supervise heartbeat without allowing a child task to reconnect."""
    timeout = getattr(connection, "_elkm1ha_heartbeat_timeout", DEFAULT_HEARTBEAT_TIMEOUT)
    while connection._writer:
        connection._heartbeat_event.clear()
        try:
            async with asyncio.timeout(timeout):
                await connection._heartbeat_event.wait()
        except TimeoutError:
            if connection._paused:
                continue
            raise ConnectionError("ELK heartbeat timed out") from None


async def _async_close_transport(connection: Connection, tasks: set[asyncio.Task[Any]]) -> None:
    """Cancel and await all streams, then close and await the writer."""
    current = asyncio.current_task()
    for task in tasks:
        if task is not current and not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    connection._tasks.difference_update(tasks)

    writer = connection._writer
    connection._writer = None
    if writer is not None:
        writer.close()
        wait_closed = getattr(writer, "wait_closed", None)
        if wait_closed is not None:
            with suppress(OSError, ConnectionError):
                await wait_closed()


def _failure_category(err: BaseException) -> str:
    """Return a stable diagnostics category for a transport failure."""
    if isinstance(err, BaudProbeError):
        return "serial_probe"
    if isinstance(err, TimeoutError):
        return "timeout"
    if isinstance(err, OSError):
        return "transport"
    return "configuration"


class ElkConnectionManager:
    """Own exactly one connection task and all transport shutdown work."""

    def __init__(
        self,
        elk: Elk,
        *,
        cached_baud: int | None = None,
        on_baud_detected: Any = None,
        heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT,
    ) -> None:
        self.elk = elk
        self.connection = elk.connection
        self._connect_task: asyncio.Task[None] | None = None
        self._ever_connected = False
        self.transport_state = "stopped"
        self.login_state = "unknown"
        self.reconnect_count = 0
        self.last_failure_category: str | None = None
        self.last_failure: str | None = None
        self.detected_baud = cached_baud

        self.connection.connect = MethodType(  # type: ignore[method-assign]
            _entry_connect, self.connection
        )
        self.connection.send = MethodType(  # type: ignore[method-assign]
            _entry_send, self.connection
        )
        self.connection.send_raw = MethodType(  # type: ignore[method-assign]
            _entry_send_raw, self.connection
        )
        self.connection._elkm1ha_retry_delay = INITIAL_RETRY_DELAY  # type: ignore[attr-defined]
        self.connection._elkm1ha_heartbeat_timeout = heartbeat_timeout  # type: ignore[attr-defined]
        self.connection._elkm1ha_on_failure = self._on_failure  # type: ignore[attr-defined]
        self.connection._elkm1ha_on_transport_connected = (  # type: ignore[attr-defined]
            self._on_transport_connected
        )
        if cached_baud is not None:
            self.connection._elkm1ha_cached_baud = cached_baud  # type: ignore[attr-defined]
        self.connection._elkm1ha_on_baud_detected = (  # type: ignore[attr-defined]
            self._wrap_baud_callback(on_baud_detected)
        )

    def _wrap_baud_callback(self, callback: Any) -> Any:
        def _detected(baud: int) -> None:
            self.detected_baud = baud
            if callback is not None:
                callback(baud)

        return _detected

    def _on_transport_connected(self) -> None:
        if self._ever_connected:
            self.reconnect_count += 1
        self._ever_connected = True
        self.transport_state = "connected"

    def _on_failure(self, category: str, message: str) -> None:
        self.transport_state = "reconnecting"
        self.last_failure_category = category
        self.last_failure = message

    def mark_disconnected(self) -> None:
        """Record a library disconnect notification."""
        if self.transport_state != "stopped":
            self.transport_state = "reconnecting"

    def mark_login(self, succeeded: bool) -> None:
        """Record login state and reset backoff only after accepted login."""
        self.login_state = "authenticated" if succeeded else "rejected"
        if succeeded:
            self.connection._elkm1ha_retry_delay = INITIAL_RETRY_DELAY  # type: ignore[attr-defined]
            self.last_failure_category = None
            self.last_failure = None
        else:
            self.last_failure_category = "authentication"
            self.last_failure = "M1XEP rejected the configured credentials"

    def start(self) -> asyncio.Task[None]:
        """Start or return the owned connection task."""
        if self._connect_task is None or self._connect_task.done():
            self.transport_state = "connecting"
            self._connect_task = asyncio.create_task(
                self.connection.connect(), name="elkm1-connect"
            )
        return self._connect_task

    async def async_stop(self) -> None:
        """Cancel the owned task, disconnect, and await all stream cleanup."""
        self.transport_state = "stopped"
        connect_task = self._connect_task
        self._connect_task = None
        if connect_task is not None and not connect_task.done():
            connect_task.cancel()
            with suppress(asyncio.CancelledError):
                await connect_task

        connection_tasks = set(self.connection._tasks)
        if self.connection._writer is not None or connection_tasks:
            writer = self.connection._writer
            self.connection.disconnect()
            if connection_tasks:
                await asyncio.gather(*connection_tasks, return_exceptions=True)
            if writer is not None:
                wait_closed = getattr(writer, "wait_closed", None)
                if wait_closed is not None:
                    with suppress(OSError, ConnectionError):
                        await wait_closed()


async def validate_serial_port(port: str, cached_baud: int | None = None) -> int:
    """Verify a selected serial port and return its detected ELK baud."""
    return await probe_baud(port, cached_baud)


async def validate_network_connection(
    url: str,
    userid: str | None = None,
    password: str | None = None,
    timeout: float = 10.0,
) -> None:
    """Verify network transport, ELK identity response, and secure login."""
    config: dict[str, Any] = {"url": url, "element_list": ["panel"]}
    if userid is not None:
        config["userid"] = userid
    if password is not None:
        config["password"] = password

    elk = Elk(config)
    manager = ElkConnectionManager(elk)
    got_version = asyncio.Event()
    login_failed = asyncio.Event()

    def _on_vn(**_kwargs: Any) -> None:
        got_version.set()

    def _on_login(succeeded: bool) -> None:
        manager.mark_login(succeeded)
        if not succeeded:
            login_failed.set()

    elk.add_handler("VN", _on_vn)
    elk.add_handler("login", _on_login)
    version_task = asyncio.create_task(got_version.wait(), name="elkm1-validate-version")
    auth_task = asyncio.create_task(login_failed.wait(), name="elkm1-validate-login")
    try:
        manager.start()
        try:
            async with asyncio.timeout(timeout):
                await asyncio.wait(
                    (version_task, auth_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
        except TimeoutError as exc:
            raise ConnectionTimeoutError(f"No ELK response from {url}") from exc
        if login_failed.is_set():
            raise InvalidAuthError(f"Authentication rejected by {url}")
        if not got_version.is_set():
            raise ConnectionTimeoutError(f"No ELK response from {url}")
    finally:
        for task in (version_task, auth_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(version_task, auth_task, return_exceptions=True)
        await manager.async_stop()
