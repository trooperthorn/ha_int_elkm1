"""Tests for climate.py: hvac/fan mode translation, setpoint properties,
and the command methods that write mode/fan/setpoint changes back to the
panel.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.climate.const import HVACMode
from homeassistant.const import ATTR_TEMPERATURE

from custom_components.elkm1.climate import ElkThermostat, async_setup_entry
from custom_components.elkm1.helpers.elk.const import (
    ThermostatFan,
    ThermostatMode,
    ThermostatSetting,
)
from custom_components.elkm1.models import ElkPanelData, ElkRuntimeData


def _thermostat(index: int, tstat_obj) -> ElkThermostat:
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(thermostats=[tstat_obj])

    config_entry = MagicMock()
    config_entry.entry_id = "entry1"

    entity = ElkThermostat(coordinator, config_entry, index)

    async def _confirm(sender, *_args, **_kwargs):
        sender()
        return True

    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm)
    return entity


def test_init_sets_unique_id_and_supported_modes():
    tstat = MagicMock()
    entity = _thermostat(0, tstat)

    assert entity._attr_unique_id == "entry1_thermostat_1"
    assert set(entity._attr_hvac_modes) == {
        HVACMode.OFF,
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.HEAT_COOL,
    }
    assert set(entity._attr_fan_modes) == {"auto", "on"}


def test_get_obj_returns_none_when_index_out_of_range():
    entity = _thermostat(0, MagicMock())
    entity._index = 5

    assert entity._get_obj() is None


def test_name_uses_panel_name_when_available():
    tstat = MagicMock()
    tstat.name = "Upstairs"
    entity = _thermostat(0, tstat)

    assert entity.name == "Upstairs"


def test_name_falls_back_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    assert entity.name == "Thermostat 10"


def test_hvac_mode_is_none_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    assert entity.hvac_mode is None


def test_hvac_mode_is_none_when_mode_unset():
    tstat = MagicMock()
    tstat.mode = None
    entity = _thermostat(0, tstat)

    assert entity.hvac_mode is None


def test_hvac_mode_maps_enum_with_value_attribute():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.COOL
    entity = _thermostat(0, tstat)

    assert entity.hvac_mode == HVACMode.COOL


def test_hvac_mode_maps_raw_int_without_value_attribute():
    tstat = MagicMock(spec=["mode", "fan", "current_temp", "heat_setpoint", "cool_setpoint"])
    tstat.mode = 1
    entity = _thermostat(0, tstat)

    assert entity.hvac_mode == HVACMode.HEAT


def test_hvac_mode_emergency_heat_maps_to_heat():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.EMERGENCY_HEAT
    entity = _thermostat(0, tstat)

    assert entity.hvac_mode == HVACMode.HEAT


def test_fan_mode_is_none_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    assert entity.fan_mode is None


def test_fan_mode_is_none_when_fan_unset():
    tstat = MagicMock()
    tstat.fan = None
    entity = _thermostat(0, tstat)

    assert entity.fan_mode is None


def test_fan_mode_maps_elk_fan_to_ha():
    tstat = MagicMock()
    tstat.fan = ThermostatFan.ON
    entity = _thermostat(0, tstat)

    assert entity.fan_mode == "on"


def test_current_temperature_is_none_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    assert entity.current_temperature is None


def test_current_temperature_reads_from_obj():
    tstat = MagicMock()
    tstat.current_temp = 72
    entity = _thermostat(0, tstat)

    assert entity.current_temperature == 72.0


def test_target_temperature_is_none_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    assert entity.target_temperature is None


def test_target_temperature_is_none_outside_heat_or_cool_mode():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.AUTO
    entity = _thermostat(0, tstat)

    assert entity.target_temperature is None


def test_target_temperature_uses_heat_setpoint_in_heat_mode():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.HEAT
    tstat.heat_setpoint = 68
    entity = _thermostat(0, tstat)

    assert entity.target_temperature == 68.0


def test_target_temperature_uses_cool_setpoint_in_cool_mode():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.COOL
    tstat.cool_setpoint = 75
    entity = _thermostat(0, tstat)

    assert entity.target_temperature == 75.0


def test_target_temperature_high_is_none_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    assert entity.target_temperature_high is None


def test_target_temperature_high_is_none_outside_heat_cool_mode():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.HEAT
    entity = _thermostat(0, tstat)

    assert entity.target_temperature_high is None


def test_target_temperature_high_uses_cool_setpoint_in_heat_cool_mode():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.AUTO
    tstat.cool_setpoint = 78
    entity = _thermostat(0, tstat)

    assert entity.target_temperature_high == 78.0


def test_target_temperature_low_is_none_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    assert entity.target_temperature_low is None


def test_target_temperature_low_is_none_outside_heat_cool_mode():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.COOL
    entity = _thermostat(0, tstat)

    assert entity.target_temperature_low is None


def test_target_temperature_low_uses_heat_setpoint_in_heat_cool_mode():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.AUTO
    tstat.heat_setpoint = 65
    entity = _thermostat(0, tstat)

    assert entity.target_temperature_low == 65.0


async def test_async_set_hvac_mode_sends_ts_mode_command():
    tstat = MagicMock()
    entity = _thermostat(0, tstat)

    await entity.async_set_hvac_mode(HVACMode.COOL)

    tstat.set.assert_called_once_with(ThermostatSetting.MODE, ThermostatMode.COOL)


async def test_async_set_hvac_mode_is_a_noop_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    await entity.async_set_hvac_mode(HVACMode.COOL)

    entity.coordinator.async_confirm_command.assert_not_called()


async def test_async_set_fan_mode_sends_ts_fan_command():
    tstat = MagicMock()
    entity = _thermostat(0, tstat)

    await entity.async_set_fan_mode("on")

    tstat.set.assert_called_once_with(ThermostatSetting.FAN, ThermostatFan.ON)


async def test_async_set_fan_mode_is_a_noop_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    await entity.async_set_fan_mode("on")

    entity.coordinator.async_confirm_command.assert_not_called()


async def test_async_set_temperature_is_a_noop_when_obj_missing():
    entity = _thermostat(0, MagicMock())
    entity._index = 9

    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 70})

    entity.coordinator.async_confirm_command.assert_not_called()


async def test_async_set_temperature_uses_heat_setpoint_in_heat_mode():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.HEAT
    entity = _thermostat(0, tstat)

    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 70})

    tstat.set.assert_called_once_with(ThermostatSetting.HEAT_SETPOINT, 70)


async def test_async_set_temperature_uses_cool_setpoint_outside_heat_mode():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.COOL
    entity = _thermostat(0, tstat)

    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 74})

    tstat.set.assert_called_once_with(ThermostatSetting.COOL_SETPOINT, 74)


async def test_async_set_temperature_sets_low_and_high_setpoints_together():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.AUTO
    entity = _thermostat(0, tstat)

    await entity.async_set_temperature(target_temp_low=65, target_temp_high=78)

    tstat.set.assert_any_call(ThermostatSetting.HEAT_SETPOINT, 65)
    tstat.set.assert_any_call(ThermostatSetting.COOL_SETPOINT, 78)
    assert tstat.set.call_count == 2


async def test_setup_entry_creates_entity_for_configured_thermostat(hass, mock_network_entry):
    tstat = MagicMock()
    tstat.index = 0
    tstat.configured = True
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(thermostats=[tstat])
    coordinator.async_add_listener.return_value = lambda: None

    mock_network_entry.add_to_hass(hass)
    mock_network_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_network_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []
    await async_setup_entry(hass, mock_network_entry, lambda ents: added.extend(ents))

    assert len(added) == 1
    assert isinstance(added[0], ElkThermostat)
