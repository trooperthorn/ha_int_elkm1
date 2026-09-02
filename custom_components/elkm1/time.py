"""Support for Elk-M1 time-of-day custom values."""

from __future__ import annotations

import logging
from datetime import time as dt_time
from typing import Any, override

from elkm1_lib.const import SettingFormat
from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ElkDataUpdateCoordinator
from .entity import ElkEntity, async_add_dynamic_entities
from .models import ElkRuntimeData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


def _enum_value(obj: Any, default: int = 0) -> int:
    if hasattr(obj, "value"):
        return int(obj.value)
    return int(obj) if isinstance(obj, (int, float)) else default


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the Elk-M1 time platform (time-of-day custom values only)."""
    runtime_data: ElkRuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator

    # elkm1_lib only marks a custom value `.configured` once its
    # panel-assigned name has synced - a sequential, one-index-at-a-time
    # exchange that can still be in progress after this function returns,
    # so entities are added as each custom value individually becomes
    # configured (and named) rather than only in this one pass.
    def _time_of_day_entity(setting: Any) -> TimeEntity | None:
        if (
            setting.is_default_name()
            or _enum_value(setting.value_format) != SettingFormat.TIME_OF_DAY.value
        ):
            return None
        return ElkTimeOfDay(coordinator, config_entry, setting.index)

    settings = coordinator.data.settings if coordinator.data else []
    async_add_dynamic_entities(
        config_entry, coordinator, async_add_entities, settings, _time_of_day_entity
    )


class ElkTimeOfDay(ElkEntity, TimeEntity):
    """Representation of a time-of-day Elk-M1 custom value."""

    def __init__(
        self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry, index: int
    ) -> None:
        """Initialize the time-of-day value."""
        super().__init__(coordinator, config_entry, f"custom_value_{index + 1}")
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_custom_value_{index + 1}_time"

    def _get_obj(self) -> Any:
        if self.coordinator.data and self._index < len(self.coordinator.data.settings):
            return self.coordinator.data.settings[self._index]
        return None

    @property
    @override
    def name(self) -> str | None:
        """Return the panel-configured name, which may arrive after entity creation."""
        obj = self._get_obj()
        return obj.name if obj else f"Custom Value {self._index + 1}"

    @property
    @override
    def native_value(self) -> dt_time | None:
        obj = self._get_obj()
        if not obj or not isinstance(obj.value, tuple):
            return None
        hour, minute = obj.value
        return dt_time(hour=hour, minute=minute)

    @override
    async def async_set_value(self, value: dt_time) -> None:
        """Set the time-of-day value."""
        if obj := self._get_obj():
            expected = (value.hour, value.minute)
            await self.coordinator.async_confirm_command(
                lambda: obj.set(expected),
                "CR",
                f"custom time {self._index + 1} update",
                lambda payload: any(
                    item.get("index") == self._index and item.get("value") == expected
                    for item in payload.get("values", [])
                ),
            )
