"""Unit tests for helpers/elk/settings.py's `Setting`/`Settings`. Closes a
gap left by the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.elkm1.helpers.elk.const import SettingFormat
from custom_components.elkm1.helpers.elk.notify import Notifier
from custom_components.elkm1.helpers.elk.settings import Settings


def _settings() -> tuple[Settings, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    settings = Settings(connection, notifier)
    connection.reset_mock()
    return settings, connection, notifier


def test_value_defaults_to_none_until_a_cr_reply_arrives():
    settings, _connection, _notifier = _settings()
    assert settings[0].value is None


def test_set_a_number_value_sends_cw():
    settings, connection, _notifier = _settings()
    settings[0].set(500)
    assert connection.send.call_args[0][0].message[2:4] == "cw"


def test_set_rejects_a_tuple_when_format_is_not_time_of_day():
    settings, _connection, _notifier = _settings()
    with pytest.raises(ValueError, match="wrong format"):
        settings[0].set((12, 30))


def test_set_rejects_a_non_tuple_when_format_is_time_of_day():
    settings, _connection, _notifier = _settings()
    settings[0].value_format = SettingFormat.TIME_OF_DAY
    with pytest.raises(ValueError, match="must have tuple"):
        settings[0].set(500)


def test_set_accepts_a_tuple_when_format_is_time_of_day():
    settings, connection, _notifier = _settings()
    settings[0].value_format = SettingFormat.TIME_OF_DAY
    settings[0].set((12, 30))
    assert connection.send.call_args[0][0].message[2:4] == "cw"


def test_sync_requests_all_values_and_names():
    settings, connection, _notifier = _settings()
    settings.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["cp", "sd"]


def test_cr_handler_updates_matching_settings_by_index():
    settings, _connection, notifier = _settings()
    notifier.notify(
        "CR",
        {
            "values": [
                {"index": 0, "value": 120, "value_format": SettingFormat.NUMBER},
                {"index": 5, "value": (12, 30), "value_format": SettingFormat.TIME_OF_DAY},
            ]
        },
    )
    assert settings[0].value == 120
    assert settings[0].value_format == SettingFormat.NUMBER
    assert settings[5].value == (12, 30)
    assert settings[5].value_format == SettingFormat.TIME_OF_DAY
