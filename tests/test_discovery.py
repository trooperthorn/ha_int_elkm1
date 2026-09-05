"""Tests for HA-side DHCP/discovery-flow glue.

This is distinct from tests/test_elk_discovery.py, which covers the UDP
scanner in helpers/elk/discovery.py.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.elkm1.discovery import (
    _endpoint_with_host,
    _short_mac,
    async_discover_device,
    async_discover_devices,
    async_trigger_discovery,
    async_update_entry_from_discovery,
)
from custom_components.elkm1.helpers.elk.discovery import ElkSystem


def _device(mac: str = "AA:BB:CC:DD:EE:FF", ip: str = "1.2.3.4", port: int = 2601) -> ElkSystem:
    return ElkSystem(mac_address=mac, ip_address=ip, port=port)


def test_short_mac_strips_separators_and_keeps_last_six_chars() -> None:
    assert _short_mac("AA:BB:CC:DD:EE:FF") == "DDEEFF"
    assert _short_mac("AA-BB-CC-DD-EE-FF") == "DDEEFF"


def test_endpoint_with_host_replaces_host_only() -> None:
    assert _endpoint_with_host("elk://1.2.3.4:2601", "5.6.7.8") == "elk://5.6.7.8:2601"


def test_endpoint_with_host_replaces_host_without_port() -> None:
    assert _endpoint_with_host("elk://1.2.3.4", "5.6.7.8") == "elk://5.6.7.8"


def test_endpoint_with_host_returns_unchanged_when_no_scheme() -> None:
    assert _endpoint_with_host("/dev/ttyUSB0", "5.6.7.8") == "/dev/ttyUSB0"


def test_update_entry_from_discovery_returns_false_on_unique_id_mismatch(
    hass, mock_network_entry
) -> None:
    mock_network_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_network_entry, unique_id="11:22:33:44:55:66")

    changed = async_update_entry_from_discovery(hass, mock_network_entry, _device())

    assert changed is False


def test_update_entry_from_discovery_updates_mac_and_host(hass, mock_network_entry) -> None:
    mock_network_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_network_entry, unique_id=None)

    changed = async_update_entry_from_discovery(hass, mock_network_entry, _device())

    assert changed is True
    assert mock_network_entry.data["mac_address"] == "aa:bb:cc:dd:ee:ff"
    assert mock_network_entry.data["host"] == "elk://1.2.3.4"
    assert mock_network_entry.unique_id == "aa:bb:cc:dd:ee:ff"


def test_update_entry_from_discovery_returns_false_when_nothing_changes(
    hass, mock_network_entry
) -> None:
    mock_network_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_network_entry, unique_id="aa:bb:cc:dd:ee:ff"
    )
    device = _device(mac="aa:bb:cc:dd:ee:ff", ip="1.2.3.4")

    changed = async_update_entry_from_discovery(hass, mock_network_entry, device)

    assert changed is False


def test_update_entry_from_discovery_ignores_non_string_host(hass, mock_network_entry) -> None:
    mock_network_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_network_entry,
        data={**mock_network_entry.data, "host": None},
        unique_id=None,
    )

    changed = async_update_entry_from_discovery(hass, mock_network_entry, _device())

    assert changed is True
    assert mock_network_entry.data["host"] is None


async def test_async_discover_devices_uses_explicit_address(hass) -> None:
    device = _device()
    scanner = AsyncMock()
    scanner.async_scan = AsyncMock(return_value=[device])

    with patch(
        "custom_components.elkm1.discovery.AIOELKDiscovery", return_value=scanner
    ):
        result = await async_discover_devices(hass, address="1.2.3.4")

    assert result == [device]
    scanner.async_scan.assert_awaited_once_with(timeout=10, address="1.2.3.4")


async def test_async_discover_devices_broadcasts_when_no_address_given(hass) -> None:
    device = _device()
    scanner = AsyncMock()
    scanner.async_scan = AsyncMock(return_value=[device])

    with (
        patch(
            "custom_components.elkm1.discovery.network.async_get_ipv4_broadcast_addresses",
            AsyncMock(return_value=[MagicMock(__str__=lambda self: "192.168.1.255")]),
        ),
        patch(
            "custom_components.elkm1.discovery.AIOELKDiscovery", return_value=scanner
        ),
    ):
        result = await async_discover_devices(hass)

    assert result == [device]
    scanner.async_scan.assert_awaited_once_with(timeout=10, address="192.168.1.255")


async def test_async_discover_devices_dedupes_by_ip_across_targets(hass) -> None:
    device_a = _device(mac="AA:BB:CC:DD:EE:01", ip="1.2.3.4")
    device_b = _device(mac="AA:BB:CC:DD:EE:02", ip="1.2.3.4")
    scanner = AsyncMock()
    scanner.async_scan = AsyncMock(side_effect=[[device_a], [device_b]])

    with (
        patch(
            "custom_components.elkm1.discovery.AIOELKDiscovery", return_value=scanner
        ),
        patch(
            "custom_components.elkm1.discovery.network.async_get_ipv4_broadcast_addresses",
            AsyncMock(return_value=["1.1.1.1", "2.2.2.2"]),
        ),
    ):
        result = await async_discover_devices(hass)

    assert result == [device_b]


async def test_async_discover_devices_skips_scan_exceptions(hass) -> None:
    scanner = AsyncMock()
    scanner.async_scan = AsyncMock(side_effect=OSError("network down"))

    with patch(
        "custom_components.elkm1.discovery.AIOELKDiscovery", return_value=scanner
    ):
        result = await async_discover_devices(hass, address="1.2.3.4")

    assert result == []


async def test_async_discover_devices_reraises_base_exceptions(hass) -> None:
    scanner = AsyncMock()
    scanner.async_scan = AsyncMock(side_effect=asyncio.CancelledError)

    with (
        patch(
            "custom_components.elkm1.discovery.AIOELKDiscovery", return_value=scanner
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await async_discover_devices(hass, address="1.2.3.4")


async def test_async_discover_device_returns_matching_device(hass) -> None:
    device = _device(ip="1.2.3.4")
    with patch(
        "custom_components.elkm1.discovery.async_discover_devices",
        AsyncMock(return_value=[device]),
    ):
        result = await async_discover_device(hass, "1.2.3.4")

    assert result is device


async def test_async_discover_device_returns_none_when_not_found(hass) -> None:
    with patch(
        "custom_components.elkm1.discovery.async_discover_devices",
        AsyncMock(return_value=[]),
    ):
        result = await async_discover_device(hass, "9.9.9.9")

    assert result is None


def test_async_trigger_discovery_creates_a_flow_per_device(hass) -> None:
    device = _device()
    with patch(
        "custom_components.elkm1.discovery.discovery_flow.async_create_flow"
    ) as mock_create_flow:
        async_trigger_discovery(hass, [device])

    mock_create_flow.assert_called_once()
    args, kwargs = mock_create_flow.call_args
    assert args[0] is hass
    assert args[1] == "elkm1"
    assert kwargs["data"]["mac_address"] == "AA:BB:CC:DD:EE:FF"
