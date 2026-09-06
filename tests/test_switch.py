"""Tests for switch.py: output on/off/turn-on-for.

Zone bypass moved off this platform entirely - see
custom_components.elkm1.binary_sensor.ElkZoneBypassBinarySensor's docstring
and docs/decisions.md 2026-09-05 for why a switch anyone could flip with no
code prompt was a real security gap, not just a style choice.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.elkm1.helpers.elk.const import ThermostatMode
from custom_components.elkm1.models import ElkPanelData, ElkRuntimeData
from custom_components.elkm1.switch import (
    ElkArmRequestSwitch,
    ElkOutput,
    ElkThermostatEMHeat,
    async_setup_entry,
)


def _output_switch(index: int, output_obj) -> ElkOutput:
    switch = object.__new__(ElkOutput)
    switch._index = index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(outputs=[output_obj])

    async def _queue(sender, _description):
        sender()
        return True

    coordinator.async_queue_command = AsyncMock(side_effect=_queue)
    switch.coordinator = coordinator
    return switch


async def test_output_turn_on_sends_indefinite_duration():
    output = MagicMock()
    switch = _output_switch(0, output)

    await switch.async_turn_on()

    output.turn_on.assert_called_once_with(0)


async def test_output_turn_off_sends_turn_off():
    output = MagicMock()
    switch = _output_switch(0, output)

    await switch.async_turn_off()

    output.turn_off.assert_called_once()


async def test_output_turn_on_for_converts_timedelta_to_seconds():
    output = MagicMock()
    switch = _output_switch(0, output)

    await switch.async_switch_output_turn_on_for(timedelta(minutes=2))

    output.turn_on.assert_called_once_with(120)


def _arm_request_switch() -> ElkArmRequestSwitch:
    switch = object.__new__(ElkArmRequestSwitch)
    switch._prefix = ""
    switch._mac = "aa:bb:cc:dd:ee:ff"
    switch._attr_is_on = False
    switch.async_write_ha_state = MagicMock()
    coordinator = MagicMock()
    switch.coordinator = coordinator
    switch._config_entry = MagicMock()
    return switch


def test_arm_request_switch_init_sets_unique_id_and_defaults_off():
    coordinator = MagicMock()
    config_entry = MagicMock()
    config_entry.data = {"prefix": "elkm1"}
    config_entry.unique_id = "aa:bb:cc:dd:ee:ff"
    config_entry.entry_id = "entry1"
    switch = ElkArmRequestSwitch(coordinator, config_entry)
    assert switch._attr_unique_id == "elkm1_elkm1_arm_request"
    assert switch.is_on is False


async def test_arm_request_switch_turn_on_sets_state_and_writes():
    switch = _arm_request_switch()

    await switch.async_turn_on()

    assert switch.is_on is True
    switch.async_write_ha_state.assert_called_once()


async def test_arm_request_switch_turn_off_sets_state_and_writes():
    switch = _arm_request_switch()
    switch._attr_is_on = True

    await switch.async_turn_off()

    assert switch.is_on is False
    switch.async_write_ha_state.assert_called_once()


def test_output_switch_init_disables_by_default_past_64():
    coordinator = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    switch = ElkOutput(coordinator, config_entry, 64)
    assert switch._attr_entity_registry_enabled_default is False


def test_output_switch_init_enabled_by_default_under_64():
    coordinator = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    switch = ElkOutput(coordinator, config_entry, 0)
    assert switch._attr_unique_id == "entry1_output_1"
    assert not hasattr(switch, "_attr_entity_registry_enabled_default") or (
        switch._attr_entity_registry_enabled_default is not False
    )


def test_output_switch_name_falls_back_without_obj():
    switch = _output_switch(3, MagicMock())
    switch.coordinator.data = ElkPanelData(outputs=[])
    assert switch.name == "Output 4"


def test_output_switch_name_uses_panel_reported_name():
    output = MagicMock()
    output.name = "Driveway Light"
    switch = _output_switch(0, output)
    assert switch.name == "Driveway Light"


def test_output_switch_is_on_false_without_obj():
    switch = _output_switch(2, MagicMock())
    switch.coordinator.data = ElkPanelData(outputs=[])
    assert switch.is_on is False


def test_output_switch_is_on_reflects_output_state():
    output = MagicMock()
    output.output_on = True
    switch = _output_switch(0, output)
    assert switch.is_on is True


def _emheat_switch(index: int, tstat_obj) -> ElkThermostatEMHeat:
    switch = object.__new__(ElkThermostatEMHeat)
    switch._index = index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(thermostats=[tstat_obj])

    async def _confirm(sender, *_args, **_kwargs):
        sender()
        return True

    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm)
    switch.coordinator = coordinator
    return switch


def test_emheat_switch_init_sets_unique_id():
    coordinator = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    switch = ElkThermostatEMHeat(coordinator, config_entry, 0)
    assert switch._index == 0
    assert switch._attr_unique_id == "entry1_thermostat_1_emheat"


def test_emheat_switch_name_falls_back_without_obj():
    switch = _emheat_switch(0, MagicMock())
    switch.coordinator.data = ElkPanelData(thermostats=[])
    assert switch.name == "Thermostat 1 Emergency Heat"


def test_emheat_switch_name_suffixes_panel_reported_name():
    tstat = MagicMock()
    tstat.name = "Upstairs"
    switch = _emheat_switch(0, tstat)
    assert switch.name == "Upstairs Emergency Heat"


def test_emheat_switch_is_on_false_without_obj():
    switch = _emheat_switch(0, MagicMock())
    switch.coordinator.data = ElkPanelData(thermostats=[])
    assert switch.is_on is False


def test_emheat_switch_is_on_true_when_mode_matches():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.EMERGENCY_HEAT
    switch = _emheat_switch(0, tstat)
    assert switch.is_on is True


def test_emheat_switch_is_on_false_when_mode_differs():
    tstat = MagicMock()
    tstat.mode = ThermostatMode.AUTO
    switch = _emheat_switch(0, tstat)
    assert switch.is_on is False


async def test_emheat_switch_turn_on_sets_emergency_heat_mode():
    tstat = MagicMock()
    switch = _emheat_switch(0, tstat)

    await switch.async_turn_on()

    tstat.set.assert_called_once()
    args = tstat.set.call_args[0]
    assert args[1] == ThermostatMode.EMERGENCY_HEAT


async def test_emheat_switch_turn_off_reverts_to_auto_mode():
    tstat = MagicMock()
    switch = _emheat_switch(0, tstat)

    await switch.async_turn_off()

    tstat.set.assert_called_once()
    args = tstat.set.call_args[0]
    assert args[1] == ThermostatMode.AUTO


async def test_emheat_switch_turn_on_is_a_noop_without_obj():
    switch = _emheat_switch(0, MagicMock())
    switch.coordinator.data = ElkPanelData(thermostats=[])

    await switch.async_turn_on()

    switch.coordinator.async_confirm_command.assert_not_called()


async def test_emheat_switch_turn_on_for_is_not_supported():
    switch = _emheat_switch(0, MagicMock())

    with pytest.raises(HomeAssistantError):
        await switch.async_switch_output_turn_on_for(timedelta(minutes=1))


def test_emheat_switch_get_enum_value_default_for_non_numeric():
    switch = object.__new__(ElkThermostatEMHeat)
    assert switch._get_enum_value("not-a-number", default=9) == 9


def test_arm_request_switch_device_info_includes_panel_version():
    switch = object.__new__(ElkArmRequestSwitch)
    switch._config_entry = MagicMock()
    switch._config_entry.entry_id = "entry1"
    switch.coordinator = MagicMock()
    switch.coordinator.data.panel_version = "5.20"

    info = switch.device_info

    assert info["sw_version"] == "5.20"


async def test_setup_entry_creates_arm_switch_and_dynamic_output_thermostat_entities(
    hass, mock_serial_entry
):
    from custom_components.elkm1.helpers.elk.outputs import Output
    from custom_components.elkm1.helpers.elk.thermostats import Thermostat

    conn = MagicMock()
    notifier = MagicMock()

    output = Output(0, conn, notifier)
    output._configured = True
    output.name = "Driveway"

    configured_output_past_64 = Output(64, conn, notifier)
    configured_output_past_64._configured = True
    configured_output_past_64.name = "Unused Output"

    unconfigured_output_past_64 = Output(65, conn, notifier)

    tstat = Thermostat(0, conn, notifier)
    tstat._configured = True
    tstat.name = "Upstairs"

    coordinator = MagicMock()
    coordinator.data = ElkPanelData(
        outputs=[output, configured_output_past_64, unconfigured_output_past_64],
        thermostats=[tstat],
    )
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)

    mock_serial_entry.add_to_hass(hass)
    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []

    def _async_add_entities(new_entities):
        added.extend(new_entities)

    await async_setup_entry(hass, mock_serial_entry, _async_add_entities)

    assert any(isinstance(e, ElkArmRequestSwitch) for e in added)
    assert any(isinstance(e, ElkOutput) and e._index == 0 for e in added)
    assert any(
        isinstance(e, ElkOutput) and e._index == 64 and not e._attr_entity_registry_enabled_default
        for e in added
    )
    assert not any(isinstance(e, ElkOutput) and e._index == 65 for e in added)
    assert any(isinstance(e, ElkThermostatEMHeat) and e._index == 0 for e in added)


async def test_unconfigured_outputs_past_64_get_no_entity(hass, mock_serial_entry):
    """Outputs 65-208 are almost never physically present; unlike the old
    unconditional-registration behavior, an unconfigured one must not create
    a switch entity at all, the same rule every other output/zone/thermostat
    already follows."""
    from custom_components.elkm1.helpers.elk.outputs import Output

    conn = MagicMock()
    notifier = MagicMock()
    unconfigured_output = Output(64, conn, notifier)
    assert unconfigured_output.configured is False

    coordinator = MagicMock()
    coordinator.data = ElkPanelData(outputs=[unconfigured_output])
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)

    mock_serial_entry.add_to_hass(hass)
    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []

    def _async_add_entities(new_entities):
        added.extend(new_entities)

    await async_setup_entry(hass, mock_serial_entry, _async_add_entities)

    assert not any(isinstance(e, ElkOutput) and e._index == 64 for e in added)
