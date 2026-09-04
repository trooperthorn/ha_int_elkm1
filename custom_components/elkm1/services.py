"""Support the ElkM1 Gold and ElkM1 EZ8 alarm/integration panels."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, service
from homeassistant.util import dt as dt_util

from .const import (
    COUNTER_SET_SERVICE_SCHEMA,
    DOMAIN,
    ELK_OUTPUT_TURN_ON_FOR_SERVICE_SCHEMA,
    ELK_USER_CODE_SERVICE_SCHEMA,
    SERVICE_ALARM_ARM_HOME_INSTANT,
    SERVICE_ALARM_ARM_NIGHT_INSTANT,
    SERVICE_ALARM_BYPASS,
    SERVICE_ALARM_CLEAR_BYPASS,
    SERVICE_SENSOR_COUNTER_REFRESH,
    SERVICE_SENSOR_COUNTER_SET,
    SERVICE_SENSOR_ZONE_BYPASS,
    SERVICE_SENSOR_ZONE_TRIGGER,
    SERVICE_SWITCH_OUTPUT_TURN_ON_FOR,
)
from .coordinator import ElkDataUpdateCoordinator
from .models import ElkRuntimeData

SPEAK_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("number"): vol.All(vol.Coerce(int), vol.Range(min=0, max=999)),
        vol.Optional("prefix", default=""): cv.string,
    }
)

SET_TIME_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("prefix", default=""): cv.string,
    }
)

DISPLAY_MESSAGE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("prefix", default=""): cv.string,
        vol.Optional("area", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
        vol.Optional("line1", default=""): vol.All(cv.string, vol.Length(max=16)),
        vol.Optional("line2", default=""): vol.All(cv.string, vol.Length(max=16)),
        vol.Optional("beep", default=False): cv.boolean,
        vol.Optional("clear", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=2)),
        vol.Optional("timeout", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
    }
)

SECURITY_SUMMARY_SCHEMA = vol.Schema(
    {
        vol.Optional("prefix", default=""): cv.string,
    }
)


def _find_coordinator_by_prefix(
    hass: HomeAssistant, prefix: str
) -> ElkDataUpdateCoordinator | None:
    """Search all config entries for a given prefix's coordinator."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if not entry.runtime_data:
            continue
        elk_data: ElkRuntimeData = entry.runtime_data
        if elk_data.prefix == prefix:
            return elk_data.coordinator
    return None


def _get_coordinator(service: ServiceCall) -> ElkDataUpdateCoordinator:
    """Get the coordinator from a service call."""
    prefix = service.data.get("prefix", "")
    coordinator = _find_coordinator_by_prefix(service.hass, prefix)
    if coordinator is None:
        raise HomeAssistantError(f"No ElkM1 coordinator with prefix '{prefix}' found")
    return coordinator


async def _async_speak_word_service(service: ServiceCall) -> None:
    """Speak a word via elkm1_lib's own Panel.speak_word() helper."""
    coordinator = _get_coordinator(service)
    number = service.data["number"]
    await coordinator.speak_word(number)


async def _async_speak_phrase_service(service: ServiceCall) -> None:
    """Speak a phrase via elkm1_lib's own Panel.speak_phrase() helper."""
    coordinator = _get_coordinator(service)
    number = service.data["number"]
    await coordinator.speak_phrase(number)


async def _async_set_time_service(service: ServiceCall) -> None:
    """Write the panel's real-time clock via elkm1_lib's own Panel.set_time() helper."""
    coordinator = _get_coordinator(service)
    await coordinator.set_panel_time(dt_util.now())


async def _async_display_message_service(service: ServiceCall) -> None:
    """Display a message on an area's keypads via elkm1_lib's own Area.display_message()."""
    coordinator = _get_coordinator(service)
    await coordinator.display_message(
        area_index=service.data["area"] - 1,
        line1=service.data["line1"],
        line2=service.data["line2"],
        beep=service.data["beep"],
        clear=service.data["clear"],
        timeout=service.data["timeout"],
    )


async def _async_get_security_summary(service: ServiceCall) -> ServiceResponse:
    """Return live security data to an automation or script."""
    coordinator = _get_coordinator(service)

    faulted_indices = coordinator.data.zones_faulted if coordinator.data else []

    # Zones are 1-indexed to the user, 0-indexed in the list.
    faulted_zones = [idx + 1 for idx in faulted_indices]

    areas = coordinator.data.areas.values() if coordinator.data else []
    # AS arm-up state is authoritative: 1 = ready, 2 = can be force armed.
    ready_to_arm = bool(coordinator.data) and all(area.arm_up_state in (1, 2) for area in areas)

    return {
        "total_faulted": len(faulted_zones),
        "is_ready_to_arm": ready_to_arm,
        "faulted_zone_numbers": faulted_zones,  # type: ignore[dict-item]
    }


ENTITY_SERVICES: tuple[tuple[str, str, dict[Any, Any] | None, str], ...] = (
    (
        "alarm_control_panel",
        SERVICE_ALARM_BYPASS,
        ELK_USER_CODE_SERVICE_SCHEMA,
        "async_alarm_bypass",
    ),
    (
        "alarm_control_panel",
        SERVICE_ALARM_CLEAR_BYPASS,
        ELK_USER_CODE_SERVICE_SCHEMA,
        "async_alarm_clear_bypass",
    ),
    (
        "alarm_control_panel",
        SERVICE_ALARM_ARM_HOME_INSTANT,
        ELK_USER_CODE_SERVICE_SCHEMA,
        "async_alarm_arm_home_instant",
    ),
    (
        "alarm_control_panel",
        SERVICE_ALARM_ARM_NIGHT_INSTANT,
        ELK_USER_CODE_SERVICE_SCHEMA,
        "async_alarm_arm_night_instant",
    ),
    ("number", SERVICE_SENSOR_COUNTER_REFRESH, None, "async_counter_refresh"),
    ("number", SERVICE_SENSOR_COUNTER_SET, COUNTER_SET_SERVICE_SCHEMA, "async_counter_set"),
    ("sensor", SERVICE_SENSOR_ZONE_BYPASS, ELK_USER_CODE_SERVICE_SCHEMA, "async_zone_bypass"),
    ("sensor", SERVICE_SENSOR_ZONE_TRIGGER, None, "async_zone_trigger"),
    (
        "switch",
        SERVICE_SWITCH_OUTPUT_TURN_ON_FOR,
        ELK_OUTPUT_TURN_ON_FOR_SERVICE_SCHEMA,
        "async_switch_output_turn_on_for",
    ),
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Create ElkM1 services, entity services included."""
    for entity_domain, name, schema, func in ENTITY_SERVICES:
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=entity_domain,
            schema=schema,
            func=func,
        )
    hass.services.async_register(
        DOMAIN, "speak_word", _async_speak_word_service, SPEAK_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "speak_phrase", _async_speak_phrase_service, SPEAK_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "set_time", _async_set_time_service, SET_TIME_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "display_message",
        _async_display_message_service,
        DISPLAY_MESSAGE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "get_security_summary",
        _async_get_security_summary,
        SECURITY_SUMMARY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
