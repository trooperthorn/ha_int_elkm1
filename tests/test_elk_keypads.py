"""Unit tests for helpers/elk/keypads.py's `Keypad`/`Keypads`. Closes a gap
left by the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.helpers.elk.const import FunctionKeys, Max
from custom_components.elkm1.helpers.elk.keypads import Keypads
from custom_components.elkm1.helpers.elk.notify import Notifier


def _keypads() -> tuple[Keypads, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    keypads = Keypads(connection, notifier)
    connection.reset_mock()
    return keypads, connection, notifier


def test_press_function_key_sends_kf():
    keypads, connection, _notifier = _keypads()
    keypads[0].press_function_key(FunctionKeys.STAR)
    sent = connection.send.call_args[0][0].message
    assert sent[2:4] == "kf"
    assert sent[6] == "*"


def test_sync_requests_areas_names_and_function_key_state():
    keypads, connection, _notifier = _keypads()
    keypads.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["ka", "sd", "kf"]


def test_ic_handler_masks_a_valid_code_but_echoes_an_invalid_one():
    keypads, _connection, notifier = _keypads()
    notifier.notify("IC", {"code": "003456", "user": 2, "keypad": 0})
    assert keypads[0].code == "****"
    assert keypads[0].last_user == 2

    notifier.notify("IC", {"code": "003456", "user": -1, "keypad": 0})
    assert keypads[0].code == "003456"
    assert keypads[0].last_user == -1


def test_ka_handler_sets_area_only_for_non_negative_assignments():
    keypads, _connection, notifier = _keypads()
    areas = [-1] * Max.KEYPADS.value
    areas[0] = 2
    notifier.notify("KA", {"keypad_areas": areas})
    assert keypads[0].area == 2
    assert keypads[1].area == -1  # unchanged default, -1 assignment skipped


def test_kc_handler_ignores_no_key():
    keypads, _connection, notifier = _keypads()
    notifier.notify("KC", {"keypad": 0, "key": 0})
    assert keypads[0].last_keypress is None


def test_kc_handler_records_a_known_key():
    keypads, _connection, notifier = _keypads()
    notifier.notify("KC", {"keypad": 0, "key": 11})
    name, key = keypads[0].last_keypress
    assert key == 11
    assert name  # a real KeypadKeys member name, not ""


def test_kc_handler_tolerates_an_undocumented_key_value():
    keypads, _connection, notifier = _keypads()
    notifier.notify("KC", {"keypad": 0, "key": 250})
    name, key = keypads[0].last_keypress
    assert key == 250
    assert name == ""


def test_kf_handler_records_the_function_key_and_resets_force_sync():
    keypads, _connection, notifier = _keypads()
    notifier.notify("KF", {"keypad": 0, "key": "1", "chime_mode": [0] * 8})
    name, key = keypads[0].last_function_key
    assert key == "1"
    assert name == "F1"


def test_kf_handler_tolerates_an_undocumented_key_value():
    keypads, _connection, notifier = _keypads()
    notifier.notify("KF", {"keypad": 0, "key": "Z", "chime_mode": [0] * 8})
    name, _key = keypads[0].last_function_key
    assert name == ""


def test_lw_handler_updates_keypad_temperature_and_ignores_the_no_probe_sentinel():
    keypads, _connection, notifier = _keypads()
    temps = [-40] * Max.KEYPADS.value
    temps[0] = 32
    notifier.notify("LW", {"keypad_temps": temps, "zone_temps": [-60] * 16})
    assert keypads[0].temperature == 32
    assert keypads[1].temperature == -40


def test_st_handler_updates_group_one_only():
    keypads, _connection, notifier = _keypads()
    notifier.notify("ST", {"group": 1, "device": 0, "temperature": 72})
    assert keypads[0].temperature == 72

    notifier.notify("ST", {"group": 0, "device": 0, "temperature": 99})
    assert keypads[0].temperature == 72  # group 0 is zones, not keypads
