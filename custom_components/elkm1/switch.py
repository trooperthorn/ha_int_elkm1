"""Support for control of ElkM1 outputs (relays) and proxy switches."""

from __future__ import annotations

import logging
from datetime import timedelta
from math import ceil
from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ElkDataUpdateCoordinator
from .entity import ElkEntity, async_add_dynamic_entities, create_elk_system_device_info
from .helpers.elk.const import ThermostatMode, ThermostatSetting
from .models import ElkRuntimeData

_LOGGER = logging.getLogger(__name__)

# The panel has one serialized command buffer with no flow control; writes must not overlap.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the Elk-M1 switch platform."""
    runtime_data: ElkRuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator

    entities: list[SwitchEntity] = []

    entities.append(ElkArmRequestSwitch(coordinator, config_entry))

    async_add_entities(entities)

    outputs = coordinator.data.outputs if coordinator.data else []
    async_add_dynamic_entities(
        config_entry,
        coordinator,
        async_add_entities,
        outputs,
        lambda output: ElkOutput(coordinator, config_entry, output.index),
    )

    thermostats = coordinator.data.thermostats if coordinator.data else []
    async_add_dynamic_entities(
        config_entry,
        coordinator,
        async_add_entities,
        thermostats,
        lambda tstat: ElkThermostatEMHeat(coordinator, config_entry, tstat.index),
    )


class ElkArmRequestSwitch(ElkEntity, SwitchEntity):
    """Native proxy switch for triggering pre-arm validation automations."""

    _attr_should_poll = False
    _attr_translation_key = "arm_system_request"

    def __init__(self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the arm request proxy switch."""
        super().__init__(coordinator, config_entry, "arm_request")
        self._prefix = config_entry.data.get("prefix", "")
        self._mac = config_entry.unique_id

        self._attr_unique_id = f"elkm1_{self._prefix}_arm_request".lower()
        self._attr_is_on = False

    @property
    @override
    def device_info(self) -> DeviceInfo:
        """Device info connecting via the ElkM1 system."""
        return create_elk_system_device_info(
            self._config_entry, sw_version=self.coordinator.data.panel_version
        )

    @property
    @override
    def is_on(self) -> bool:
        """Return the state of the switch."""
        return bool(self._attr_is_on)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (Triggers the HA Pre-Arm Blueprint)."""
        self._attr_is_on = True
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (Reset by the Blueprint or manually)."""
        self._attr_is_on = False
        self.async_write_ha_state()


class ElkOutput(ElkEntity, SwitchEntity):
    """Elk output as switch."""

    def __init__(
        self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry, index: int
    ) -> None:
        """Initialize the Elk physical output."""
        super().__init__(coordinator, config_entry, f"output_{index + 1}")
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_output_{index + 1}"
        if index >= 64:
            self._attr_entity_registry_enabled_default = False

    @property
    @override
    def name(self) -> str | None:
        """Return the panel-configured name, which may arrive after entity creation."""
        obj = self._get_obj()
        return obj.name if obj else f"Output {self._index + 1}"

    def _get_obj(self) -> Any:
        if self.coordinator.data and self._index < len(self.coordinator.data.outputs):
            return self.coordinator.data.outputs[self._index]
        return None

    @property
    @override
    def is_on(self) -> bool:
        """Get the current output status."""
        obj = self._get_obj()
        return bool(obj and obj.output_on)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the output indefinitely."""
        if obj := self._get_obj():
            await self.coordinator.async_queue_command(
                lambda: obj.turn_on(0), f"output {self._index + 1} on"
            )

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the output."""
        if obj := self._get_obj():
            await self.coordinator.async_queue_command(
                obj.turn_off, f"output {self._index + 1} off"
            )

    async def async_switch_output_turn_on_for(self, duration: timedelta) -> None:
        """Turn on an output for specified length of time."""
        if obj := self._get_obj():
            await self.coordinator.async_queue_command(
                lambda: obj.turn_on(ceil(duration.total_seconds())),
                f"output {self._index + 1} timed on",
            )


class ElkThermostatEMHeat(ElkEntity, SwitchEntity):
    """Elk Thermostat emergency heat as switch.

    Not translation_key-named: `Entity.translation_placeholders` is a `@final`
    `cached_property` (computed once, then frozen for the entity's lifetime),
    but the panel-reported thermostat name this entity's display name embeds
    can arrive after entity creation. A live `name` override is the only way
    to keep that name current. See docs/decisions.md.
    """

    def __init__(
        self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry, index: int
    ) -> None:
        """Initialize the emergency heat switch."""
        super().__init__(coordinator, config_entry, f"thermostat_{index + 1}_emheat")
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_thermostat_{index + 1}_emheat"

    def _get_obj(self) -> Any:
        if self.coordinator.data and self._index < len(self.coordinator.data.thermostats):
            return self.coordinator.data.thermostats[self._index]
        return None

    @property
    @override
    def name(self) -> str | None:
        """Return the panel-configured name (may arrive after entity creation), suffixed."""
        obj = self._get_obj()
        base_name = obj.name if obj else f"Thermostat {self._index + 1}"
        return f"{base_name} Emergency Heat"

    @property
    @override
    def is_on(self) -> bool:
        """Get the current emergency heat status."""
        obj = self._get_obj()
        if not obj:
            return False
        mode = self._get_enum_value(getattr(obj, "mode", 0))
        return mode == ThermostatMode.EMERGENCY_HEAT.value

    def _get_enum_value(self, obj: Any, default: int = 0) -> int:
        if hasattr(obj, "value"):
            return int(obj.value)
        return int(obj) if isinstance(obj, (int, float)) else default

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on Emergency Heat."""
        if obj := self._get_obj():
            await self.coordinator.async_confirm_command(
                lambda: obj.set(ThermostatSetting.MODE, ThermostatMode.EMERGENCY_HEAT),
                "TR",
                f"thermostat {self._index + 1} emergency heat on",
                lambda payload: payload.get("thermostat_index") == self._index,
            )

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off Emergency Heat by reverting to Auto."""
        if obj := self._get_obj():
            await self.coordinator.async_confirm_command(
                lambda: obj.set(ThermostatSetting.MODE, ThermostatMode.AUTO),
                "TR",
                f"thermostat {self._index + 1} emergency heat off",
                lambda payload: payload.get("thermostat_index") == self._index,
            )

    async def async_switch_output_turn_on_for(self, duration: timedelta) -> None:
        """Not supported for thermostat."""
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="output_switch_only"
        )
