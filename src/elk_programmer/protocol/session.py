"""A programming session: transport, request and reply matching, keepalive.

The session reproduces ElkRP's SendReceive contract: send one framed
request, wait up to the request's timeout for a frame whose first byte is
the expected opcode (or for a bare ACK when an ACK is expected), retry up to
the request's attempt count, and treat a panel-sent ``7F 01`` as the panel
hanging up. A keepalive is sent every 15 seconds of silence because the
panel drops an idle RP session. Every frame in both directions is recorded
in the trace so a live test can be compared byte for byte with ElkRP.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from . import messages as m
from .framing import Decoder, Event, Kind, encode_frame

_LOGGER = logging.getLogger(__name__)

KEEPALIVE_INTERVAL = 15.0


class Transport(Protocol):
    async def write(self, data: bytes) -> None: ...

    async def read(self, timeout: float) -> bytes: ...

    async def close(self) -> None: ...


class TcpTransport:
    """Plain TCP to an M1XEP's non-secure port; TLS is layered by the caller."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    @classmethod
    async def connect(cls, host: str, port: int, ssl: object | None = None) -> TcpTransport:
        reader, writer = await asyncio.open_connection(host, port, ssl=ssl)
        return cls(reader, writer)

    async def write(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def read(self, timeout: float) -> bytes:
        try:
            return await asyncio.wait_for(self._reader.read(4096), timeout)
        except TimeoutError:
            return b""

    async def close(self) -> None:
        self._writer.close()
        with contextlib.suppress(OSError):
            await self._writer.wait_closed()


class SerialTransport(TcpTransport):
    """Direct RS-232 through serialx's asyncio streams; the panel's port is 8N1."""

    @classmethod
    async def open(cls, port: str, baud: int) -> SerialTransport:
        import serialx

        reader, writer = await serialx.open_serial_connection(url=port, baudrate=baud)
        return cls(reader, writer)


class SessionError(Exception):
    pass


class Timeout(SessionError):
    pass


class Disconnected(SessionError):
    pass


class WrongReply(SessionError):
    pass


@dataclass(frozen=True)
class TraceEntry:
    when: datetime
    direction: str
    body: bytes
    note: str = ""


@dataclass
class Session:
    transport: Transport
    trace: list[TraceEntry] = field(default_factory=list)
    on_trace: Callable[[TraceEntry], None] | None = None
    login_reply: m.LoginReply | None = None
    _decoder: Decoder = field(default_factory=Decoder)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _keepalive: asyncio.Task[None] | None = None
    _last_activity: float = 0.0
    _pending: list[Event] = field(default_factory=list)

    def _record(self, direction: str, body: bytes, note: str = "") -> None:
        entry = TraceEntry(datetime.now(UTC), direction, body, note)
        self.trace.append(entry)
        if self.on_trace:
            self.on_trace(entry)

    async def send_receive(self, request: m.Request) -> bytes:
        """Send a request and return the reply body; raise on failure.

        Returns ``b""`` for a bare ACK when the request expected one.
        """
        async with self._lock:
            last: SessionError | None = None
            for attempt in range(1, request.attempts + 1):
                self._record("tx", request.body, f"{request.description} attempt {attempt}")
                await self.transport.write(encode_frame(request.body))
                try:
                    return await self._await_reply(request)
                except (Timeout, WrongReply) as err:
                    last = err
                    _LOGGER.debug("%s: %s (attempt %d)", request.description, err, attempt)
                finally:
                    self._last_activity = asyncio.get_running_loop().time()
            assert last is not None
            raise last

    async def _await_reply(self, request: m.Request) -> bytes:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + request.timeout_ms / 1000
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise Timeout(f"no reply to {request.description}")
            data = await self.transport.read(remaining)
            if not data:
                continue
            for ev in self._decoder.feed(data):
                self._record("rx", ev.body, ev.kind.value)
                if ev.kind is Kind.DEBUG:
                    continue
                if ev.kind is Kind.CRC_ERROR:
                    raise WrongReply("reply failed CRC")
                if ev.kind is Kind.NAK:
                    raise WrongReply("panel sent NAK")
                if ev.kind is Kind.ACK:
                    if request.expect == m.ACK_RESULT:
                        return b""
                    continue
                if m.is_panel_disconnect(ev.body):
                    raise Disconnected("panel closed the session")
                if ev.body[0] == request.expect:
                    return ev.body
                raise WrongReply(f"expected opcode {request.expect:#04x}, got {ev.body[0]:#04x}")

    async def login(self, rp_code: str) -> m.LoginReply:
        body = await self.send_receive(m.login(rp_code))
        reply = m.parse_login_reply(body)
        if reply.status != 0:
            raise SessionError(f"panel rejected the session (status {reply.status})")
        self.login_reply = reply
        self._keepalive = asyncio.create_task(self._keepalive_loop())
        return reply

    async def _keepalive_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(1.0)
            if loop.time() - self._last_activity < KEEPALIVE_INTERVAL:
                continue
            try:
                await self.send_receive(m.keepalive())
            except SessionError as err:
                _LOGGER.warning("keepalive failed: %s", err)
                return

    async def read_record(self, record: m.Record, item: int, size: int, sub: int = 0) -> bytes:
        body = await self.send_receive(m.read_record(record, item, sub))
        data = body[m.REPLY_DATA_OFFSET : m.REPLY_DATA_OFFSET + size]
        if len(data) != size:
            raise WrongReply(f"{record.name} {item}: expected {size} bytes, got {len(data)}")
        return data

    async def write_record(self, record: m.Record, item: int, payload: bytes, sub: int = 0) -> None:
        await self.send_receive(m.write_record(record, item, payload, sub))

    async def record_crc(self, record: m.Record, item: int) -> int:
        body = await self.send_receive(m.record_crc(record, item))
        if len(body) < 6:
            raise WrongReply("short CRC reply")
        return (body[4] << 8) | body[5]

    async def close(self) -> None:
        if self._keepalive:
            self._keepalive.cancel()
        with contextlib.suppress(SessionError):
            await self.send_receive(m.disconnect())
        await self.transport.close()
