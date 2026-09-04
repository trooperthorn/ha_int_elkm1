"""Base entity for Elk-M1 integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import ElkDataUpdateCoordinator


def create_elk_system_device_info(
    config_entry: ConfigEntry, sw_version: str | None = None
) -> DeviceInfo:
    """Create standard device info for Elk-M1 system components."""
    return DeviceInfo(
        identifiers={(DOMAIN, config_entry.entry_id)},
        name="Elk-M1",
        manufacturer=MANUFACTURER,
        model=MODEL,
        sw_version=sw_version,
    )


class ElkEntity(CoordinatorEntity[ElkDataUpdateCoordinator], Entity):
    """Base entity for Elk-M1."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: ElkDataUpdateCoordinator,
        config_entry: ConfigEntry,
        entity_key: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_key = entity_key
        self._config_entry = config_entry

        self._attr_device_info = create_elk_system_device_info(
            config_entry, sw_version=getattr(coordinator.data, "panel_version", None)
        )

        self._attr_unique_id = f"{config_entry.entry_id}_{entity_key}"


def async_add_dynamic_entities(
    config_entry: ConfigEntry,
    coordinator: ElkDataUpdateCoordinator,
    async_add_entities: AddEntitiesCallback,
    elements: Iterable[Any],
    entity_factory: Callable[[Any], Entity | None],
) -> None:
    """Create entities for already-configured elements, then keep adding
    entities for elements that become configured later.

    `entity_factory` returns `None` to skip an element entirely (e.g. a
    zone type handled by a different platform); the returned entity's
    `element.index` is used to avoid ever adding the same element twice.
    """
    added_indices: set[int] = set()

    def _scan_for_new_entities() -> None:
        new_entities: list[Entity] = []
        for element in elements:
            if element.index in added_indices or not element.configured:
                continue
            entity = entity_factory(element)
            added_indices.add(element.index)
            if entity is not None:
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    _scan_for_new_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_scan_for_new_entities))
