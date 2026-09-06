"""Tests for services.py's domain-level services (speak_word, speak_phrase,
set_time, display_message, get_security_summary), routed to a coordinator
by prefix.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.elkm1.const import DOMAIN
from custom_components.elkm1.models import AreaData, ElkPanelData, ElkRuntimeData
from custom_components.elkm1.services import async_setup_services


@pytest.fixture
async def registered_coordinator(hass, mock_serial_entry):
    """A config entry with runtime_data wired up, and services registered."""
    mock_serial_entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.speak_word = AsyncMock()
    coordinator.speak_phrase = AsyncMock()
    coordinator.set_panel_time = AsyncMock()
    coordinator.display_message = AsyncMock()
    coordinator.data = ElkPanelData(zones_faulted=[0, 3], areas={0: AreaData(arm_up_state=0)})

    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config=dict(mock_serial_entry.data),
        coordinator=coordinator,
    )

    await async_setup_services(hass)
    return coordinator


async def test_speak_word_routes_to_coordinator(hass, registered_coordinator):
    await hass.services.async_call(DOMAIN, "speak_word", {"number": 42}, blocking=True)
    registered_coordinator.speak_word.assert_called_once_with(42)


async def test_speak_phrase_routes_to_coordinator(hass, registered_coordinator):
    await hass.services.async_call(DOMAIN, "speak_phrase", {"number": 99}, blocking=True)
    registered_coordinator.speak_phrase.assert_called_once_with(99)


async def test_set_time_routes_to_coordinator(hass, registered_coordinator):
    await hass.services.async_call(DOMAIN, "set_time", {}, blocking=True)
    registered_coordinator.set_panel_time.assert_called_once()


async def test_display_message_passes_all_fields(hass, registered_coordinator):
    await hass.services.async_call(
        DOMAIN,
        "display_message",
        {
            "area": 2,
            "line1": "Hello",
            "line2": "World",
            "beep": True,
            "clear": 1,
            "timeout": 30,
        },
        blocking=True,
    )
    registered_coordinator.display_message.assert_called_once_with(
        area_index=1,  # area is 1-indexed in the service, 0-indexed internally
        line1="Hello",
        line2="World",
        beep=True,
        clear=1,
        timeout=30,
    )


async def test_get_security_summary_reports_faulted_zones(hass, registered_coordinator):
    result = await hass.services.async_call(
        DOMAIN, "get_security_summary", {}, blocking=True, return_response=True
    )
    assert result["total_faulted"] == 2
    assert result["is_ready_to_arm"] is False
    assert result["faulted_zone_numbers"] == [1, 4]


async def test_unknown_prefix_raises_homeassistant_error(hass, registered_coordinator):
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "speak_word", {"number": 1, "prefix": "nonexistent"}, blocking=True
        )


async def test_entity_services_register_without_platform_setup(hass) -> None:
    """Every entity service exists after async_setup_services alone."""
    await async_setup_services(hass)

    for name in (
        "alarm_bypass",
        "alarm_clear_bypass",
        "alarm_arm_home_instant",
        "alarm_arm_night_instant",
        "alarm_force_arm_away",
        "alarm_force_arm_stay",
        "sensor_counter_refresh",
        "sensor_counter_set",
        "sensor_zone_bypass",
        "sensor_zone_trigger",
        "switch_output_turn_on_for",
    ):
        assert hass.services.has_service(DOMAIN, name), name
