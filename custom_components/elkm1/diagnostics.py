"""Diagnostics for Elk-M1 integration."""
from __future__ import annotations

from dataclasses import asdict
from enum import Enum
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .models import ELKM1Data

# Ensure all security credentials and network locators are wiped from the diagnostic output
TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "pin",
    "code",
    "userid",
    "host",
    "serial_port",
    "mac",
}


def _serialize_element(element: Any) -> dict[str, Any]:
    """Convert an elkm1_lib Element's public attrs into a JSON-safe dict."""
    return {
        key: (value.name if isinstance(value, Enum) else value)
        for key, value in element.as_dict().items()
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for config entry."""
    elk_data: ELKM1Data = entry.runtime_data
    coordinator = elk_data.coordinator
    data = coordinator.data if coordinator else None

    diagnostics: dict[str, Any] = {
        "config_entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "prefix": elk_data.prefix,
            "auto_configure": elk_data.auto_configure,
            "config_filters": async_redact_data(elk_data.config, TO_REDACT),
        },
        "panel": {
            "connected": coordinator.connected if coordinator else False,
        },
    }
    if coordinator is not None:
        lifecycle = coordinator.transport_diagnostics
        diagnostics["transport"] = lifecycle
        diagnostics["health"] = {
            "push": (
                "active"
                if sum(lifecycle["broadcast_counts"].values()) > 0
                else "not_observed"
            ),
            "fallback_poll": (
                "healthy" if coordinator.last_update_success else "failed"
            ),
        }

    if data is None:
        return diagnostics

    diagnostics["panel"].update(
        {
            "elkm1_version": data.panel_version,
            "num_areas": data.num_areas,
            "system_trouble_status": data.trouble_status,
            "fire_alarm_active": data.fire_alarm_active,
        }
    )
    diagnostics["areas"] = {idx: asdict(area) for idx, area in data.areas.items()}
    diagnostics["zones_faulted"] = data.faulted_zone_names
    diagnostics["outputs_active"] = data.active_output_names
    diagnostics["bypassed_zones"] = data.bypassed_zones
    diagnostics["zones"] = [
        _serialize_element(zone) for zone in data.zones if zone.configured
    ]
    diagnostics["outputs"] = [
        _serialize_element(output) for output in data.outputs if output.configured
    ]
    diagnostics["thermostats"] = [
        _serialize_element(tstat) for tstat in data.thermostats if tstat.configured
    ]
    diagnostics["tasks"] = [
        _serialize_element(task) for task in data.tasks if task.configured
    ]

    return diagnostics
