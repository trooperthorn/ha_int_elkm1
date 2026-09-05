"""Unit tests for helpers/elk/counters.py's `Counter`/`Counters`. Closes a
gap left by the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.helpers.elk.const import TextDescriptions
from custom_components.elkm1.helpers.elk.counters import Counters
from custom_components.elkm1.helpers.elk.notify import Notifier


def _counters() -> tuple[Counters, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    counters = Counters(connection, notifier)
    connection.reset_mock()
    return counters, connection, notifier


def test_value_defaults_to_none_until_a_cv_reply_arrives():
    """Real protocol state, not a bug - see counters.py's own module
    docstring and docs/decisions.md 2026-09-05."""
    counters, _connection, _notifier = _counters()
    assert counters[0].value is None


def test_get_sends_cv():
    counters, connection, _notifier = _counters()
    counters[0].get()
    assert connection.send.call_args[0][0].message[2:4] == "cv"


def test_set_sends_cx_with_the_value():
    counters, connection, _notifier = _counters()
    counters[0].set(42)
    sent = connection.send.call_args[0][0].message
    assert sent[2:4] == "cx"
    assert sent[6:11] == "00042"


def test_configured_was_set_priority_requests_the_value():
    counters, connection, notifier = _counters()
    counters.get_descriptions(TextDescriptions.COUNTER.value)
    connection.reset_mock()

    notifier.notify(
        "SD",
        {"desc_type": TextDescriptions.COUNTER.value.desc_type, "unit": 0, "desc": "Rain Total", "show_on_keypad": False},
    )

    cv_call = next(
        call for call in connection.send.call_args_list if call.args[0].message[2:4] == "cv"
    )
    assert cv_call.kwargs == {"priority_send": True}


def test_sync_only_requests_names_values_are_fetched_on_demand():
    counters, connection, _notifier = _counters()
    counters.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["sd"]


def test_cv_handler_sets_the_named_counters_value():
    counters, _connection, notifier = _counters()
    notifier.notify("CV", {"counter": 2, "value": 42})
    assert counters[2].value == 42
