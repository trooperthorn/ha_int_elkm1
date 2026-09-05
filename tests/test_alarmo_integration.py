"""Tests for alarmo_integration.py's elkm1.alarmo_auto_setup service."""
from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.helpers import entity_registry as er

from custom_components.elkm1.alarmo_integration import async_setup_alarmo_auto_config


async def test_auto_setup_with_no_zones_does_not_crash(hass):
    """No hass.components.* crash even when there's nothing to report."""
    await async_setup_alarmo_auto_config(hass)

    result = await hass.services.async_call(
        "elkm1", "alarmo_auto_setup", {}, blocking=True
    )

    assert result is None


async def test_auto_setup_finds_zone_by_unique_id_not_entity_id(hass):
    """Zones are matched via unique_id ("_zone_"), which is stable regardless
    of the panel-configured (and therefore unpredictable) entity_id/name.
    """
    await async_setup_alarmo_auto_config(hass)
    hass.data["alarmo"] = MagicMock()

    entity_reg = er.async_get(hass)
    entry = entity_reg.async_get_or_create(
        "binary_sensor",
        "elkm1",
        "abcdef123456_zone_1",
        suggested_object_id="front_door",
    )
    assert "zone" not in entry.entity_id

    # Must not raise while walking the entity registry to find the zone.
    await hass.services.async_call("elkm1", "alarmo_auto_setup", {}, blocking=True)


async def test_auto_setup_warns_when_alarmo_is_not_installed(hass):
    """A real zone is found, but Alarmo itself isn't installed - must hit the
    dedicated "Alarmo not found" branch, not the "no zones" one."""
    await async_setup_alarmo_auto_config(hass)

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "binary_sensor",
        "elkm1",
        "abcdef123456_zone_1",
        suggested_object_id="front_door",
    )

    result = await hass.services.async_call(
        "elkm1", "alarmo_auto_setup", {}, blocking=True
    )
    assert result is None


async def test_auto_setup_ignores_non_zone_binary_sensors(hass):
    """A trouble-condition binary_sensor (unique_id has _trouble_, not _zone_) is not reported as a zone."""
    await async_setup_alarmo_auto_config(hass)
    hass.data["alarmo"] = MagicMock()

    entity_reg = er.async_get(hass)
    entity_reg.async_get_or_create(
        "binary_sensor",
        "elkm1",
        "abcdef123456_trouble_ac_fail",
        suggested_object_id="ac_fail",
    )

    # No zones registered -> should hit the "no zones found" branch, not crash.
    result = await hass.services.async_call(
        "elkm1", "alarmo_auto_setup", {}, blocking=True
    )
    assert result is None
