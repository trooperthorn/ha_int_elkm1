"""Alarm control panel platform for Elk-M1."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.alarm_control_panel import AlarmControlPanelEntity
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ELK_USER_CODE_SERVICE_SCHEMA
from .coordinator import ElkDataUpdateCoordinator
from .entity import ElkEntity
from .models import AreaData, ElkRuntimeData

SERVICE_ALARM_BYPASS = "alarm_bypass"
SERVICE_ALARM_CLEAR_BYPASS = "alarm_clear_bypass"
SERVICE_ALARM_ARM_HOME_INSTANT = "alarm_arm_home_instant"
SERVICE_ALARM_ARM_NIGHT_INSTANT = "alarm_arm_night_instant"

# Map modern enum states
STATE_ALARM_TRIGGERED = AlarmControlPanelState.TRIGGERED
STATE_ARMED_AWAY = AlarmControlPanelState.ARMED_AWAY
STATE_ARMED_HOME = AlarmControlPanelState.ARMED_HOME
STATE_ARMED_NIGHT = AlarmControlPanelState.ARMED_NIGHT
STATE_DISARMED = AlarmControlPanelState.DISARMED

_LOGGER: logging.Logger = logging.getLogger(__name__)

# The panel has a single serialized command buffer with no flow control -
# concurrent writes from multiple entities must not overlap.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up alarm control panel platform for all configured areas."""
    runtime_data: ElkRuntimeData = config_entry.runtime_data
    coordinator = runtime_data.coordinator

    # The coordinator now dictates how many areas exist based on connection parsing
    num_areas = coordinator.data.num_areas if coordinator.data else 1

    entities = [
        ElkAlarmControlPanel(
            coordinator=coordinator,
            config_entry=config_entry,
            area_index=i,
        )
        for i in range(num_areas)
    ]

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ALARM_BYPASS, ELK_USER_CODE_SERVICE_SCHEMA, "async_alarm_bypass"
    )
    platform.async_register_entity_service(
        SERVICE_ALARM_CLEAR_BYPASS,
        ELK_USER_CODE_SERVICE_SCHEMA,
        "async_alarm_clear_bypass",
    )
    platform.async_register_entity_service(
        SERVICE_ALARM_ARM_HOME_INSTANT,
        ELK_USER_CODE_SERVICE_SCHEMA,
        "async_alarm_arm_home_instant",
    )
    platform.async_register_entity_service(
        SERVICE_ALARM_ARM_NIGHT_INSTANT,
        ELK_USER_CODE_SERVICE_SCHEMA,
        "async_alarm_arm_night_instant",
    )


class ElkAlarmControlPanel(ElkEntity, AlarmControlPanelEntity):
    """Elk-M1 alarm control panel partition."""

    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_NIGHT
        | AlarmControlPanelEntityFeature.ARM_VACATION
        | AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS
        | AlarmControlPanelEntityFeature.TRIGGER
    )
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = True

    def __init__(
        self,
        coordinator: ElkDataUpdateCoordinator,
        config_entry: ConfigEntry,
        area_index: int = 0,
    ) -> None:
        """Initialize alarm panel partition."""
        area_num = area_index + 1
        super().__init__(coordinator, config_entry, f"alarm_panel_area_{area_num}")
        self._area_index = area_index
        self._attr_name = f"Area {area_num}"
        self._attr_unique_id = f"{config_entry.entry_id}_area_{area_num}"

    @property
    def area_data(self) -> AreaData:
        """Helper to get the specific area data from the coordinator."""
        if self.coordinator.data:
            return self.coordinator.data.areas.get(self._area_index, AreaData())
        return AreaData()

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return state strictly mapped to HA AlarmControlPanelState."""
        if not self.coordinator.data:
            return None

        data = self.area_data
        alarm_state_val = data.alarm_state
        armed_status_val = data.armed_status
        arm_up_state_val = data.arm_up_state

        # 1. TRIGGERED: Elk AlarmState >= 2
        if alarm_state_val >= 2:
            return STATE_ALARM_TRIGGERED

        # 2. PENDING (Entry Delay): Elk AlarmState == 1 OR Timer1 running while armed
        if alarm_state_val == 1 or (data.timer1 > 0 and armed_status_val != 0):
            return AlarmControlPanelState.PENDING

        # 3. ARMING (Exit Delay): Timer2 running or exit state indicated
        if data.timer2 > 0 or arm_up_state_val in (3, 5):
            return AlarmControlPanelState.ARMING

        # 4. ARMED_CUSTOM_BYPASS: Armed with Bypass active
        if arm_up_state_val == 6 and armed_status_val != 0:
            return AlarmControlPanelState.ARMED_CUSTOM_BYPASS

        # 5. Stable Arming Modes
        if armed_status_val == 1:
            return STATE_ARMED_AWAY
        if armed_status_val in (2, 3):
            return STATE_ARMED_HOME
        if armed_status_val in (4, 5):
            return STATE_ARMED_NIGHT
        if armed_status_val == 6:
            return AlarmControlPanelState.ARMED_VACATION

        return STATE_DISARMED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes with detailed panel information."""
        if not self.coordinator.data:
            return {}

        global_data = self.coordinator.data
        area_data = self.area_data

        return {
            "armed": global_data.armed,
            "armed_mode": global_data.armed_mode,
            "entry_delay_active": area_data.entry_delay_active,
            "exit_delay_active": area_data.exit_delay_active,
            "entry_delay_seconds": area_data.entry_delay,
            "exit_delay_seconds": area_data.exit_delay,
            "last_user": global_data.last_user,
            "last_user_name": global_data.last_user_name,
            "last_keypad": global_data.last_keypad,
            "zones_faulted": global_data.zones_faulted,
            "zones_faulted_count": len(global_data.zones_faulted),
            "faulted_zone_names": global_data.faulted_zone_names,
            "outputs_active": global_data.outputs_active,
            "outputs_active_count": len(global_data.outputs_active),
            "active_output_names": global_data.active_output_names,
            "trouble_status": global_data.trouble_status,
            "ac_power": global_data.ac_power,
            "battery_status": global_data.battery_status,
            "panel_temperature": global_data.panel_temperature,
            "connection_status": "Connected" if self.coordinator.last_update_success else "Disconnected",
            "last_update": self.coordinator.last_update_success,
            "alarm_triggered": area_data.alarm_state >= 2,
            "fire_alarm": global_data.fire_alarm_active,
            "panic_alarm": area_data.panic_state,
            "alarm_memory": area_data.alarm_memory,
            "bypassed_zones": global_data.bypassed_zones,
            "bypassed_zones_count": len(global_data.bypassed_zones),
        }

    def _get_code_val(self, code: str | None) -> int:
        """Safely convert HA string PIN to Elk required integer."""
        if not code:
            return 0
        try:
            return int(code)
        except ValueError:
            _LOGGER.warning("Invalid PIN code format. Expected numeric digits.")
            return 0

    async def _async_run_command(self, coro: Any, action_desc: str) -> None:
        """Await a coordinator command, raising HomeAssistantError on failure.

        Without this, a failed command would only be logged - HA's service
        call/automation trace would show success even though the panel
        never got (or rejected) the command.
        """
        try:
            await coro
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(
                f"Error {action_desc} area {self._area_index + 1}: {err}"
            ) from err

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command to the area via the coordinator."""
        await self._async_run_command(
            self.coordinator.async_alarm_disarm(self._area_index, self._get_code_val(code)),
            "disarming",
        )

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm stay command to the area via the coordinator."""
        await self._async_run_command(
            self.coordinator.async_alarm_arm_home(self._area_index, self._get_code_val(code)),
            "arming home",
        )

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command to the area via the coordinator."""
        await self._async_run_command(
            self.coordinator.async_alarm_arm_away(self._area_index, self._get_code_val(code)),
            "arming away",
        )

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Send arm night command to the area via the coordinator."""
        await self._async_run_command(
            self.coordinator.async_alarm_arm_night(self._area_index, self._get_code_val(code)),
            "arming night",
        )

    async def async_alarm_arm_vacation(self, code: str | None = None) -> None:
        """Send arm vacation command to the area via the coordinator."""
        await self._async_run_command(
            self.coordinator.async_alarm_arm_vacation(self._area_index, self._get_code_val(code)),
            "arming vacation",
        )

    async def async_alarm_arm_custom_bypass(self, code: str | None = None) -> None:
        """Handle custom bypass request via the coordinator."""
        await self._async_run_command(
            self.coordinator.async_alarm_arm_custom_bypass(
                self._area_index, self._get_code_val(code)
            ),
            "arming custom bypass",
        )

    async def async_alarm_trigger(self, code: str | None = None) -> None:
        """Trigger the alarm on the area via the coordinator."""
        await self._async_run_command(
            self.coordinator.async_alarm_trigger(self._area_index, self._get_code_val(code)),
            "triggering alarm",
        )

    async def async_alarm_arm_home_instant(self, code: str | None = None) -> None:
        """Arm stay-instant (no entry delay) via the elkm1.alarm_arm_home_instant service."""
        await self._async_run_command(
            self.coordinator.async_alarm_arm_home_instant(
                self._area_index, self._get_code_val(code)
            ),
            "arming home instant",
        )

    async def async_alarm_arm_night_instant(self, code: str | None = None) -> None:
        """Arm night-instant (no entry delay) via the elkm1.alarm_arm_night_instant service."""
        await self._async_run_command(
            self.coordinator.async_alarm_arm_night_instant(
                self._area_index, self._get_code_val(code)
            ),
            "arming night instant",
        )

    async def async_alarm_bypass(self, code: str | None = None) -> None:
        """Toggle bypass of all zones in the area via the elkm1.alarm_bypass service."""
        await self._async_run_command(
            self.coordinator.bypass_area(self._area_index, code), "bypassing"
        )

    async def async_alarm_clear_bypass(self, code: str | None = None) -> None:
        """Toggle bypass of all zones in the area via the elkm1.alarm_clear_bypass service.

        The Elk protocol's all-zone bypass command is a toggle with no
        separate "clear" variant, so this sends the same command as
        `async_alarm_bypass` - resending it clears an active area bypass.
        """
        await self._async_run_command(
            self.coordinator.bypass_area(self._area_index, code), "clearing bypass on"
        )
