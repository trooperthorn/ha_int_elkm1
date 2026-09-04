"""Support for Elk-M1 thermostats."""

from __future__ import annotations

import logging
from typing import Any, override

from elkm1_lib.const import ThermostatFan, ThermostatMode, ThermostatSetting
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ElkDataUpdateCoordinator
from .entity import ElkEntity, async_add_dynamic_entities
from .models import ElkRuntimeData

_LOGGER = logging.getLogger(__name__)

# The panel has one serialized command buffer with no flow control; writes must not overlap.
PARALLEL_UPDATES = 1

FAN_AUTO = "auto"
FAN_ON = "on"

_HVAC_MODE_TO_ELK = {
    HVACMode.OFF: ThermostatMode.OFF,
    HVACMode.HEAT: ThermostatMode.HEAT,
    HVACMode.COOL: ThermostatMode.COOL,
    # Elk AUTO switches between heat and cool setpoints, which is HA HEAT_COOL, not HA AUTO.
    HVACMode.HEAT_COOL: ThermostatMode.AUTO,
}
_ELK_MODE_TO_HVAC = {v: k for k, v in _HVAC_MODE_TO_ELK.items()}
_ELK_MODE_TO_HVAC[ThermostatMode.EMERGENCY_HEAT] = HVACMode.HEAT

_FAN_TO_ELK = {FAN_AUTO: ThermostatFan.AUTO, FAN_ON: ThermostatFan.ON}
_ELK_FAN_TO_HA = {v: k for k, v in _FAN_TO_ELK.items()}

# The protocol manual documents no panel-enforced setpoint limits; these are generic defaults.
MIN_TEMP = 40
MAX_TEMP = 95


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the Elk-M1 climate platform."""
    runtime_data: ElkRuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator

    thermostats = coordinator.data.thermostats if coordinator.data else []
    async_add_dynamic_entities(
        config_entry,
        coordinator,
        async_add_entities,
        thermostats,
        lambda tstat: ElkThermostat(coordinator, config_entry, tstat.index),
    )


class ElkThermostat(ElkEntity, ClimateEntity):
    """Representation of an Elk-M1 thermostat."""

    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self, coordinator: ElkDataUpdateCoordinator, config_entry: ConfigEntry, index: int
    ) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator, config_entry, f"thermostat_{index + 1}")
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_thermostat_{index + 1}"
        self._attr_hvac_modes = list(_HVAC_MODE_TO_ELK)
        self._attr_fan_modes = list(_FAN_TO_ELK)

    def _get_obj(self) -> Any:
        if self.coordinator.data and self._index < len(self.coordinator.data.thermostats):
            return self.coordinator.data.thermostats[self._index]
        return None

    @property
    @override
    def name(self) -> str | None:
        """Return the panel-configured name, which may arrive after entity creation."""
        obj = self._get_obj()
        return obj.name if obj else f"Thermostat {self._index + 1}"

    @staticmethod
    def _enum_value(obj: Any, default: int = 0) -> int:
        if hasattr(obj, "value"):
            return int(obj.value)
        return int(obj) if isinstance(obj, (int, float)) else default

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        obj = self._get_obj()
        if not obj or obj.mode is None:
            return None
        return _ELK_MODE_TO_HVAC.get(ThermostatMode(self._enum_value(obj.mode)), HVACMode.OFF)

    @property
    @override
    def fan_mode(self) -> str | None:
        obj = self._get_obj()
        if not obj or obj.fan is None:
            return None
        return _ELK_FAN_TO_HA.get(ThermostatFan(self._enum_value(obj.fan)))

    @property
    @override
    def current_temperature(self) -> float | None:
        obj = self._get_obj()
        return float(obj.current_temp) if obj else None

    @property
    @override
    def target_temperature(self) -> float | None:
        obj = self._get_obj()
        if not obj or self.hvac_mode not in (HVACMode.HEAT, HVACMode.COOL):
            return None
        value = obj.heat_setpoint if self.hvac_mode == HVACMode.HEAT else obj.cool_setpoint
        return float(value)

    @property
    @override
    def target_temperature_high(self) -> float | None:
        obj = self._get_obj()
        if not obj or self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return float(obj.cool_setpoint)

    @property
    @override
    def target_temperature_low(self) -> float | None:
        obj = self._get_obj()
        if not obj or self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return float(obj.heat_setpoint)

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if obj := self._get_obj():
            await self.coordinator.async_confirm_command(
                lambda: obj.set(ThermostatSetting.MODE, _HVAC_MODE_TO_ELK[hvac_mode]),
                "TR",
                f"thermostat {self._index + 1} mode change",
                lambda payload: payload.get("thermostat_index") == self._index,
            )

    @override
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode."""
        if obj := self._get_obj():
            await self.coordinator.async_confirm_command(
                lambda: obj.set(ThermostatSetting.FAN, _FAN_TO_ELK[fan_mode]),
                "TR",
                f"thermostat {self._index + 1} fan change",
                lambda payload: payload.get("thermostat_index") == self._index,
            )

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature(s)."""
        obj = self._get_obj()
        if not obj:
            return
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            setting = (
                ThermostatSetting.HEAT_SETPOINT
                if self.hvac_mode == HVACMode.HEAT
                else ThermostatSetting.COOL_SETPOINT
            )
            await self.coordinator.async_confirm_command(
                lambda: obj.set(setting, int(temp)),
                "TR",
                f"thermostat {self._index + 1} setpoint change",
                lambda payload: payload.get("thermostat_index") == self._index,
            )
            return
        if (low := kwargs.get("target_temp_low")) is not None:
            await self.coordinator.async_confirm_command(
                lambda: obj.set(ThermostatSetting.HEAT_SETPOINT, int(low)),
                "TR",
                f"thermostat {self._index + 1} heat setpoint change",
                lambda payload: payload.get("thermostat_index") == self._index,
            )
        if (high := kwargs.get("target_temp_high")) is not None:
            await self.coordinator.async_confirm_command(
                lambda: obj.set(ThermostatSetting.COOL_SETPOINT, int(high)),
                "TR",
                f"thermostat {self._index + 1} cool setpoint change",
                lambda payload: payload.get("thermostat_index") == self._index,
            )
