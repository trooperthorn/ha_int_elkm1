"""Tests for redacted lifecycle diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.diagnostics import async_get_config_entry_diagnostics
from custom_components.elkm1.models import ElkRuntimeData


async def test_diagnostics_redacts_identity_secrets(
    hass, mock_network_entry
) -> None:
    """Credentials and endpoints are redacted while lifecycle health remains."""
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.connected = False
    coordinator.last_update_success = True
    coordinator.transport_diagnostics = {
        "transport": "network",
        "transport_state": "reconnecting",
        "detected_baud": None,
        "login_state": "authenticated",
        "reconnect_count": 2,
        "last_failure_category": "timeout",
        "last_push_update": None,
        "last_poll_success": None,
        "broadcast_counts": {"ZC": 1},
    }
    mock_network_entry.runtime_data = ElkRuntimeData(
        prefix="panel",
        mac=mock_network_entry.unique_id,
        auto_configure=False,
        config={
            **mock_network_entry.data,
            "username": "user",
            "password": "secret",
            "pin": "1234",
        },
        coordinator=coordinator,
    )

    result = await async_get_config_entry_diagnostics(hass, mock_network_entry)

    assert result["config_entry"]["data"]["host"] == "**REDACTED**"
    assert result["config_entry"]["config_filters"]["password"] == "**REDACTED**"
    assert result["config_entry"]["config_filters"]["pin"] == "**REDACTED**"
    assert result["transport"]["reconnect_count"] == 2
    assert result["health"] == {"push": "active", "fallback_poll": "healthy"}
