"""Tests for __init__.py: config entry setup/unload and the options-reload listener."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elkm1 import async_migrate_entry
from custom_components.elkm1.const import CONF_BAUD_RATE, CONF_POLL_INTERVAL, DOMAIN
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


async def test_migrate_entry_already_current_is_a_no_op(hass):
    """An entry already past version 2 is left alone, not re-migrated."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "elk://1.2.3.4"},
        version=3,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is False


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


async def test_setup_entry_over_serial_builds_a_serial_url(hass, mock_serial_entry):
    """The serial-port branch of async_setup_entry (not just network) sets up cleanly."""
    mock_serial_entry.add_to_hass(hass)

    with patch(
        "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
        _fake_first_refresh,
    ):
        assert await hass.config_entries.async_setup(mock_serial_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_serial_entry.state is ConfigEntryState.LOADED


async def test_setup_entry_updates_from_discovery_when_a_matching_device_is_found(
    hass, mock_network_entry
):
    """A network entry with no MAC yet gets its unique_id/data filled in from discovery."""
    mock_network_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_network_entry, unique_id=None)

    discovered = object()
    update_mock = MagicMock()

    with (
        patch(
            "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
            _fake_first_refresh,
        ),
        patch(
            "custom_components.elkm1.async_discover_device",
            AsyncMock(return_value=discovered),
        ) as discover_mock,
        patch(
            "custom_components.elkm1.async_update_entry_from_discovery",
            update_mock,
        ),
    ):
        assert await hass.config_entries.async_setup(mock_network_entry.entry_id)
        await hass.async_block_till_done()

    discover_mock.assert_awaited_once()
    update_mock.assert_called_once_with(hass, mock_network_entry, discovered)


async def test_on_baud_detected_persists_a_changed_baud_rate(hass, mock_network_entry):
    """The on_baud_detected callback passed to the coordinator updates the config entry."""
    mock_network_entry.add_to_hass(hass)
    captured_kwargs: dict = {}

    real_init = None

    def _capturing_init(self, hass_, conf, **kwargs):
        nonlocal captured_kwargs
        captured_kwargs = kwargs
        real_init(self, hass_, conf, **kwargs)

    from custom_components.elkm1.coordinator import ElkDataUpdateCoordinator

    real_init = ElkDataUpdateCoordinator.__init__

    with (
        patch.object(ElkDataUpdateCoordinator, "__init__", _capturing_init),
        patch(
            "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
            _fake_first_refresh,
        ),
    ):
        assert await hass.config_entries.async_setup(mock_network_entry.entry_id)
        await hass.async_block_till_done()

        on_baud_detected = captured_kwargs["on_baud_detected"]
        on_baud_detected(115200)
        await hass.async_block_till_done()

    assert mock_network_entry.data[CONF_BAUD_RATE] == 115200


async def test_setup_entry_raises_config_entry_not_ready_on_first_refresh_failure(
    hass, mock_network_entry
):
    """A generic failure during first refresh disconnects and surfaces as ConfigEntryNotReady."""
    mock_network_entry.add_to_hass(hass)

    async def _failing_first_refresh(self) -> None:
        raise RuntimeError("connect failed")

    disconnect_mock = AsyncMock()

    with (
        patch(
            "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
            _failing_first_refresh,
        ),
        patch(
            "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_disconnect",
            disconnect_mock,
        ),
    ):
        assert not await hass.config_entries.async_setup(mock_network_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_network_entry.state is ConfigEntryState.SETUP_RETRY
    disconnect_mock.assert_awaited_once()


async def test_setup_entry_reraises_config_entry_auth_failed_unchanged(
    hass, mock_network_entry
):
    """ConfigEntryAuthFailed must propagate as-is, not get wrapped as ConfigEntryNotReady."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    mock_network_entry.add_to_hass(hass)

    async def _auth_failing_first_refresh(self) -> None:
        raise ConfigEntryAuthFailed("bad pin")

    with patch(
        "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
        _auth_failing_first_refresh,
    ):
        assert not await hass.config_entries.async_setup(mock_network_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_network_entry.state is ConfigEntryState.SETUP_ERROR


async def test_background_verify_logs_a_warning_on_a_non_fatal_error(
    hass, mock_network_entry, caplog
):
    """verify_panel_configuration failing must be logged, not crash the setup."""
    mock_network_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
            _fake_first_refresh,
        ),
        patch(
            "custom_components.elkm1.verify_panel_configuration",
            AsyncMock(side_effect=RuntimeError("panel not ready")),
        ),
    ):
        assert await hass.config_entries.async_setup(mock_network_entry.entry_id)
        await hass.async_block_till_done()

    assert "Panel verification encountered non-fatal error" in caplog.text
