"""Tests for redacted lifecycle diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.diagnostics import async_get_config_entry_diagnostics
from custom_components.elkm1.models import AreaData, ElkRuntimeData


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


def _element(**attrs) -> MagicMock:
    element = MagicMock()
    element.configured = True
    element.as_dict.return_value = attrs
    return element


async def test_diagnostics_includes_panel_snapshot_and_serialized_elements(
    hass, mock_network_entry
) -> None:
    """When coordinator data is present, panel/areas/elements are all reported."""
    import enum

    class _FakeEnum(enum.Enum):
        NORMAL = "normal"

    coordinator = MagicMock()
    coordinator.connected = True
    coordinator.last_update_success = False
    coordinator.transport_diagnostics = {"broadcast_counts": {}}
    coordinator.data = MagicMock(
        panel_version="5.2.0",
        num_areas=1,
        trouble_status=False,
        fire_alarm_active=False,
        areas={0: AreaData()},
        faulted_zone_names=["Front Door"],
        active_output_names=["Siren"],
        bypassed_zones=["Zone 1"],
        zones=[
            _element(name="Zone 1", status=_FakeEnum.NORMAL),
            MagicMock(configured=False),
        ],
        outputs=[_element(name="Output 1")],
        thermostats=[_element(name="Thermostat 1")],
        tasks=[_element(name="Task 1")],
    )
    mock_network_entry.runtime_data = ElkRuntimeData(
        prefix="panel",
        mac=mock_network_entry.unique_id,
        auto_configure=False,
        config=dict(mock_network_entry.data),
        coordinator=coordinator,
    )

    result = await async_get_config_entry_diagnostics(hass, mock_network_entry)

    assert result["panel"]["elkm1_version"] == "5.2.0"
    assert result["health"] == {"push": "not_observed", "fallback_poll": "failed"}
    assert result["zones"] == [{"name": "Zone 1", "status": "NORMAL"}]
    assert result["outputs"] == [{"name": "Output 1"}]
    assert result["thermostats"] == [{"name": "Thermostat 1"}]
    assert result["tasks"] == [{"name": "Task 1"}]
    assert result["zones_faulted"] == ["Front Door"]
    assert result["outputs_active"] == ["Siren"]
    assert result["bypassed_zones"] == ["Zone 1"]
