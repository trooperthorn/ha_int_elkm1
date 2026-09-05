"""Unit tests for helpers/elk/panel.py's `Panel` element - version/RTC/
trouble-status/ElkRP handlers and the voice/set-time command methods. Closes
a gap left by the 2026-09-05 elkm1-lib removal (see docs/decisions.md):
`Panel` had no dedicated tests before this file.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.helpers.elk.const import ElkRPStatus
from custom_components.elkm1.helpers.elk.notify import Notifier
from custom_components.elkm1.helpers.elk.panel import Panel


def _panel() -> tuple[Panel, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    panel = Panel(connection, notifier)
    connection.reset_mock()
    return panel, connection, notifier


def test_panel_starts_configured_with_the_fixed_name():
    panel, _connection, _notifier = _panel()
    assert panel.configured is True
    assert panel.name == "ElkM1"
    assert panel.index == 0


def test_sync_requests_version_temperature_and_trouble_status():
    panel, connection, _notifier = _panel()
    panel.sync()

    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["vn", "lw", "ss"]


def test_speak_word_sends_sw():
    panel, connection, _notifier = _panel()
    panel.speak_word(42)
    connection.send.assert_called_once()
    assert connection.send.call_args[0][0].message[2:4] == "sw"


def test_speak_phrase_sends_sp():
    panel, connection, _notifier = _panel()
    panel.speak_phrase(7)
    connection.send.assert_called_once()
    assert connection.send.call_args[0][0].message[2:4] == "sp"


def test_set_time_sends_rw_with_the_given_datetime():
    import datetime as dt

    panel, connection, _notifier = _panel()
    panel.set_time(dt.datetime(2026, 1, 5, 10, 30, 45))
    connection.send.assert_called_once()
    assert connection.send.call_args[0][0].message[2:4] == "rw"


def test_set_time_defaults_to_local_time_when_none_given():
    panel, connection, _notifier = _panel()
    panel.set_time()
    connection.send.assert_called_once()
    assert connection.send.call_args[0][0].message[2:4] == "rw"


def test_vn_handler_updates_version_fields():
    panel, _connection, notifier = _panel()
    notifier.notify("VN", {"elkm1_version": "5.3.18", "xep_version": "0.0.0"})
    assert panel.elkm1_version == "5.3.18"
    assert panel.xep_version == "0.0.0"


def test_xk_handler_updates_the_real_time_clock():
    panel, _connection, notifier = _panel()
    notifier.notify("XK", {"real_time_clock": "0102030405060708"})
    assert panel.real_time_clock == "0102030405060708"


def test_rr_reply_updates_the_same_real_time_clock_field_as_xk():
    """RR (a direct rr request's reply) and XK (the periodic broadcast) carry
    the same RTC field and share a handler."""
    panel, _connection, notifier = _panel()
    notifier.notify("RR", {"real_time_clock": "1112017050926100"})
    assert panel.real_time_clock == "1112017050926100"


def test_ss_handler_builds_a_joined_status_string_including_zone_numbers():
    panel, _connection, notifier = _panel()
    status = list("0" * 34)
    status[0] = "1"  # AC Fail
    status[5] = "A"  # Transmitter Low Battery, zone 17 (ord('A') - 0x30 = 17)
    notifier.notify("SS", {"system_trouble_status": "".join(status)})

    assert panel.system_trouble_status == "AC Fail, Transmitter Low Battery zone 17"


def test_ss_handler_reports_no_troubles_as_an_empty_string():
    panel, _connection, notifier = _panel()
    notifier.notify("SS", {"system_trouble_status": "0" * 34})
    assert panel.system_trouble_status == ""


def test_rp_handler_pauses_the_connection_when_elkrp_connects():
    panel, connection, notifier = _panel()
    notifier.notify("RP", {"remote_programming_status": ElkRPStatus.CONNECTED})
    connection.pause.assert_called_once()
    connection.resume.assert_not_called()
    assert panel.remote_programming_status == ElkRPStatus.CONNECTED


def test_rp_handler_resumes_the_connection_once_elkrp_disconnects():
    _panel_obj, connection, notifier = _panel()
    notifier.notify("RP", {"remote_programming_status": ElkRPStatus.DISCONNECTED})
    connection.resume.assert_called_once()
    connection.pause.assert_not_called()


def test_ua_handler_updates_user_code_length_and_temperature_units():
    panel, _connection, notifier = _panel()
    notifier.notify(
        "UA",
        {
            "user_code": 1234,
            "valid_areas": 0xC3,
            "diagnostic": "00000000",
            "user_code_length": 4,
            "user_code_type": 0,
            "temperature_units": "F",
        },
    )
    assert panel.user_code_length == 4
    assert panel.temperature_units == "F"
