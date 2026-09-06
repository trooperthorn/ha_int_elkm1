"""Tests for __init__.py: config entry setup/unload and the options-reload listener."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elkm1 import async_migrate_entry
from custom_components.elkm1.const import CONF_BAUD_RATE, CONF_POLL_INTERVAL, DOMAIN
from custom_components.elkm1.models import ElkPanelData


async def _fake_first_refresh(self) -> None:
    self.data = ElkPanelData()


async def test_setup_and_unload_entry(hass, mock_serial_entry):
    """A config entry loads successfully and unloads cleanly."""
    mock_serial_entry.add_to_hass(hass)

    with patch(
        "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
        _fake_first_refresh,
    ):
        assert await hass.config_entries.async_setup(mock_serial_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_serial_entry.state is ConfigEntryState.LOADED
    assert mock_serial_entry.runtime_data.coordinator is not None

    assert await hass.config_entries.async_unload(mock_serial_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_serial_entry.state is ConfigEntryState.NOT_LOADED


async def test_options_update_reloads_entry(hass, mock_serial_entry):
    """Changing options (e.g. poll_interval) triggers a reload, not a stale coordinator."""
    mock_serial_entry.add_to_hass(hass)

    with patch(
        "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
        _fake_first_refresh,
    ):
        assert await hass.config_entries.async_setup(mock_serial_entry.entry_id)
        await hass.async_block_till_done()

        hass.config_entries.async_update_entry(
            mock_serial_entry, options={CONF_POLL_INTERVAL: 45}
        )
        await hass.async_block_till_done()

    assert mock_serial_entry.state is ConfigEntryState.LOADED


async def test_migrate_entry_already_current_is_a_no_op(hass):
    """An entry already past the current version is left alone, not re-migrated."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"serial_port": "/dev/ttyUSB0"},
        version=4,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is False


async def test_migrate_entry_rejects_a_network_shaped_entry(hass):
    """Network/M1XEP connectivity was removed entirely (see docs/decisions.md
    2026-09-05) - a network-shaped legacy entry has no supported path
    forward and must fail migration cleanly, not be silently reinterpreted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "elk://1.2.3.4"},
        version=1,
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
    assert entry.version == 3
    assert entry.minor_version == 1
    assert entry.data["connection_type"] == "serial"
    assert entry.data["serial_port"] == "/dev/serial/by-id/elk"
    assert entry.unique_id == "serial:/dev/serial/by-id/elk"


async def test_setup_entry_over_serial_builds_a_serial_url(hass, mock_serial_entry):
    """The serial-port branch of async_setup_entry sets up cleanly."""
    mock_serial_entry.add_to_hass(hass)

    with patch(
        "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
        _fake_first_refresh,
    ):
        assert await hass.config_entries.async_setup(mock_serial_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_serial_entry.state is ConfigEntryState.LOADED


async def test_on_baud_detected_persists_a_changed_baud_rate(hass, mock_serial_entry):
    """The on_baud_detected callback passed to the coordinator updates the config entry."""
    mock_serial_entry.add_to_hass(hass)
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
        assert await hass.config_entries.async_setup(mock_serial_entry.entry_id)
        await hass.async_block_till_done()

        on_baud_detected = captured_kwargs["on_baud_detected"]
        on_baud_detected(115200)
        await hass.async_block_till_done()

    assert mock_serial_entry.data[CONF_BAUD_RATE] == 115200


async def test_setup_entry_raises_config_entry_not_ready_on_first_refresh_failure(
    hass, mock_serial_entry
):
    """A generic failure during first refresh disconnects and surfaces as ConfigEntryNotReady."""
    mock_serial_entry.add_to_hass(hass)

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
        assert not await hass.config_entries.async_setup(mock_serial_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_serial_entry.state is ConfigEntryState.SETUP_RETRY
    disconnect_mock.assert_awaited_once()


async def test_setup_entry_reraises_config_entry_auth_failed_unchanged(
    hass, mock_serial_entry
):
    """ConfigEntryAuthFailed must propagate as-is, not get wrapped as ConfigEntryNotReady."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    mock_serial_entry.add_to_hass(hass)

    async def _auth_failing_first_refresh(self) -> None:
        raise ConfigEntryAuthFailed("bad pin")

    with patch(
        "custom_components.elkm1.coordinator.ElkDataUpdateCoordinator.async_config_entry_first_refresh",
        _auth_failing_first_refresh,
    ):
        assert not await hass.config_entries.async_setup(mock_serial_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_serial_entry.state is ConfigEntryState.SETUP_ERROR


async def test_background_verify_logs_a_warning_on_a_non_fatal_error(
    hass, mock_serial_entry, caplog
):
    """verify_panel_configuration failing must be logged, not crash the setup."""
    mock_serial_entry.add_to_hass(hass)

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
        assert await hass.config_entries.async_setup(mock_serial_entry.entry_id)
        await hass.async_block_till_done()

    assert "Panel verification encountered non-fatal error" in caplog.text
