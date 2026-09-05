"""Unit tests for helpers/elk/tasks.py's `Task`/`Tasks`. Closes a gap left by
the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.helpers.elk.notify import Notifier
from custom_components.elkm1.helpers.elk.tasks import Tasks


def _tasks() -> tuple[Tasks, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    tasks = Tasks(connection, notifier)
    connection.reset_mock()
    return tasks, connection, notifier


def test_activate_sends_tn():
    tasks, connection, _notifier = _tasks()
    tasks[0].activate()
    assert connection.send.call_args[0][0].message[2:4] == "tn"


def test_sync_only_requests_names_tasks_have_no_queryable_state():
    tasks, connection, _notifier = _tasks()
    tasks.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["sd"]


def test_tc_handler_records_the_activation_time():
    tasks, _connection, notifier = _tasks()
    assert tasks[0].last_change is None
    notifier.notify("TC", {"task": 0})
    assert tasks[0].last_change is not None
