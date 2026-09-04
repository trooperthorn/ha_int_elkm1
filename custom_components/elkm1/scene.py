"""Support for Elk-M1 tasks as scenes (tasks are momentary and have no state)."""

from __future__ import annotations

import logging
from typing import Any, override

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ElkDataUpdateCoordinator
from .entity import ElkEntity, async_add_dynamic_entities
from .models import ElkRuntimeData

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the Elk-M1 scene (task) platform."""
    runtime_data: ElkRuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator

    tasks = coordinator.data.tasks if coordinator.data else []
    async_add_dynamic_entities(
        config_entry,
        coordinator,
        async_add_entities,
        tasks,
        lambda task: ElkTask(coordinator, config_entry, task.index),
    )


class ElkTask(ElkEntity, Scene):
    """Representation of an Elk-M1 task."""

    def __init__(
        self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry, index: int
    ) -> None:
        """Initialize the task."""
        super().__init__(coordinator, config_entry, f"task_{index + 1}")
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_task_{index + 1}"

    def _get_obj(self) -> Any:
        if self.coordinator.data and self._index < len(self.coordinator.data.tasks):
            return self.coordinator.data.tasks[self._index]
        return None

    @property
    @override
    def name(self) -> str | None:
        """Return the panel-configured name, which may arrive after entity creation."""
        obj = self._get_obj()
        return obj.name if obj else f"Task {self._index + 1}"

    @override
    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the task."""
        if obj := self._get_obj():
            await self.coordinator.async_queue_command(
                obj.activate, f"task {self._index + 1} activation"
            )
