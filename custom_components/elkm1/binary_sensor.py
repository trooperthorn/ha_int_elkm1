"""Support for control of ElkM1 binary sensors."""

from __future__ import annotations

import logging
from typing import Any, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ElkDataUpdateCoordinator
from .entity import ElkEntity, async_add_dynamic_entities
from .helpers.troublestatus import TROUBLE_INDEX_NAMES
from .models import ElkRuntimeData

_LOGGER = logging.getLogger(__name__)

# ZoneType encodes arming response, not sensor type; classes are installer convention. See docs/protocol.md.
_DEVICE_CLASS_MAP: dict[int, BinarySensorDeviceClass] = {
    1: BinarySensorDeviceClass.DOOR,
    2: BinarySensorDeviceClass.DOOR,
    3: BinarySensorDeviceClass.OPENING,
    4: BinarySensorDeviceClass.MOTION,
    5: BinarySensorDeviceClass.MOTION,
    6: BinarySensorDeviceClass.MOTION,
    7: BinarySensorDeviceClass.MOTION,
    10: BinarySensorDeviceClass.SMOKE,
    11: BinarySensorDeviceClass.SMOKE,
    17: BinarySensorDeviceClass.CO,
    19: BinarySensorDeviceClass.COLD,
    20: BinarySensorDeviceClass.GAS,
    21: BinarySensorDeviceClass.HEAT,
    25: BinarySensorDeviceClass.MOISTURE,
}

# Entry/exit and perimeter-instant zones count as door/window openings for the per-area sensor.
_OPENING_DEFINITIONS = {1, 2, 3}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the Elk-M1 binary sensor platform."""
    runtime_data: ElkRuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator

    def _zone_entity(zone: Any) -> BinarySensorEntity | None:
        def_val = 0
        if hasattr(zone, "definition"):
            def_obj = zone.definition
            def_val = int(def_obj.value) if hasattr(def_obj, "value") else int(def_obj)

        # Definitions 33 (temperature) and 34 (analog) are sensor.py entities, not binary sensors.
        if def_val in (33, 34):
            return None

        return ElkBinarySensor(
            coordinator=coordinator,
            config_entry=config_entry,
            zone_index=zone.index,
        )

    zones = coordinator.data.zones if coordinator.data else []
    async_add_dynamic_entities(config_entry, coordinator, async_add_entities, zones, _zone_entity)

    entities: list[BinarySensorEntity] = []
    entities.extend(
        ElkTroubleBinarySensor(coordinator, config_entry, name)
        for _index, (name, _label) in TROUBLE_INDEX_NAMES.items()
    )

    # One aggregate opening sensor per area; see docs/cross_integration.md.
    num_areas = coordinator.data.num_areas if coordinator.data else 1
    entities.extend(
        ElkAreaOpeningsBinarySensor(coordinator, config_entry, area_index)
        for area_index in range(num_areas)
    )

    async_add_entities(entities)


class ElkBinarySensor(ElkEntity, BinarySensorEntity):
    """Representation of ElkM1 binary sensor."""

    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: ElkDataUpdateCoordinator,
        config_entry: ConfigEntry,
        zone_index: int,
    ) -> None:
        """Initialize the binary sensor."""
        zone_num = zone_index + 1
        super().__init__(coordinator, config_entry, f"binary_sensor_zone_{zone_num}")
        self._zone_index = zone_index
        self._attr_unique_id = f"{config_entry.entry_id}_zone_{zone_num}"

    @property
    @override
    def name(self) -> str | None:
        """Return the panel-configured name, which may arrive after entity creation."""
        zone_obj = self.zone_data
        return zone_obj.name if zone_obj else f"Zone {self._zone_index + 1}"

    @property
    def zone_data(self) -> Any:
        """Helper to get the specific zone object from the coordinator data."""
        if self.coordinator.data and self._zone_index < len(self.coordinator.data.zones):
            return self.coordinator.data.zones[self._zone_index]
        return None

    def _get_enum_value(self, obj: Any, default: int = 0) -> int:
        """Safely extract the raw integer value from helpers.elk Enum objects or raw dicts."""
        if hasattr(obj, "value"):
            return int(obj.value)
        if isinstance(obj, str):
            return int(obj) if obj.isdigit() else default
        return int(obj) if isinstance(obj, (int, float)) else default

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on (violated)."""
        zone = self.zone_data
        if not zone:
            return False

        logical_status = self._get_enum_value(getattr(zone, "logical_status", 0))
        # ZoneLogicalStatus: 0=normal, 1=trouble, 2=violated, 3=bypassed.
        return logical_status == 2

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return the device class of this sensor based on its Elk definition."""
        zone = self.zone_data
        if not zone:
            return None

        def_val = self._get_enum_value(getattr(zone, "definition", 0))
        return _DEVICE_CLASS_MAP.get(def_val)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes for the zone."""
        zone = self.zone_data
        if not zone:
            return {}

        logical_status = self._get_enum_value(getattr(zone, "logical_status", 0))
        return {
            "physical_status": self._get_enum_value(getattr(zone, "physical_status", 0)),
            "logical_status": logical_status,
            "definition": self._get_enum_value(getattr(zone, "definition", 0)),
            # BYPASSED (3) is its own logical status; Zone has no separate bypassed flag.
            "bypassed": logical_status == 3,
            "triggered_alarm": getattr(zone, "triggered_alarm", False),
            "voltage": getattr(zone, "voltage", 0.0),
        }


class ElkTroubleBinarySensor(ElkEntity, BinarySensorEntity):
    """Representation of a single Elk-M1 system trouble condition."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: ElkDataUpdateCoordinator,
        config_entry: ConfigEntry,
        trouble_name: str,
    ) -> None:
        """Initialize the trouble sensor."""
        super().__init__(coordinator, config_entry, f"trouble_{trouble_name}")
        self._trouble_name = trouble_name
        self._attr_unique_id = f"{config_entry.entry_id}_trouble_{trouble_name}"
        self._attr_translation_key = f"trouble_{trouble_name}"

    @property
    def is_on(self) -> bool:
        """Return true if this trouble condition is currently active."""
        if not self.coordinator.data:
            return False
        return self.coordinator.data.troubles.get(self._trouble_name, False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the zone/device number carried by detailed SS fields."""
        if not self.coordinator.data:
            return {}
        detail = self.coordinator.data.trouble_details.get(self._trouble_name)
        return {"zone_or_device_number": detail} if detail is not None else {}


class ElkAreaOpeningsBinarySensor(ElkEntity, BinarySensorEntity):
    """Aggregate 'any door/window open' sensor for one area."""

    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_translation_key = "area_openings"

    def __init__(
        self,
        coordinator: ElkDataUpdateCoordinator,
        config_entry: ConfigEntry,
        area_index: int,
    ) -> None:
        """Initialize the area openings sensor."""
        area_num = area_index + 1
        super().__init__(coordinator, config_entry, f"area_{area_num}_openings")
        self._area_index = area_index
        self._attr_unique_id = f"{config_entry.entry_id}_area_{area_num}_openings"
        self._attr_translation_placeholders = {"area_num": str(area_num)}

    def _get_enum_value(self, obj: Any, default: int = 0) -> int:
        if hasattr(obj, "value"):
            return int(obj.value)
        if isinstance(obj, str):
            return int(obj) if obj.isdigit() else default
        return int(obj) if isinstance(obj, (int, float)) else default

    def _area_opening_zones(self) -> list[Any]:
        """Return configured door/window zones assigned to this area."""
        if not self.coordinator.data:
            return []
        return [
            zone
            for zone in self.coordinator.data.zones
            if zone.configured
            and self._get_enum_value(getattr(zone, "area", -1)) == self._area_index
            and self._get_enum_value(getattr(zone, "definition", 0)) in _OPENING_DEFINITIONS
        ]

    @property
    @override
    def is_on(self) -> bool:
        """Return True if any door/window zone in this area is open."""
        return any(
            self._get_enum_value(getattr(zone, "logical_status", 0)) == 2
            for zone in self._area_opening_zones()
        )

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """List which zones are currently open, for automation/debugging use."""
        open_zones = [
            zone.name
            for zone in self._area_opening_zones()
            if self._get_enum_value(getattr(zone, "logical_status", 0)) == 2
        ]
        return {
            "open_zones": open_zones,
            "open_zones_count": len(open_zones),
        }
