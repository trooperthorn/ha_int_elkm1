"""Connection state and the outbound write queue for an ELK-M1 link.

The actual transport open/reconnect loop and inbound read loop are owned by
`helpers/transport.py` (`ElkConnectionManager`), not by this class - that
split predates this module (it already bypassed elkm1-lib's own `connect()`)
and is kept deliberately, now without reaching into another package's
private attributes to do it. This class owns: connection state, the
outbound checksum/write queue, and the handful of state fields the entry
lifecycle manager needs to track across reconnects.
"""

from __future__ import annotations

import asyncio
import logging
from asyncio import timeout as asyncio_timeout
from collections import deque
from collections.abc import Callable
from typing import Any, NamedTuple

from .message import MessageEncode, checksum as _checksum
from .notify import Notifier

_LOGGER = logging.getLogger(__name__)
# A lost reply stalls every later queued write for up to this long, not just
# the command that lost it - kept short relative to real round trips for
# exactly that reason. See docs/decisions.md 2026-09-05.
MESSAGE_RESPONSE_TIME = 1.5


class QueuedWrite(NamedTuple):
    """One entry in the outbound write queue."""

    msg: str
    response_cmd: str | None
    timeout: float = 5.0


class Connection:
    """Connection state, outbound write queue, and per-entry lifecycle fields.

    `url`, `cached_baud`, `retry_delay`, and the `on_*` callbacks are
    read/written directly by `helpers/transport.py`'s entry-owned supervisor
    functions - they are this class's own public state, not another
    package's internals.
    """

    def __init__(self, url: str, notifier: Notifier) -> None:
        self.url = url
        self._notifier = notifier

        self.writer: asyncio.StreamWriter | None = None
        self.awaiting_response_command: str | None = None
        self._paused = False
        self._write_queue: deque[QueuedWrite] = deque()
        self._check_write_queue = asyncio.Event()
        self.response_received = asyncio.Event()
        self.tasks: set[asyncio.Task[Any]] = set()

        # Per-entry lifecycle state, set by helpers/transport.py across reconnects.
        self.cached_baud: int | None = None
        self.retry_delay: int = 1
        self.on_failure: Callable[[str, str], None] | None = None
        self.on_transport_connected: Callable[[], None] | None = None
        self.on_baud_detected: Callable[[int], None] | None = None

    async def _write_stream(self) -> None:
        """Drain the outbound queue: checksum, write, and await any reply."""

        async def write_msg(q_entry: QueuedWrite) -> None:
            msg = f"{q_entry.msg}{_checksum(q_entry.msg)}\r\n"
            _LOGGER.debug("write_data '%s'", msg[:-2])
            assert self.writer is not None
            self.writer.write(msg.encode())

        async def await_msg_response(q_entry: QueuedWrite) -> None:
            self.awaiting_response_command = q_entry.response_cmd
            try:
                async with asyncio_timeout(MESSAGE_RESPONSE_TIME):
                    await self.response_received.wait()
            except TimeoutError:
                self._notifier.notify("timeout", {"msg_code": q_entry.response_cmd})
            self.response_received.clear()
            self.awaiting_response_command = None

        while True:
            if not self._write_queue:
                await self._check_write_queue.wait()
            if not self.writer:
                break
            self._check_write_queue.clear()
            if self._write_queue:
                q_entry = self._write_queue.popleft()
                await write_msg(q_entry)
                if q_entry.response_cmd:
                    await await_msg_response(q_entry)

    def _send(self, q_entry: QueuedWrite, priority_send: bool) -> None:
        if self._paused:
            return
        if priority_send:
            self._write_queue.appendleft(q_entry)
        else:
            self._write_queue.append(q_entry)
        self._check_write_queue.set()

    def send(self, msg: MessageEncode, priority_send: bool = False) -> None:
        """Queue a checksummed message, rejecting unavailable transports explicitly."""
        if self._paused:
            raise ConnectionError("ELK-M1 command rejected while ELKRP has the panel paused")
        if self.writer is None:
            raise ConnectionError("ELK-M1 command rejected because the transport is disconnected")
        self._send(QueuedWrite(msg.message, msg.response_command), priority_send)

    def is_connected(self) -> bool:
        """Whether a transport is currently open."""
        return self.writer is not None

    def is_paused(self) -> bool:
        """Whether ElkRP currently owns the panel (writes are suppressed)."""
        return self._paused

    def pause(self) -> None:
        """Stop sending while ElkRP is connected to the panel."""
        self._write_queue.clear()
        self._paused = True

    def resume(self) -> None:
        """Resume sending once ElkRP has disconnected."""
        self._paused = False

    def disconnect(self, reason: str = "") -> None:
        """Close the transport and cancel this connection's own tasks."""
        if reason:
            _LOGGER.warning("ElkM1 at %s disconnecting %s", self.url, reason)
        else:
            _LOGGER.info("ElkM1 at %s disconnecting", self.url)
        if self.writer:
            self.writer.close()
            self.writer = None
        for task in self.tasks:
            if asyncio.current_task() != task:
                task.cancel()
        self.tasks = set()
        self._notifier.notify("disconnected", {})
