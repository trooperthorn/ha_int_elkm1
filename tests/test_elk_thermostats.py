"""Unit tests for helpers/elk/thermostats.py's `Thermostat`/`Thermostats`.
Closes a gap left by the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.elkm1.helpers.elk.const import (
    ThermostatFan,
    ThermostatMode,
    ThermostatSetting,
)
from custom_components.elkm1.helpers.elk.notify import Notifier
from custom_components.elkm1.helpers.elk.thermostats import Thermostats


def _thermostats() -> tuple[Thermostats, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    thermostats = Thermostats(connection, notifier)
    connection.reset_mock()
    return thermostats, connection, notifier


def test_set_mode_sends_ts_with_the_enum_value():
    thermostats, connection, _notifier = _thermostats()
    thermostats[0].set(ThermostatSetting.MODE, ThermostatMode.COOL)
    sent = connection.send.call_args[0][0].message
    assert sent[2:4] == "ts"
    assert sent[6:8] == f"{ThermostatMode.COOL.value:02}"
    assert sent[8] == str(ThermostatSetting.MODE.value)


def test_set_hold_encodes_bool_as_0_or_1():
    thermostats, connection, _notifier = _thermostats()
    thermostats[0].set(ThermostatSetting.HOLD, True)
    sent = connection.send.call_args[0][0].message
    assert sent[6:8] == "01"


def test_set_a_setpoint_passes_the_int_through():
    thermostats, connection, _notifier = _thermostats()
    thermostats[0].set(ThermostatSetting.HEAT_SETPOINT, 70)
    sent = connection.send.call_args[0][0].message
    assert sent[6:8] == "70"


def test_set_rejects_a_type_mismatched_value():
    thermostats, _connection, _notifier = _thermostats()
    with pytest.raises(ValueError, match="Wrong type"):
        thermostats[0].set(ThermostatSetting.MODE, "cool")  # type: ignore[arg-type]


def test_configured_was_set_priority_requests_full_thermostat_data():
    """Once a thermostat's name syncs (first `configured`), its full `tr`
    data must be requested with priority so it doesn't wait behind the rest
    of the sync queue."""
    thermostats, connection, notifier = _thermostats()
    text_desc = thermostats._text_desc  # set by the constructor's sync() call chain
    if text_desc is None:
        thermostats.sync()
        text_desc = thermostats._text_desc
    connection.reset_mock()

    notifier.notify(
        "SD",
        {"desc_type": text_desc.desc_type, "unit": 0, "desc": "Living Room", "show_on_keypad": False},
    )

    sent = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert "tr" in sent
    tr_call = next(
        call for call in connection.send.call_args_list if call.args[0].message[2:4] == "tr"
    )
    assert tr_call.kwargs == {"priority_send": True}


def test_sync_only_requests_names():
    thermostats, connection, _notifier = _thermostats()
    thermostats.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["sd"]


def test_st_handler_updates_group_two_only():
    thermostats, _connection, notifier = _thermostats()
    notifier.notify("ST", {"group": 2, "device": 0, "temperature": 72})
    assert thermostats[0].current_temp == 72

    notifier.notify("ST", {"group": 0, "device": 0, "temperature": 99})
    assert thermostats[0].current_temp == 72  # group 0 is zones, not thermostats


def test_tr_handler_updates_every_field():
    thermostats, _connection, notifier = _thermostats()
    notifier.notify(
        "TR",
        {
            "thermostat_index": 0,
            "mode": ThermostatMode.COOL,
            "hold": False,
            "fan": ThermostatFan.AUTO,
            "current_temp": 72,
            "heat_setpoint": 68,
            "cool_setpoint": 75,
            "humidity": 0,
        },
    )
    thermostat = thermostats[0]
    assert thermostat.mode == ThermostatMode.COOL
    assert thermostat.hold is False
    assert thermostat.fan == ThermostatFan.AUTO
    assert thermostat.current_temp == 72
    assert thermostat.heat_setpoint == 68
    assert thermostat.cool_setpoint == 75
    assert thermostat.humidity == 0
