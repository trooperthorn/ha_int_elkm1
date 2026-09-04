"""Utility functions for Elk-M1 integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)


def deprecate_entity(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    platform: str,
    unique_id: str,
    new_unique_id: str,
    new_translation_key: str,
    old_entity_id: str,
    new_entity_id: str,
) -> bool:
    """Handle entity deprecation, migration, or cleanup safely.

    Returns True to allow entity creation, or False to skip.
    """
    try:
        entity_id = entity_registry.async_get_entity_id(platform, "elkm1", unique_id)
        if entity_id:
            entry = entity_registry.async_get(entity_id)
            if entry and entry.entity_id != new_entity_id and not entity_registry.async_get(new_entity_id):
                _LOGGER.info(
                    "Migrating legacy Elk-M1 entity %s to new structure",
                    entry.entity_id,
                )
                entity_registry.async_update_entity(
                    entity_id, new_unique_id=new_unique_id
                )
    except Exception as err:
        _LOGGER.debug("Error during entity deprecation check for %s: %s", unique_id, err)

    return True
