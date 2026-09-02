"""Support for Elk-M1 PLC (X10-style) lighting."""

from __future__ import annotations

import logging
from typing import Any, override

from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ElkDataUpdateCoordinator
from .entity import ElkEntity, async_add_dynamic_entities
from .models import ElkRuntimeData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# In PC/PS, 0=off, 1=full on, and 2-99 are dim percentages.
_ELK_MAX_LEVEL = 100
_HA_MAX_BRIGHTNESS = 255


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the Elk-M1 PLC light platform."""
    runtime_data: ElkRuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator

    # elkm1_lib always allocates the hardware-maximum number of Light
    # objects regardless of how many the panel actually has, and only
    # marks one `.configured` once its panel-assigned name has synced - a
    # sequential, one-index-at-a-time exchange that can still be in
    # progress after this function returns, so lights are added as they
    # individually become configured rather than only in this one pass.
    lights = coordinator.data.lights if coordinator.data else []
    async_add_dynamic_entities(
        config_entry,
        coordinator,
        async_add_entities,
        lights,
        lambda light: ElkPlcLight(coordinator, config_entry, light.index),
    )


class ElkPlcLight(ElkEntity, LightEntity):
    """Representation of an Elk-M1 PLC lighting device."""

    _attr_color_mode = ColorMode.BRIGHTNESS

    def __init__(
        self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry, index: int
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator, config_entry, f"light_{index + 1}")
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_light_{index + 1}"
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def _get_obj(self) -> Any:
        if self.coordinator.data and self._index < len(self.coordinator.data.lights):
            return self.coordinator.data.lights[self._index]
        return None

    @property
    @override
    def name(self) -> str | None:
        """Return the panel-configured name, which may arrive after entity creation."""
        obj = self._get_obj()
        return obj.name if obj else f"Light {self._index + 1}"

    @property
    @override
    def is_on(self) -> bool:
        obj = self._get_obj()
        return bool(obj and obj.status > 0)

    @property
    @override
    def brightness(self) -> int | None:
        obj = self._get_obj()
        if not obj:
            return None
        status = int(obj.status)
        if status <= 0:
            return 0
        if status == 1:
            return _HA_MAX_BRIGHTNESS
        return round(min(status, 99) * _HA_MAX_BRIGHTNESS / _ELK_MAX_LEVEL)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on (optionally to a specific brightness)."""
        obj = self._get_obj()
        if not obj:
            return
        if (brightness := kwargs.get("brightness")) is not None:
            level = round(brightness * _ELK_MAX_LEVEL / _HA_MAX_BRIGHTNESS)
            await self.coordinator.async_queue_command(
                lambda: obj.level(max(level, 2)), "lighting level change"
            )
        else:
            await self.coordinator.async_queue_command(
                lambda: obj.level(_ELK_MAX_LEVEL), "lighting on"
            )

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        if obj := self._get_obj():
            await self.coordinator.async_queue_command(lambda: obj.level(0), "lighting off")
