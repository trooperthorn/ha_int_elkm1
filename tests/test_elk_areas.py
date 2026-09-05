"""Unit tests for helpers/elk/areas.py's `Area`/`Areas`. Closes a gap left by
the 2026-09-05 elkm1-lib removal (see docs/decisions.md): only exercised
indirectly before this file, through coordinator/alarm_control_panel tests
that mock the whole `Area` object rather than constructing a real one.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.helpers.elk.areas import Areas
from custom_components.elkm1.helpers.elk.const import (
    AlarmState,
    ArmedStatus,
    ArmLevel,
    ArmUpState,
)
from custom_components.elkm1.helpers.elk.notify import Notifier


def _areas() -> tuple[Areas, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    areas = Areas(connection, notifier)
    connection.reset_mock()
    return areas, connection, notifier


# --------------------------------------------------------------------------
# Area
# --------------------------------------------------------------------------


def test_is_armed_false_before_any_as_reply():
    areas, _connection, _notifier = _areas()
    assert areas[0].is_armed() is False


def test_is_armed_true_once_armed_status_is_set():
    areas, _connection, _notifier = _areas()
    areas[0].setattr("armed_status", ArmedStatus.ARMED_AWAY)
    assert areas[0].is_armed() is True


def test_in_alarm_state_false_for_benign_states():
    areas, _connection, _notifier = _areas()
    for benign in (None, AlarmState.NO_ALARM_ACTIVE, AlarmState.ENTRANCE_DELAY_ACTIVE, AlarmState.ALARM_ABORT_DELAY_ACTIVE):
        areas[0].alarm_state = benign
        assert areas[0].in_alarm_state() is False


def test_in_alarm_state_true_for_a_real_alarm():
    areas, _connection, _notifier = _areas()
    areas[0].alarm_state = AlarmState.FIRE_ALARM
    assert areas[0].in_alarm_state() is True


def test_arm_sends_al_when_not_already_armed():
    areas, connection, _notifier = _areas()
    areas[0].arm(ArmLevel.ARMED_AWAY, 1234)
    connection.send.assert_called_once()
    assert connection.send.call_args[0][0].message[2:4] == "a1"


def test_arm_is_a_noop_when_already_armed_at_a_different_level():
    """Arming an already-armed area (other than disarming it) must not
    re-send `al` - the panel already has a valid armed state."""
    areas, connection, _notifier = _areas()
    areas[0].setattr("armed_status", ArmedStatus.ARMED_AWAY)
    connection.reset_mock()

    areas[0].arm(ArmLevel.ARMED_STAY, 1234)

    connection.send.assert_not_called()


def test_disarm_is_allowed_even_when_armed():
    areas, connection, _notifier = _areas()
    areas[0].setattr("armed_status", ArmedStatus.ARMED_AWAY)
    connection.reset_mock()

    areas[0].disarm(1234)

    connection.send.assert_called_once()
    assert connection.send.call_args[0][0].message[2:4] == "a0"


def test_display_message_sends_dm_for_this_area():
    areas, connection, _notifier = _areas()
    areas[2].display_message(1, True, 30, "Hi", "There")
    connection.send.assert_called_once()
    assert connection.send.call_args[0][0].message[2:4] == "dm"


def test_bypass_sends_zb_999_for_this_area():
    areas, connection, _notifier = _areas()
    areas[0].bypass(1234)
    sent = connection.send.call_args[0][0].message
    assert sent[2:4] == "zb"
    assert sent[4:7] == "999"


def test_clear_bypass_sends_zb_000():
    areas, connection, _notifier = _areas()
    areas[0].clear_bypass(1234)
    sent = connection.send.call_args[0][0].message
    assert sent[4:7] == "000"


# --------------------------------------------------------------------------
# Areas
# --------------------------------------------------------------------------


def test_sync_requests_arming_status_and_names():
    areas, connection, _notifier = _areas()
    areas.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert "as" in sent_commands
    assert "sd" in sent_commands


def test_am_handler_sets_alarm_memory_per_area():
    areas, _connection, notifier = _areas()
    memory = [True, False, False, False, False, False, False, True]
    notifier.notify("AM", {"alarm_memory": memory})
    assert areas[0].alarm_memory is True
    assert areas[1].alarm_memory is False
    assert areas[7].alarm_memory is True


def test_as_handler_updates_every_area_and_ignores_timer_seconds():
    areas, _connection, notifier = _areas()
    notifier.notify(
        "AS",
        {
            "armed_statuses": [ArmedStatus.ARMED_AWAY] + [ArmedStatus.DISARMED] * 7,
            "arm_up_states": [ArmUpState.FULLY_ARMED] + [ArmUpState.NOT_READY_TO_ARM] * 7,
            "alarm_states": [AlarmState.NO_ALARM_ACTIVE] * 8,
            "timer_seconds": 9,
        },
    )
    assert areas[0].armed_status == ArmedStatus.ARMED_AWAY
    assert areas[0].arm_up_state == ArmUpState.FULLY_ARMED
    assert not hasattr(areas[0], "timer_seconds")


def test_as_handler_requests_az_when_a_new_alarm_starts():
    _areas_obj, connection, notifier = _areas()
    notifier.notify(
        "AS",
        {
            "armed_statuses": [ArmedStatus.ARMED_AWAY] + [ArmedStatus.DISARMED] * 7,
            "arm_up_states": [ArmUpState.FULLY_ARMED] + [ArmUpState.NOT_READY_TO_ARM] * 7,
            "alarm_states": [AlarmState.FIRE_ALARM] + [AlarmState.NO_ALARM_ACTIVE] * 7,
            "timer_seconds": 0,
        },
    )
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert "az" in sent_commands


def test_as_handler_does_not_request_az_when_nothing_changed_and_no_alarm():
    _areas_obj, connection, notifier = _areas()
    payload = {
        "armed_statuses": [ArmedStatus.DISARMED] * 8,
        "arm_up_states": [ArmUpState.NOT_READY_TO_ARM] * 8,
        "alarm_states": [AlarmState.NO_ALARM_ACTIVE] * 8,
        "timer_seconds": 0,
    }
    notifier.notify("AS", payload)
    connection.reset_mock()
    notifier.notify("AS", payload)  # identical, no-alarm - must not re-request AZ

    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert "az" not in sent_commands


def test_ee_handler_updates_the_named_areas_timers():
    areas, _connection, notifier = _areas()
    notifier.notify(
        "EE",
        {"area": 3, "is_exit": True, "timer1": 15, "timer2": 0, "armed_status": ArmedStatus.ARMED_AWAY},
    )
    assert areas[3].timer1 == 15
    assert areas[3].timer2 == 0
    assert areas[3].is_exit is True
    assert areas[3].armed_status == ArmedStatus.ARMED_AWAY


def test_ld_handler_tags_user_number_for_specific_events():
    """Events 1173/1174 carry a user number in the `number` field, not a
    generic log-entry index - see `_ld_handler`'s own inline comment."""
    areas, _connection, notifier = _areas()
    log = {"event": 1173, "number": 7, "index": 1, "timestamp": "2026-09-05T00:00:00+00:00"}
    notifier.notify("LD", {"area": 0, "log": log})
    assert areas[0].last_log["user_number"] == 7


def test_ld_handler_leaves_other_events_untagged():
    areas, _connection, notifier = _areas()
    log = {"event": 1000, "number": 7, "index": 1, "timestamp": "2026-09-05T00:00:00+00:00"}
    notifier.notify("LD", {"area": 0, "log": log})
    assert "user_number" not in areas[0].last_log


def test_kf_handler_sets_the_chime_mode_name_per_area():
    areas, _connection, notifier = _areas()
    notifier.notify("KF", {"keypad": 0, "key": "0", "chime_mode": [1] + [0] * 7})
    assert areas[0].chime_mode == ("CHIME", 1)


def test_kf_handler_tolerates_an_undocumented_chime_mode_value():
    areas, _connection, notifier = _areas()
    notifier.notify("KF", {"keypad": 0, "key": "0", "chime_mode": [99] + [0] * 7})
    assert areas[0].chime_mode == ("", 99)
