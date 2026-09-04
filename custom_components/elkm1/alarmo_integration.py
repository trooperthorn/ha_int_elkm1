"""Alarmo auto-setup helper for ELK-M1 integration.

Provides the service that configures Alarmo with ELK-M1 zone sensors.
"""

from __future__ import annotations

import logging

from homeassistant.components.persistent_notification import (
    async_create as async_create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__name__)

ALARMO_DOMAIN = "alarmo"


async def async_setup_alarmo_auto_config(hass: HomeAssistant) -> None:
    """Set up Alarmo auto-configuration service."""

    async def handle_auto_setup_alarmo(call: ServiceCall) -> None:
        """Auto-configure Alarmo with ELK-M1 zones."""
        _LOGGER.info("Starting Alarmo auto-setup for ELK-M1 zones")

        entity_reg = er.async_get(hass)
        elk_zones = []

        for entity in entity_reg.entities.values():
            # Match on unique_id: entity_id comes from the panel zone name and never contains "zone".
            if (
                entity.domain == "binary_sensor"
                and entity.platform == DOMAIN
                and entity.unique_id
                and "_zone_" in entity.unique_id
            ):
                elk_zones.append({
                    "entity_id": entity.entity_id,
                    "name": entity.original_name or entity.name or entity.entity_id,
                    "device_id": entity.device_id,
                })

        if not elk_zones:
            _LOGGER.warning("No ELK-M1 zones found. Install/setup binary_sensor.py first.")
            async_create_notification(
                hass,
                "No ELK-M1 zones found to auto-configure in Alarmo. "
                "Make sure binary_sensor platform is loaded and zones are created.",
                title="Alarmo Auto-Setup Failed",
            )
            return

        if ALARMO_DOMAIN not in hass.data:
            _LOGGER.warning("Alarmo integration not found. Install Alarmo first.")
            async_create_notification(
                hass,
                "Alarmo integration not installed. "
                "Install Alarmo via HACS before running this automation.",
                title="Alarmo Not Found",
            )
            return

        zones_list = "\n".join([f"- {z['name']} ({z['entity_id']})" for z in elk_zones])

        setup_message = f"""
Auto-Setup Complete! {len(elk_zones)} ELK-M1 zones found and ready to configure in Alarmo.

**Zones Found:**
{zones_list}

**Next Steps:**
1. Open Alarmo control panel (Settings > Devices & Services > Alarmo)
2. Click "SENSORS" tab
3. All ELK-M1 zones should appear in the available sensors list
4. For each zone you want to monitor:
   - Click the zone name
   - Select the Device Type (Door, Window, Motion, Fire, Water, etc.)
   - Choose which Arm Modes include this zone (Away, Home, Night)
   - Click "Add to alarm"
5. Go to ACTIONS tab to set up sirens, notifications, etc.
6. Go to CODES tab to set up user codes (optional)

Zones are automatically detected by Alarmo. No manual configuration needed!
"""

        _LOGGER.info("Found %d ELK-M1 zones ready for Alarmo", len(elk_zones))

        async_create_notification(
            hass,
            setup_message,
            title="✅ ELK-M1 → Alarmo Auto-Setup",
            notification_id=f"{DOMAIN}_alarmo_setup_success",
        )

    if not hass.services.has_service(DOMAIN, "alarmo_auto_setup"):
        hass.services.async_register(
            DOMAIN,
            "alarmo_auto_setup",
            handle_auto_setup_alarmo,
        )
        _LOGGER.info("Alarmo auto-setup service registered")
