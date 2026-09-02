"""Tests for entry-owned transport lifecycle behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from elkm1_lib import Elk
from elkm1_lib.connection import Connection

from custom_components.elkm1.helpers.transport import ElkConnectionManager


def test_manager_does_not_patch_global_connection_class() -> None:
    """Constructing a manager changes only its entry's connection instance."""
    original_connect = Connection.connect
    manager = ElkConnectionManager(Elk({"url": "elk://127.0.0.1:2101"}))

    assert Connection.connect is original_connect
    assert manager.connection.connect is not original_connect


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
