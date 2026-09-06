"""Tests for time.py: the time-of-day custom-value filter in
async_setup_entry, and the ElkTimeOfDay entity's value conversion.
"""

from __future__ import annotations

from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock

from custom_components.elkm1.helpers.elk.const import SettingFormat
from custom_components.elkm1.models import ElkPanelData, ElkRuntimeData
from custom_components.elkm1.time import ElkTimeOfDay, _enum_value, async_setup_entry


def test_enum_value_reads_value_attribute():
    assert _enum_value(SettingFormat.TIME_OF_DAY) == 2


def test_enum_value_accepts_raw_int():
    assert _enum_value(2) == 2


def test_enum_value_returns_default_for_unrecognized_type():
    assert _enum_value(object(), default=7) == 7


def _setting(index: int, value_format, default_name: bool = False) -> MagicMock:
    setting = MagicMock()
    setting.index = index
    setting.configured = True
    setting.is_default_name.return_value = default_name
    setting.value_format = value_format
    return setting


async def test_setup_entry_skips_default_named_settings(hass, mock_serial_entry):
    time_setting = _setting(0, SettingFormat.TIME_OF_DAY, default_name=True)
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[time_setting])
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


async def test_setup_entry_skips_non_time_of_day_settings(hass, mock_serial_entry):
    number_setting = _setting(0, SettingFormat.NUMBER)
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[number_setting])
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


async def test_setup_entry_creates_entity_for_time_of_day_setting(hass, mock_serial_entry):
    time_setting = _setting(0, SettingFormat.TIME_OF_DAY)
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[time_setting])
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
    assert isinstance(added[0], ElkTimeOfDay)


def _time_of_day(index: int, setting_obj) -> ElkTimeOfDay:
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(settings=[setting_obj])

    config_entry = MagicMock()
    config_entry.entry_id = "entry1"

    entity = ElkTimeOfDay(coordinator, config_entry, index)

    async def _confirm(sender, *_args, **_kwargs):
        sender()
        return True

    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm)
    return entity


def test_init_sets_unique_id():
    entity = _time_of_day(0, MagicMock())

    assert entity._attr_unique_id == "entry1_custom_value_1_time"


def test_get_obj_returns_none_when_index_out_of_range():
    entity = _time_of_day(0, MagicMock())
    entity._index = 5

    assert entity._get_obj() is None


def test_name_uses_panel_name_when_available():
    setting = MagicMock()
    setting.name = "Sunrise"
    entity = _time_of_day(0, setting)

    assert entity.name == "Sunrise"


def test_name_falls_back_when_obj_missing():
    entity = _time_of_day(0, MagicMock())
    entity._index = 9

    assert entity.name == "Custom Value 10"


def test_native_value_none_when_obj_missing():
    entity = _time_of_day(0, MagicMock())
    entity._index = 9

    assert entity.native_value is None


def test_native_value_none_when_value_not_a_tuple():
    setting = MagicMock()
    setting.value = None
    entity = _time_of_day(0, setting)

    assert entity.native_value is None


def test_native_value_converts_hour_minute_tuple():
    setting = MagicMock()
    setting.value = (6, 30)
    entity = _time_of_day(0, setting)

    assert entity.native_value == dt_time(hour=6, minute=30)


async def test_async_set_value_sends_cr_command():
    setting = MagicMock()
    entity = _time_of_day(0, setting)

    await entity.async_set_value(dt_time(hour=14, minute=5))

    setting.set.assert_called_once_with((14, 5))


async def test_async_set_value_is_a_noop_when_obj_missing():
    entity = _time_of_day(0, MagicMock())
    entity._index = 9

    await entity.async_set_value(dt_time(hour=1, minute=0))

    entity.coordinator.async_confirm_command.assert_not_called()
