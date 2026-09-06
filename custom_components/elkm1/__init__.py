"""Elk-M1 Control integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PREFIX, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .alarmo_integration import async_setup_alarmo_auto_config
from .const import (
    CONF_AUTO_CONFIGURE,
    CONF_BAUD_RATE,
    CONF_CONNECTION_TYPE,
    CONF_DEVICE_ID,
    CONF_POLL_INTERVAL,
    CONF_SERIAL_PORT,
    CONNECTION_SERIAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .coordinator import ElkDataUpdateCoordinator
from .entity import create_elk_system_device_info
from .helpers.panel_settings import verify_panel_configuration
from .models import ElkRuntimeData
from .services import async_setup_services

if TYPE_CHECKING:
    ElkM1ConfigEntry = ConfigEntry[ElkRuntimeData]
else:
    ElkM1ConfigEntry = ConfigEntry

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SCENE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]


def hostname_from_url(url: str) -> str:
    """Return the hostname from a url."""
    parsed = urlparse(url)
    return parsed.hostname or url.replace("serial://", "")


async def async_setup(hass: HomeAssistant, _hass_config: dict[str, Any]) -> bool:
    """Set up the Elk-M1 integration (services only; no YAML config import)."""
    await async_setup_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy entries to the explicit, serial-only transport schema.

    Network/M1XEP connectivity was removed entirely (see docs/decisions.md
    2026-09-05 - serial-only is a deliberate security posture, not a gap).
    A network-shaped entry has no supported path forward and fails to
    migrate; a serial-shaped entry from either schema version is normalized.
    """
    if entry.version > 3:
        return False

    data = dict(entry.data)
    serial_port = data.get(CONF_SERIAL_PORT)
    legacy_host = str(data.get("host", ""))
    if not serial_port and not legacy_host.startswith("serial://"):
        return False

    if not serial_port:
        serial_port = hostname_from_url(legacy_host)
        data[CONF_SERIAL_PORT] = serial_port
    data.pop("host", None)
    data[CONF_CONNECTION_TYPE] = CONNECTION_SERIAL
    device_id = str(data.get(CONF_DEVICE_ID) or f"serial:{serial_port}")
    data[CONF_DEVICE_ID] = device_id

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        unique_id=device_id,
        version=3,
        minor_version=1,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ElkM1ConfigEntry) -> bool:
    """Set up Elk-M1 Control from a config entry."""
    conf = dict(entry.data)

    serial_port = conf.get(CONF_SERIAL_PORT)
    if not serial_port:
        raise ConfigEntryNotReady("Serial port not configured")
    connection_url = f"serial://{serial_port}"
    conf[CONF_CONNECTION_TYPE] = CONNECTION_SERIAL

    _LOGGER.info("Setting up elkm1 at %s", connection_url)

    def _on_baud_detected(baud: int) -> None:
        """Persist a newly detected baud rate so reconnects try it first."""
        if entry.data.get(CONF_BAUD_RATE) != baud:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_BAUD_RATE: baud}
            )

    poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)

    coordinator = ElkDataUpdateCoordinator(
        hass, conf, on_baud_detected=_on_baud_detected, poll_interval=poll_interval
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        await coordinator.async_disconnect()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"connection_url": connection_url},
        ) from err

    # Not awaited: diagnostic only, and it sleeps to let broadcasts arrive.
    async def _background_verify() -> None:
        try:
            await verify_panel_configuration(coordinator)
        except Exception as err:
            _LOGGER.warning("Panel verification encountered non-fatal error: %s", err)

    entry.async_create_background_task(
        hass, _background_verify(), "elkm1_panel_verification"
    )

    prefix: str = conf.get(CONF_PREFIX, "")
    auto_configure: bool = conf.get(CONF_AUTO_CONFIGURE, False)

    entry.runtime_data = ElkRuntimeData(
        prefix=prefix,
        mac=entry.unique_id,
        auto_configure=auto_configure,
        config=dict(conf),
        coordinator=coordinator,
    )

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        **create_elk_system_device_info(entry, sw_version=coordinator.data.panel_version),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    if async_setup_alarmo_auto_config is not None:
        await async_setup_alarmo_auto_config(hass)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ElkM1ConfigEntry) -> None:
    """Reload the config entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ElkM1ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    coordinator = entry.runtime_data.coordinator
    if unload_ok and coordinator:
        await coordinator.async_shutdown()
        await coordinator.async_disconnect()

    return unload_ok
