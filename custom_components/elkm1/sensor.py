"""Support for control of ElkM1 sensors."""

from __future__ import annotations

import logging
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ElkDataUpdateCoordinator
from .entity import ElkEntity, async_add_dynamic_entities
from .helpers.troublestatus import format_troubles
from .models import ElkRuntimeData

_LOGGER = logging.getLogger(__name__)

# The panel has one serialized command buffer with no flow control; writes must not overlap.
PARALLEL_UPDATES = 1


UNDEFINED_TEMPERATURE = -40

# Zone definitions 33 = temperature, 34 = analog.
_DEVICE_CLASS_MAP: dict[int, SensorDeviceClass] = {
    33: SensorDeviceClass.TEMPERATURE,
    34: SensorDeviceClass.VOLTAGE,
}

_STATE_CLASS_MAP: dict[int, SensorStateClass] = {
    33: SensorStateClass.MEASUREMENT,
    34: SensorStateClass.MEASUREMENT,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the Elk-M1 sensor platform."""
    runtime_data: ElkRuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator

    entities: list[SensorEntity] = []

    entities.append(ElkPanel(coordinator, config_entry))

    entities.append(ElkActiveZonesSensor(coordinator, config_entry))

    async_add_entities(entities)

    # Only definitions 33 (temperature) and 34 (analog) become sensors.
    def _zone_entity(zone: Any) -> SensorEntity | None:
        def_val = 0
        if hasattr(zone, "definition"):
            def_obj = zone.definition
            def_val = int(def_obj.value) if hasattr(def_obj, "value") else int(def_obj)

        if def_val in (33, 34):
            return ElkZone(coordinator, config_entry, zone.index)
        return None

    zones = coordinator.data.zones if coordinator.data else []
    async_add_dynamic_entities(config_entry, coordinator, async_add_entities, zones, _zone_entity)


class ElkSensor(ElkEntity, SensorEntity):
    """Base representation of Elk-M1 sensor."""

    def _get_enum_value(self, obj: Any, default: int = 0) -> int:
        """Safely extract integer value from enum or string objects."""
        if hasattr(obj, "value"):
            return int(obj.value)
        if isinstance(obj, str):
            return int(obj) if obj.isdigit() else default
        return int(obj) if isinstance(obj, (int, float)) else default


class ElkActiveZonesSensor(ElkSensor):
    """Sensor that provides a live count and readable list of open zones."""

    _attr_native_unit_of_measurement = "Zones"
    _attr_translation_key = "active_zones"

    def __init__(self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the active zones sensor."""
        super().__init__(coordinator, config_entry, "active_zones_summary")
        self._attr_unique_id = f"{config_entry.entry_id}_active_zones_summary"

    @property
    def native_value(self) -> int:
        """Return the live count of faulted zones from the coordinator."""
        if not self.coordinator.data:
            return 0
        return len(self.coordinator.data.zones_faulted)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes including a readable list of open zones."""
        if not self.coordinator.data:
            return {"open_entities": "None"}

        open_zones = self.coordinator.data.faulted_zone_names
        return {"open_entities": ", ".join(open_zones) if open_zones else "None"}


class ElkPanel(ElkSensor):
    """Representation of an Elk-M1 Panel."""

    _attr_translation_key = "panel"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the panel sensor."""
        super().__init__(coordinator, config_entry, "panel_status")
        self._attr_unique_id = f"{config_entry.entry_id}_panel_status"

    @property
    def native_value(self) -> str:
        """Return the connection state."""
        return "Connected" if self.coordinator.connected else "Disconnected"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributes of the sensor."""
        if not self.coordinator.data:
            return {}

        raw_status = self.coordinator.data.raw_trouble_status
        return {
            "system_trouble_status_raw": raw_status,
            "system_trouble_status_parsed": format_troubles(raw_status),
        }


class ElkZone(ElkSensor):
    """Representation of an Elk-M1 Zone (Analog or Temperature)."""

    def __init__(
        self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry, index: int
    ) -> None:
        super().__init__(coordinator, config_entry, f"sensor_zone_{index + 1}")
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_sensor_zone_{index + 1}"
        self._temperature_unit = "°F"

    @property
    @override
    def name(self) -> str | None:
        """Return the panel-configured name, which may arrive after entity creation."""
        obj = self._get_obj()
        return obj.name if obj else f"Zone {self._index + 1}"

    def _get_obj(self) -> Any:
        if self.coordinator.data and self._index < len(self.coordinator.data.zones):
            return self.coordinator.data.zones[self._index]
        return None

    @property
    def icon(self) -> str:
        obj = self._get_obj()
        def_val = self._get_enum_value(getattr(obj, "definition", 0)) if obj else 0
        return "mdi:thermometer-lines" if def_val == 33 else "mdi:speedometer"

    @property
    def device_class(self) -> SensorDeviceClass | None:
        obj = self._get_obj()
        def_val = self._get_enum_value(getattr(obj, "definition", 0)) if obj else 0
        return _DEVICE_CLASS_MAP.get(def_val)

    @property
    def state_class(self) -> SensorStateClass | None:
        obj = self._get_obj()
        def_val = self._get_enum_value(getattr(obj, "definition", 0)) if obj else 0
        return _STATE_CLASS_MAP.get(def_val)

    @property
    def native_unit_of_measurement(self) -> str | None:
        obj = self._get_obj()
        def_val = self._get_enum_value(getattr(obj, "definition", 0)) if obj else 0
        if def_val == 33:
            return self._temperature_unit
        if def_val == 34:
            return UnitOfElectricPotential.VOLT
        return None

    @property
    def native_value(self) -> str | None:
        obj = self._get_obj()
        if not obj:
            return None

        def_val = self._get_enum_value(getattr(obj, "definition", 0))
        if def_val == 33:
            temp = getattr(obj, "temperature", UNDEFINED_TEMPERATURE)
            return str(temp) if temp > UNDEFINED_TEMPERATURE else None
        if def_val == 34:
            return str(getattr(obj, "voltage", 0.0))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        obj = self._get_obj()
        if not obj:
            return {}
        logical_status = self._get_enum_value(getattr(obj, "logical_status", 0))
        return {
            "physical_status": self._get_enum_value(getattr(obj, "physical_status", 0)),
            "logical_status": logical_status,
            "definition": self._get_enum_value(getattr(obj, "definition", 0)),
            # ZoneLogicalStatus.BYPASSED == 3 (there's no separate attribute).
            "bypassed": logical_status == 3,
        }

    async def async_zone_bypass(self, code: str | None = None) -> None:
        """Bypass zone via the coordinator."""
        await self.coordinator.bypass_zone(self._index + 1, code)

    async def async_zone_trigger(self) -> None:
        """Trigger a zone, explicitly treated as protocol-unconfirmed."""
        await self.coordinator.trigger_zone(self._index + 1)
