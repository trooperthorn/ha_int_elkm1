# custom_components/elkm1/device_action.py
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN

ACTION_TYPES = {"speak_phrase", "display_message"}

# Defines the UI fields the user will see in the automation editor
ACTION_SCHEMA = cv.DEVICE_ACTION_BASE_SCHEMA.extend({
    vol.Required("type"): vol.In(ACTION_TYPES),
    vol.Optional("phrase_number"): cv.positive_int,
    vol.Optional("line1"): cv.string,
})

async def async_get_actions(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """Populate the 'Add Action' dropdown in the device UI."""
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)

    # Verify this device actually belongs to our integration
    if device and any(entry[0] == DOMAIN for entry in device.identifiers):
        return [
            {"device_id": device_id, "domain": DOMAIN, "type": "speak_phrase"},
            {"device_id": device_id, "domain": DOMAIN, "type": "display_message"},
        ]
    return []

async def async_call_action_from_config(
    hass: HomeAssistant,
    config: dict[str, Any],
    variables: dict[str, Any],
    context: Context | None,
) -> None:
    """Execute the action when the automation fires."""
    action_type = config["type"]

    if action_type == "speak_phrase":
        await hass.services.async_call(
            DOMAIN, "speak_phrase",
            {"number": config.get("phrase_number")},
            context=context,
        )
    elif action_type == "display_message":
        await hass.services.async_call(
            DOMAIN, "display_message",
            {"line1": config.get("line1", "")},
            context=context,
        )
