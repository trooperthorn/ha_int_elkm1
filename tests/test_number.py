"""Tests for number.py: the ElkCounter entity's set/refresh entity services,
and that ElkCustomValue correctly rejects them (those services only make
sense for counters).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.elkm1.helpers.elk.const import SettingFormat
from custom_components.elkm1.models import ElkPanelData, ElkRuntimeData
from custom_components.elkm1.number import (
    ElkCounter,
    ElkCustomValue,
    _enum_value,
    async_setup_entry,
)


def _counter(index: int, counter_obj) -> ElkCounter:
    entity = object.__new__(ElkCounter)
    entity._index = index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(counters=[counter_obj])

    async def _confirm(sender, *_args, **_kwargs):
        sender()
        return True

    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm)
    entity.coordinator = coordinator
    return entity


async def test_counter_refresh_calls_get():
    counter = MagicMock()
    entity = _counter(0, counter)

    await entity.async_counter_refresh()

    counter.get.assert_called_once()


async def test_counter_set_calls_set_with_value():
    counter = MagicMock()
    entity = _counter(0, counter)

    await entity.async_counter_set(42)

    counter.set.assert_called_once_with(42)


async def test_native_value_reads_from_counter_object():
    counter = MagicMock()
    counter.value = 7
    entity = _counter(0, counter)

    assert entity.native_value == 7


async def test_native_value_returns_none_when_counter_value_is_none():
    """Regression test: helpers.elk.Counter.value is None until a CV message
    arrives, and native_value is read as soon as the entity is added to its
    platform - before any such message could have arrived. Crashed with
    TypeError before this was guarded; see docs/decisions.md 2026-09-05.
    """
    counter = MagicMock()
    counter.value = None
    entity = _counter(0, counter)

    assert entity.native_value is None


def _custom_value(index: int, setting_obj) -> ElkCustomValue:
    entity = object.__new__(ElkCustomValue)
    entity._index = index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[setting_obj])
    entity.coordinator = coordinator
    return entity


async def test_custom_value_native_value_returns_none_when_value_is_none():
    """Regression test: helpers.elk.Setting.value is None until a CR message
    arrives, same crash as the counter case above.
    """
    setting = MagicMock()
    setting.value = None
    entity = _custom_value(0, setting)

    assert entity.native_value is None


async def test_custom_value_native_value_reads_from_setting_object():
    setting = MagicMock()
    setting.value = 42
    entity = _custom_value(0, setting)

    assert entity.native_value == 42


async def test_custom_value_rejects_counter_refresh_service():
    entity = object.__new__(ElkCustomValue)

    with pytest.raises(HomeAssistantError):
        await entity.async_counter_refresh()


async def test_custom_value_rejects_counter_set_service():
    entity = object.__new__(ElkCustomValue)

    with pytest.raises(HomeAssistantError):
        await entity.async_counter_set(5)


def test_enum_value_reads_value_attribute():
    assert _enum_value(SettingFormat.TIMER) == 1


def test_enum_value_accepts_raw_int():
    assert _enum_value(3) == 3


def test_enum_value_returns_default_for_unrecognized_type():
    assert _enum_value(object(), default=9) == 9


def _real_counter(index: int, counter_obj) -> ElkCounter:
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(counters=[counter_obj])
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"

    entity = ElkCounter(coordinator, config_entry, index)

    async def _confirm(sender, *_args, **_kwargs):
        sender()
        return True

    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm)
    return entity


def test_counter_init_sets_unique_id():
    entity = _real_counter(0, MagicMock())

    assert entity._attr_unique_id == "entry1_counter_1"


def test_counter_get_obj_returns_none_when_index_out_of_range():
    entity = _real_counter(0, MagicMock())
    entity._index = 5

    assert entity._get_obj() is None


def test_counter_name_uses_panel_name_when_available():
    counter = MagicMock()
    counter.name = "Alarm Count"
    entity = _real_counter(0, counter)

    assert entity.name == "Alarm Count"


def test_counter_name_falls_back_when_obj_missing():
    entity = _real_counter(0, MagicMock())
    entity._index = 9

    assert entity.name == "Counter 10"


async def test_counter_async_set_native_value_sends_cv_command():
    counter = MagicMock()
    entity = _real_counter(0, counter)

    await entity.async_set_native_value(42)

    counter.set.assert_called_once_with(42)


async def test_counter_async_set_native_value_is_a_noop_when_obj_missing():
    entity = _real_counter(0, MagicMock())
    entity._index = 9

    await entity.async_set_native_value(42)

    entity.coordinator.async_confirm_command.assert_not_called()


def _real_custom_value(index: int, setting_obj) -> ElkCustomValue:
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[setting_obj])
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"

    entity = ElkCustomValue(coordinator, config_entry, index)

    async def _confirm(sender, *_args, **_kwargs):
        sender()
        return True

    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm)
    return entity


def test_custom_value_init_sets_unique_id():
    entity = _real_custom_value(0, MagicMock())

    assert entity._attr_unique_id == "entry1_custom_value_1"


def test_custom_value_get_obj_returns_none_when_index_out_of_range():
    entity = _real_custom_value(0, MagicMock())
    entity._index = 5

    assert entity._get_obj() is None


def test_custom_value_name_uses_panel_name_when_available():
    setting = MagicMock()
    setting.name = "Thermostat Offset"
    entity = _real_custom_value(0, setting)

    assert entity.name == "Thermostat Offset"


def test_custom_value_name_falls_back_when_obj_missing():
    entity = _real_custom_value(0, MagicMock())
    entity._index = 9

    assert entity.name == "Custom Value 10"


def test_custom_value_native_value_returns_none_for_tuple_value():
    """Time-of-day settings store a (hour, minute) tuple; that format is
    handled by time.py, not number.py, so it must read as unavailable here.
    """
    setting = MagicMock()
    setting.value = (6, 30)
    entity = _real_custom_value(0, setting)

    assert entity.native_value is None


async def test_custom_value_async_set_native_value_sends_cr_command():
    setting = MagicMock()
    entity = _real_custom_value(0, setting)

    await entity.async_set_native_value(15)

    setting.set.assert_called_once_with(15)


async def test_custom_value_async_set_native_value_is_a_noop_when_obj_missing():
    entity = _real_custom_value(0, MagicMock())
    entity._index = 9

    await entity.async_set_native_value(15)

    entity.coordinator.async_confirm_command.assert_not_called()


def _element(index: int, default_name: bool = False, value_format=None) -> MagicMock:
    element = MagicMock()
    element.index = index
    element.configured = True
    element.is_default_name.return_value = default_name
    if value_format is not None:
        element.value_format = value_format
    return element


async def test_setup_entry_skips_default_named_counters(hass, mock_serial_entry):
    counter = _element(0, default_name=True)
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(counters=[counter])
    coordinator.async_add_listener.return_value = lambda: None

    mock_serial_entry.add_to_hass(hass)
    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []
    await async_setup_entry(hass, mock_serial_entry, lambda ents: added.extend(ents))

    assert added == []


async def test_setup_entry_creates_entity_for_named_counter(hass, mock_serial_entry):
    counter = _element(0)
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(counters=[counter])
    coordinator.async_add_listener.return_value = lambda: None

    mock_serial_entry.add_to_hass(hass)
    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []
    await async_setup_entry(hass, mock_serial_entry, lambda ents: added.extend(ents))

    assert len(added) == 1
    assert isinstance(added[0], ElkCounter)


async def test_setup_entry_skips_default_named_settings(hass, mock_serial_entry):
    setting = _element(0, default_name=True, value_format=SettingFormat.NUMBER)
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[setting])
    coordinator.async_add_listener.return_value = lambda: None

    mock_serial_entry.add_to_hass(hass)
    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []
    await async_setup_entry(hass, mock_serial_entry, lambda ents: added.extend(ents))

    assert added == []


async def test_setup_entry_skips_settings_with_non_numeric_format(hass, mock_serial_entry):
    setting = _element(0, value_format=SettingFormat.TIME_OF_DAY)
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[setting])
    coordinator.async_add_listener.return_value = lambda: None

    mock_serial_entry.add_to_hass(hass)
    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []
    await async_setup_entry(hass, mock_serial_entry, lambda ents: added.extend(ents))

    assert added == []


async def test_setup_entry_creates_entity_for_number_format_setting(hass, mock_serial_entry):
    setting = _element(0, value_format=SettingFormat.NUMBER)
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[setting])
    coordinator.async_add_listener.return_value = lambda: None

    mock_serial_entry.add_to_hass(hass)
    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []
    await async_setup_entry(hass, mock_serial_entry, lambda ents: added.extend(ents))

    assert len(added) == 1
    assert isinstance(added[0], ElkCustomValue)


async def test_setup_entry_creates_entity_for_timer_format_setting(hass, mock_serial_entry):
    setting = _element(0, value_format=SettingFormat.TIMER)
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[setting])
    coordinator.async_add_listener.return_value = lambda: None

    mock_serial_entry.add_to_hass(hass)
    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []
    await async_setup_entry(hass, mock_serial_entry, lambda ents: added.extend(ents))

    assert len(added) == 1
    assert isinstance(added[0], ElkCustomValue)
