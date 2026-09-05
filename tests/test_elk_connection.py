"""Unit tests for helpers/elk/connection.py's `Connection`: the outbound
write queue, checksum-on-write, response correlation, pause/resume, and
disconnect. This is the class the 2026-09-05 elkm1-lib removal (see
docs/decisions.md) rewrote from elkm1-lib's private-attribute pattern into
public state - the highest-risk piece of that rewrite, and the one with the
least direct test coverage before this file (only exercised incidentally
through tests/test_transport.py's entry-owned supervisor tests).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.elkm1.helpers.elk.connection import Connection, QueuedWrite
from custom_components.elkm1.helpers.elk.message import checksum
from custom_components.elkm1.helpers.elk.notify import Notifier


def _connected(url: str = "elk://test") -> Connection:
    connection = Connection(url, Notifier())
    connection.writer = MagicMock()
    return connection


# --------------------------------------------------------------------------
# send / send_raw / _send
# --------------------------------------------------------------------------


def test_send_rejects_when_disconnected():
    connection = Connection("elk://test", Notifier())
    with pytest.raises(ConnectionError, match="disconnected"):
        connection.send(MagicMock(message="06vn00", response_command="VN"))


def test_send_rejects_while_paused():
    connection = _connected()
    connection.pause()
    with pytest.raises(ConnectionError, match="paused"):
        connection.send(MagicMock(message="06vn00", response_command="VN"))


def test_send_raw_rejects_when_disconnected():
    connection = Connection("elk://test", Notifier())
    with pytest.raises(ConnectionError, match="disconnected"):
        connection.send_raw("someuser")


def test_send_raw_rejects_while_paused():
    connection = _connected()
    connection.pause()
    with pytest.raises(ConnectionError, match="paused"):
        connection.send_raw("someuser")


def test_send_queues_in_fifo_order_by_default():
    connection = _connected()
    connection.send(MagicMock(message="one", response_command=None))
    connection.send(MagicMock(message="two", response_command=None))

    assert [q.msg for q in connection._write_queue] == ["one", "two"]


def test_send_with_priority_jumps_the_queue():
    connection = _connected()
    connection.send(MagicMock(message="normal", response_command=None))
    connection.send(MagicMock(message="urgent", response_command=None), priority_send=True)

    assert [q.msg for q in connection._write_queue] == ["urgent", "normal"]


def test_send_raw_queues_a_raw_entry_with_no_response_command():
    connection = _connected()
    connection.send_raw("myusername")

    entry = connection._write_queue[0]
    assert entry == QueuedWrite("myusername", None, timeout=5.0, raw=True)


def test_send_sets_the_check_write_queue_event():
    connection = _connected()
    assert not connection._check_write_queue.is_set()
    connection.send(MagicMock(message="vn", response_command=None))
    assert connection._check_write_queue.is_set()


# --------------------------------------------------------------------------
# pause / resume / is_paused / is_connected
# --------------------------------------------------------------------------


def test_pause_clears_the_queue_and_blocks_further_sends():
    connection = _connected()
    connection.send(MagicMock(message="queued", response_command=None))

    connection.pause()

    assert connection.is_paused() is True
    assert len(connection._write_queue) == 0
    with pytest.raises(ConnectionError):
        connection.send(MagicMock(message="rejected", response_command=None))


def test_resume_allows_sends_again():
    connection = _connected()
    connection.pause()
    connection.resume()

    assert connection.is_paused() is False
    connection.send(MagicMock(message="ok", response_command=None))
    assert len(connection._write_queue) == 1


def test_is_connected_reflects_writer_presence():
    connection = Connection("elk://test", Notifier())
    assert connection.is_connected() is False
    connection.writer = MagicMock()
    assert connection.is_connected() is True


# --------------------------------------------------------------------------
# heartbeat
# --------------------------------------------------------------------------


def test_heartbeat_sets_the_heartbeat_event():
    connection = Connection("elk://test", Notifier())
    assert not connection.heartbeat_event.is_set()
    connection.heartbeat()
    assert connection.heartbeat_event.is_set()


# --------------------------------------------------------------------------
# disconnect
# --------------------------------------------------------------------------


def test_disconnect_closes_the_writer_and_notifies():
    connection = _connected()
    writer = connection.writer
    disconnected = []
    connection._notifier.attach("disconnected", lambda: disconnected.append(1))

    connection.disconnect()

    writer.close.assert_called_once()
    assert connection.writer is None
    assert disconnected == [1]


async def test_disconnect_cancels_owned_tasks_but_not_the_caller():
    connection = _connected()
    ran_forever = asyncio.Event()

    async def _child() -> None:
        await ran_forever.wait()

    task = asyncio.create_task(_child(), name="elkm1-child")
    connection.tasks.add(task)

    connection.disconnect()
    await asyncio.sleep(0)  # let the cancellation propagate

    assert task.cancelled()
    assert connection.tasks == set()


def test_disconnect_logs_the_reason_when_given(caplog):
    connection = _connected()
    connection.disconnect(reason="heartbeat timeout")
    assert "heartbeat timeout" in caplog.text


# --------------------------------------------------------------------------
# _write_stream
# --------------------------------------------------------------------------


async def test_write_stream_writes_a_checksummed_crlf_terminated_frame():
    connection = Connection("elk://test", Notifier())
    writer = MagicMock()
    connection.writer = writer
    connection.send(MagicMock(message="06vn00", response_command=None))

    async def _run_one_iteration() -> None:
        stream_task = asyncio.create_task(connection._write_stream())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        connection.writer = None
        connection._check_write_queue.set()
        await stream_task

    await _run_one_iteration()

    writer.write.assert_called_once()
    sent_bytes = writer.write.call_args[0][0]
    assert sent_bytes == f"06vn00{checksum('06vn00')}\r\n".encode()


async def test_write_stream_writes_a_raw_frame_with_no_checksum():
    connection = Connection("elk://test", Notifier())
    writer = MagicMock()
    connection.writer = writer
    connection.send_raw("myusername")

    stream_task = asyncio.create_task(connection._write_stream())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    connection.writer = None
    connection._check_write_queue.set()
    await stream_task

    writer.write.assert_called_once_with(b"myusername\r\n")


async def test_write_stream_clears_awaiting_response_once_reply_arrives():
    connection = Connection("elk://test", Notifier())
    connection.writer = MagicMock()
    connection.send(MagicMock(message="06as00", response_command="AS"))

    stream_task = asyncio.create_task(connection._write_stream())
    await asyncio.sleep(0)  # frame written, now awaiting "AS"
    assert connection.awaiting_response_command == "AS"

    connection.response_received.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert connection.awaiting_response_command is None
    assert not connection.response_received.is_set()

    connection.writer = None
    connection._check_write_queue.set()
    await stream_task


async def test_write_stream_notifies_timeout_when_no_reply_arrives(monkeypatch):
    """A queued command whose response never arrives must notify "timeout"
    with the expected response command, not hang the write loop forever."""
    import custom_components.elkm1.helpers.elk.connection as connection_module

    monkeypatch.setattr(connection_module, "MESSAGE_RESPONSE_TIME", 0.01)
    connection = Connection("elk://test", Notifier())
    connection.writer = MagicMock()
    timeouts = []
    connection._notifier.attach("timeout", lambda **kwargs: timeouts.append(kwargs))
    connection.send(MagicMock(message="06as00", response_command="AS"))

    stream_task = asyncio.create_task(connection._write_stream())
    await asyncio.sleep(0.05)

    assert timeouts == [{"msg_code": "AS"}]
    assert connection.awaiting_response_command is None

    connection.writer = None
    connection._check_write_queue.set()
    await stream_task


def test_message_response_time_is_short_relative_to_a_lost_reply_s_blast_radius():
    """Every later queued write stalls for up to MESSAGE_RESPONSE_TIME behind
    one lost/corrupted reply, not just the command that lost it (see
    _write_stream's await_msg_response). Real round trips measured live
    against hardware are ~50-350ms (docs/live_qualification.md 2026-09-05);
    this pins the ceiling to a value that bounds that blast radius instead of
    the 5.0s default that let a single lost reply cascade a full periodic
    status refresh (AS/AZ/CS/SS/LW) past its own 12s aggregate timeout - see
    docs/decisions.md 2026-09-05."""
    import custom_components.elkm1.helpers.elk.connection as connection_module

    assert connection_module.MESSAGE_RESPONSE_TIME <= 2.0


async def test_write_stream_recovers_and_sends_a_second_item_after_the_first_times_out(
    monkeypatch,
):
    """The drain loop must still send a later queued command after an earlier
    one's reply never arrives - proves a lost reply merely delays, rather
    than permanently blocks, everything queued behind it."""
    import custom_components.elkm1.helpers.elk.connection as connection_module

    monkeypatch.setattr(connection_module, "MESSAGE_RESPONSE_TIME", 0.01)
    connection = Connection("elk://test", Notifier())
    writer = MagicMock()
    connection.writer = writer
    connection.send(MagicMock(message="06as00", response_command="AS"))
    connection.send(MagicMock(message="06az00", response_command="AZ"))

    stream_task = asyncio.create_task(connection._write_stream())
    await asyncio.sleep(0.1)

    assert writer.write.call_count == 2

    connection.writer = None
    connection._check_write_queue.set()
    await stream_task


async def test_write_stream_exits_once_writer_is_cleared_and_queue_is_empty():
    connection = Connection("elk://test", Notifier())
    connection.writer = MagicMock()
    stream_task = asyncio.create_task(connection._write_stream())
    await asyncio.sleep(0)

    connection.writer = None
    connection._check_write_queue.set()

    await asyncio.wait_for(stream_task, timeout=1.0)
    assert stream_task.done()
