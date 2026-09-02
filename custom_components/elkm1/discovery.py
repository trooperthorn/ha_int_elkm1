"""Network discovery helpers for the Elk-M1 integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from urllib.parse import urlsplit, urlunsplit

from elkm1_lib.discovery import AIOELKDiscovery, ElkSystem
from homeassistant import config_entries
from homeassistant.components import network
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, discovery_flow

from .const import CONF_HOST, CONF_MAC_ADDRESS, DISCOVER_SCAN_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _short_mac(mac_address: str) -> str:
    """Return the final six hexadecimal characters of a MAC address."""
    return mac_address.replace(":", "").replace("-", "")[-6:]


def _endpoint_with_host(endpoint: str, host: str) -> str:
    """Replace only the host portion of an ELK endpoint."""
    parsed = urlsplit(endpoint)
    if not parsed.scheme:
        return endpoint
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


@callback
def async_update_entry_from_discovery(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    device: ElkSystem,
) -> bool:
    """Apply identity and address updates from a verified ELK discovery."""
    formatted_mac = dr.format_mac(device.mac_address)
    if entry.unique_id and entry.unique_id != formatted_mac:
        return False

    data = dict(entry.data)
    if data.get(CONF_MAC_ADDRESS) != formatted_mac:
        data[CONF_MAC_ADDRESS] = formatted_mac

    endpoint = data.get(CONF_HOST)
    if isinstance(endpoint, str):
        updated_endpoint = _endpoint_with_host(endpoint, device.ip_address)
        if updated_endpoint != endpoint:
            data[CONF_HOST] = updated_endpoint

    unique_id = entry.unique_id or formatted_mac
    if data == dict(entry.data) and unique_id == entry.unique_id:
        return False
    return hass.config_entries.async_update_entry(
        entry, data=data, unique_id=unique_id
    )


async def async_discover_devices(
    hass: HomeAssistant,
    timeout: int = DISCOVER_SCAN_TIMEOUT,
    address: str | None = None,
) -> list[ElkSystem]:
    """Discover ELK M1XEP interfaces using the upstream library."""
    if address:
        targets = [address]
    else:
        targets = [
            str(broadcast_address)
            for broadcast_address in await network.async_get_ipv4_broadcast_addresses(
                hass
            )
        ]

    scanner = AIOELKDiscovery()
    combined: dict[str, ElkSystem] = {}
    results = await asyncio.gather(
        *[
            scanner.async_scan(timeout=timeout, address=target)
            for target in targets
        ],
        return_exceptions=True,
    )
    for target, result in zip(targets, results, strict=True):
        if isinstance(result, Exception):
            _LOGGER.debug("ELK discovery scan of %s failed: %s", target, result)
            continue
        if isinstance(result, BaseException):
            raise result from None
        for device in result:
            combined[device.ip_address] = device
    return list(combined.values())


async def async_discover_device(hass: HomeAssistant, host: str) -> ElkSystem | None:
    """Run directed discovery against one host."""
    for device in await async_discover_devices(hass, DISCOVER_SCAN_TIMEOUT, host):
        if device.ip_address == host:
            return device
    return None


@callback
def async_trigger_discovery(
    hass: HomeAssistant, discovered_devices: list[ElkSystem]
) -> None:
    """Start integration-discovery flows for discovered devices."""
    for device in discovered_devices:
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
            data=asdict(device),
        )
