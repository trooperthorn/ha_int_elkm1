"""Tests for __init__.py: config entry setup/unload and the options-reload listener."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elkm1 import async_migrate_entry
from custom_components.elkm1.const import CONF_POLL_INTERVAL, DOMAIN
from custom_components.elkm1.models import ElkPanelData


async def _fake_first_refresh(self) -> None:
    self.data = ElkPanelData()


async def test_setup_and_unload_entry(hass, mock_network_entry):
    """A config entry loads successfully and unloads cleanly."""
    mock_network_entry.add_to_hass(hass)

    with patch(
        "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
        _fake_first_refresh,
    ):
        assert await hass.config_entries.async_setup(mock_network_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_network_entry.state is ConfigEntryState.LOADED
    assert mock_network_entry.runtime_data.coordinator is not None

    assert await hass.config_entries.async_unload(mock_network_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_network_entry.state is ConfigEntryState.NOT_LOADED


async def test_options_update_reloads_entry(hass, mock_network_entry):
    """Changing options (e.g. poll_interval) triggers a reload, not a stale coordinator."""
    mock_network_entry.add_to_hass(hass)

    with patch(
        "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
        _fake_first_refresh,
    ):
        assert await hass.config_entries.async_setup(mock_network_entry.entry_id)
        await hass.async_block_till_done()

        hass.config_entries.async_update_entry(
            mock_network_entry, options={CONF_POLL_INTERVAL: 45}
        )
        await hass.async_block_till_done()

    assert mock_network_entry.state is ConfigEntryState.LOADED


async def test_migrate_legacy_serial_entry(hass):
    """Legacy serial URLs migrate to explicit transport and stable identity."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "serial:///dev/serial/by-id/elk", "prefix": "elkm1"},
        version=1,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.minor_version == 1
    assert entry.data["connection_type"] == "serial"
    assert entry.data["serial_port"] == "/dev/serial/by-id/elk"
    assert entry.unique_id == "serial:/dev/serial/by-id/elk"
