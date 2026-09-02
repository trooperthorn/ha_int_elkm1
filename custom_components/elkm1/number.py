"""Support for Elk-M1 counters and numeric custom values."""

from __future__ import annotations

import logging
from typing import Any, override

import voluptuous as vol
from elkm1_lib.const import SettingFormat
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ElkDataUpdateCoordinator
from .entity import ElkEntity, async_add_dynamic_entities
from .models import ElkRuntimeData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

SERVICE_SENSOR_COUNTER_REFRESH = "sensor_counter_refresh"
SERVICE_SENSOR_COUNTER_SET = "sensor_counter_set"

COUNTER_SET_SERVICE_SCHEMA = {
    vol.Required("value"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
}


def _enum_value(obj: Any, default: int = 0) -> int:
    if hasattr(obj, "value"):
        return int(obj.value)
    return int(obj) if isinstance(obj, (int, float)) else default


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the Elk-M1 number platform.

    Only counters/custom values the panel has actually given a real name to
    (via the `sd` text-description command) are created automatically -
    elkm1_lib always allocates the hardware maximum (64 counters, 20
    custom values) regardless of how many are actually in use, and most
    installations only use a handful. Unnamed slots are left for a future
    options-flow opt-in rather than flooding every install with mostly-
    unused entities.
    """
    runtime_data: ElkRuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator

    # elkm1_lib always allocates the hardware maximum (64 counters, 20
    # custom values) regardless of how many are actually in use, and only
    # marks one `.configured` once its panel-assigned name has synced - a
    # sequential, one-index-at-a-time exchange that can still be in
    # progress after this function returns, so each is added as it
    # individually becomes configured (and named) rather than only in
    # this one pass.
    def _counter_entity(counter: Any) -> NumberEntity | None:
        if counter.is_default_name():
            return None
        return ElkCounter(coordinator, config_entry, counter.index)

    def _custom_value_entity(setting: Any) -> NumberEntity | None:
        if setting.is_default_name() or _enum_value(setting.value_format) not in (
            SettingFormat.NUMBER.value,
            SettingFormat.TIMER.value,
        ):
            return None
        return ElkCustomValue(coordinator, config_entry, setting.index)

    counters = coordinator.data.counters if coordinator.data else []
    async_add_dynamic_entities(
        config_entry, coordinator, async_add_entities, counters, _counter_entity
    )
    settings = coordinator.data.settings if coordinator.data else []
    async_add_dynamic_entities(
        config_entry, coordinator, async_add_entities, settings, _custom_value_entity
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SENSOR_COUNTER_REFRESH, None, "async_counter_refresh"
    )
    platform.async_register_entity_service(
        SERVICE_SENSOR_COUNTER_SET,
        vol.Schema(COUNTER_SET_SERVICE_SCHEMA),
        "async_counter_set",
    )


class ElkCounter(ElkEntity, NumberEntity):
    """Representation of an Elk-M1 RAM counter."""

    _attr_native_min_value = 0
    _attr_native_max_value = 65535
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:counter"

    def __init__(
        self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry, index: int
    ) -> None:
        """Initialize the counter."""
        super().__init__(coordinator, config_entry, f"counter_{index + 1}")
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_counter_{index + 1}"

    def _get_obj(self) -> Any:
        if self.coordinator.data and self._index < len(self.coordinator.data.counters):
            return self.coordinator.data.counters[self._index]
        return None

    @property
    @override
    def name(self) -> str | None:
        """Return the panel-configured name, which may arrive after entity creation."""
        obj = self._get_obj()
        return obj.name if obj else f"Counter {self._index + 1}"

    @property
    @override
    def native_value(self) -> float | None:
        obj = self._get_obj()
        return float(obj.value) if obj else None

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the counter value."""
        if obj := self._get_obj():
            expected = int(value)
            await self.coordinator.async_confirm_command(
                lambda: obj.set(expected),
                "CV",
                f"counter {self._index + 1} update",
                lambda payload: (
                    payload.get("counter") == self._index and payload.get("value") == expected
                ),
            )

    async def async_counter_refresh(self) -> None:
        """Request the panel resend this counter's current value."""
        if obj := self._get_obj():
            await self.coordinator.async_confirm_command(
                obj.get,
                "CV",
                f"counter {self._index + 1} refresh",
                lambda payload: payload.get("counter") == self._index,
            )

    async def async_counter_set(self, value: int) -> None:
        """Set the counter value via the elkm1.sensor_counter_set service."""
        if obj := self._get_obj():
            await self.coordinator.async_confirm_command(
                lambda: obj.set(value),
                "CV",
                f"counter {self._index + 1} update",
                lambda payload: (
                    payload.get("counter") == self._index and payload.get("value") == value
                ),
            )


class ElkCustomValue(ElkEntity, NumberEntity):
    """Representation of a numeric (Number or Timer format) Elk-M1 custom value."""

    _attr_native_min_value = 0
    _attr_native_max_value = 65535
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry, index: int
    ) -> None:
        """Initialize the custom value."""
        super().__init__(coordinator, config_entry, f"custom_value_{index + 1}")
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_custom_value_{index + 1}"

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
    def native_value(self) -> float | None:
        obj = self._get_obj()
        if not obj or isinstance(obj.value, tuple):
            return None
        return float(obj.value)

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the custom value."""
        if obj := self._get_obj():
            expected = int(value)
            await self.coordinator.async_confirm_command(
                lambda: obj.set(expected),
                "CR",
                f"custom value {self._index + 1} update",
                lambda payload: any(
                    item.get("index") == self._index and item.get("value") == expected
                    for item in payload.get("values", [])
                ),
            )

    async def async_counter_refresh(self) -> None:
        """Not supported for custom values."""
        raise HomeAssistantError("supported only on ElkM1 counter entities")

    async def async_counter_set(self, value: int) -> None:
        """Not supported for custom values."""
        raise HomeAssistantError("supported only on ElkM1 counter entities")
