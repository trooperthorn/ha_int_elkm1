"""Session behaviour against a scripted fake panel: retries, ACKs, hang-ups."""

from __future__ import annotations

import asyncio

import pytest

from elk_programmer.protocol import messages as m
from elk_programmer.protocol.framing import encode_frame
from elk_programmer.protocol.session import Disconnected, Session, Timeout, WrongReply


class FakePanel:
    """Replies are queued per request; ``None`` means stay silent once."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.replies: list[bytes | None] = []
        self._inbox: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False

    async def write(self, data: bytes) -> None:
        self.sent.append(data)
        if self.replies:
            reply = self.replies.pop(0)
            if reply is not None:
                await self._inbox.put(reply)

    async def read(self, timeout: float) -> bytes:
        try:
            return await asyncio.wait_for(self._inbox.get(), timeout)
        except TimeoutError:
            return b""

    async def close(self) -> None:
        self.closed = True


def framed(body: bytes) -> bytes:
    return encode_frame(body)


async def test_login_parses_reply_and_starts_keepalive() -> None:
    panel = FakePanel()
    reply = bytearray(43)
    reply[0] = 0x7F
    reply[4:7] = bytes([5, 3, 18])
    panel.replies = [framed(bytes(reply))]
    session = Session(panel)
    info = await session.login("246801")
    assert info.firmware == "5.3.18"
    assert panel.sent[0] == framed(m.login("246801").body)
    assert session._keepalive is not None
    session._keepalive.cancel()


async def test_retry_then_success_and_timeout() -> None:
    panel = FakePanel()
    body = bytes([0x03, 0, 0, 1]) + bytes(range(24))
    panel.replies = [None, framed(body)]
    session = Session(panel)
    req = m.Request(m.read_record(m.Record.AREA, 1).body, expect=0x03, attempts=2, timeout_ms=50)
    assert await session.send_receive(req) == body
    assert len(panel.sent) == 2
    panel.replies = [None, None]
    with pytest.raises(Timeout):
        await session.send_receive(req)


async def test_read_record_slices_payload_and_checks_size() -> None:
    panel = FakePanel()
    body = bytes([0x05, 0, 0, 7]) + bytes(32)
    panel.replies = [framed(body)]
    session = Session(panel)
    assert await session.read_record(m.Record.ZONE, 7, 32) == bytes(32)
    panel.replies = [framed(bytes([0x05, 0, 0, 7]) + bytes(10))] * 4
    with pytest.raises(WrongReply):
        await session.read_record(m.Record.ZONE, 7, 32)


async def test_wrong_opcode_ack_and_panel_disconnect() -> None:
    panel = FakePanel()
    session = Session(panel)
    req = m.Request(bytes([0x03, 0, 0, 1]), expect=0x03, attempts=1, timeout_ms=50)
    panel.replies = [framed(bytes([0x04, 0, 0, 1]))]
    with pytest.raises(WrongReply):
        await session.send_receive(req)
    ack_req = m.Request(bytes([0xFF, 0, 0, 0x0C, 1]), expect=m.ACK_RESULT, attempts=1)
    panel.replies = [bytes([0x10, 0x06])]
    assert await session.send_receive(ack_req) == b""
    panel.replies = [framed(bytes([0x7F, 0x01, 0x00, 0xA5]))]
    with pytest.raises(Disconnected):
        await session.send_receive(req)
    assert [t.direction for t in session.trace][:2] == ["tx", "rx"]


async def test_close_sends_disconnect_and_closes_transport() -> None:
    panel = FakePanel()
    session = Session(panel)
    panel.replies = [framed(bytes([0x7F, 0, 0, 0xA5]))]
    await session.close()
    assert panel.sent[-1] == framed(m.disconnect().body)
    assert panel.closed
