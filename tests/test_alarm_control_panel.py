"""Tests for alarm_control_panel.py: state mapping and command failures raising HomeAssistantError."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelEntityFeature
from homeassistant.exceptions import HomeAssistantError

from custom_components.elkm1.alarm_control_panel import ElkAlarmControlPanel
from custom_components.elkm1.models import AreaData, ElkPanelData


def _panel(area_data: AreaData) -> ElkAlarmControlPanel:
    panel = object.__new__(ElkAlarmControlPanel)
    panel._area_index = 0
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(areas={0: area_data})
    panel.coordinator = coordinator
    return panel


@pytest.mark.parametrize(
    ("area_data", "expected_state"),
    [
        (AreaData(alarm_state="2"), AlarmControlPanelState.PENDING),
        (AreaData(alarm_state="1"), AlarmControlPanelState.PENDING),
        (AreaData(exit_delay_active=True), AlarmControlPanelState.ARMING),
        (AreaData(arm_up_state=3), AlarmControlPanelState.ARMING),
        (AreaData(arm_up_state=5, armed_status=1), AlarmControlPanelState.ARMED_AWAY),
        (AreaData(armed_status=1), AlarmControlPanelState.ARMED_AWAY),
        (AreaData(armed_status=2), AlarmControlPanelState.ARMED_HOME),
        (AreaData(armed_status=4), AlarmControlPanelState.ARMED_NIGHT),
        (AreaData(armed_status=6), AlarmControlPanelState.ARMED_VACATION),
        (AreaData(), AlarmControlPanelState.DISARMED),
    ],
)
def test_alarm_state_mapping(area_data, expected_state):
    panel = _panel(area_data)
    assert panel.alarm_state == expected_state


@pytest.mark.parametrize("alarm_state", tuple("3456789:;<=>?@AB"))
def test_every_documented_full_alarm_state_maps_to_triggered(alarm_state):
    """Protocol v1.90 defines every value from '3' through 'B' explicitly."""
    assert _panel(AreaData(alarm_state=alarm_state)).alarm_state == (
        AlarmControlPanelState.TRIGGERED
    )


def test_panic_trigger_feature_is_not_advertised():
    """AP is M1-to-XEP only; the third-party protocol has no panic command."""
    assert not (_panel(AreaData()).supported_features & AlarmControlPanelEntityFeature.TRIGGER)


async def test_failed_disarm_raises_homeassistant_error_not_silent_log():
    """A failed command must surface as a real failure, not a logged-and-ignored one."""
    panel = _panel(AreaData())
    panel.coordinator.async_alarm_disarm = AsyncMock(side_effect=RuntimeError("panel offline"))

    with pytest.raises(HomeAssistantError):
        await panel.async_alarm_disarm("1234")


async def test_successful_disarm_does_not_raise():
    panel = _panel(AreaData())
    panel.coordinator.async_alarm_disarm = AsyncMock(return_value=True)

    await panel.async_alarm_disarm("1234")

    panel.coordinator.async_alarm_disarm.assert_called_once_with(0, 1234)


async def test_bypass_and_clear_bypass_use_distinct_protocol_commands():
    """Area bypass is zb999; clear-all is the distinct zb000 operation."""
    panel = _panel(AreaData())
    panel.coordinator.bypass_area = AsyncMock(return_value=True)
    panel.coordinator.clear_bypass_area = AsyncMock(return_value=True)

    await panel.async_alarm_bypass("1234")
    await panel.async_alarm_clear_bypass("1234")

    panel.coordinator.bypass_area.assert_awaited_once_with(0, "1234")
    panel.coordinator.clear_bypass_area.assert_awaited_once_with(0, "1234")


async def test_alarm_trigger_fails_closed():
    panel = _panel(AreaData())
    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_trigger("1234")
    assert exc_info.value.translation_key == "panic_not_supported"


async def test_invalid_pin_does_not_fall_back_to_configured_pin():
    panel = _panel(AreaData())
    with pytest.raises(HomeAssistantError) as exc_info:
        await panel.async_alarm_disarm("12A4")
    assert exc_info.value.translation_key == "invalid_pin"


def test_area_data_falls_back_to_a_default_when_this_area_is_not_in_coordinator_data():
    panel = _panel(AreaData())
    panel.coordinator.data.areas = {}  # this panel's area index (0) is missing
    assert panel.area_data == AreaData()


def test_alarm_state_pending_on_entry_delay_alone():
    assert _panel(AreaData(entry_delay_active=True)).alarm_state == (
        AlarmControlPanelState.PENDING
    )


async def test_disarm_with_no_code_defaults_to_zero():
    panel = _panel(AreaData())
    panel.coordinator.async_alarm_disarm = AsyncMock(return_value=True)

    await panel.async_alarm_disarm(None)

    panel.coordinator.async_alarm_disarm.assert_called_once_with(0, 0)


def test_alarm_state_none_before_coordinator_has_data():
    panel = _panel(AreaData())
    panel.coordinator.data = None
    assert panel.alarm_state is None


def test_alarm_state_maps_arm_up_state_6_to_custom_bypass():
    area_data = AreaData(arm_up_state=6, armed_status=1)
    assert _panel(area_data).alarm_state == AlarmControlPanelState.ARMED_CUSTOM_BYPASS


def test_changed_by_none_before_coordinator_has_data():
    panel = _panel(AreaData())
    panel.coordinator.data = None
    assert panel.changed_by is None


def test_changed_by_none_when_last_user_name_is_unknown():
    panel = _panel(AreaData())
    panel.coordinator.data.last_user_name = "Unknown"
    assert panel.changed_by is None


async def test_setup_entry_uses_real_area_indices_not_a_contiguous_range(
    hass, mock_network_entry
):
    """A panel can have a gap (e.g. Area 2 never programmed) while a later
    area (e.g. Area 8) is real. range(num_areas) would create an entity for
    the unconfigured gap and skip the real later area entirely - see
    docs/decisions.md 2026-09-05."""
    from custom_components.elkm1.alarm_control_panel import async_setup_entry
    from custom_components.elkm1.models import ElkRuntimeData

    coordinator = MagicMock()
    coordinator.data = ElkPanelData(
        num_areas=3, areas={0: AreaData(), 2: AreaData(), 7: AreaData()}
    )

    mock_network_entry.add_to_hass(hass)
    mock_network_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_network_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []

    def _async_add_entities(new_entities):
        added.extend(new_entities)

    await async_setup_entry(hass, mock_network_entry, _async_add_entities)

    assert {p._area_index for p in added} == {0, 2, 7}


def test_changed_by_returns_the_resolved_user_name():
    panel = _panel(AreaData())
    panel.coordinator.data.last_user_name = "Sean"
    assert panel.changed_by == "Sean"


def test_extra_state_attributes_empty_before_coordinator_has_data():
    panel = _panel(AreaData())
    panel.coordinator.data = None
    assert panel.extra_state_attributes == {}


def test_extra_state_attributes_reports_full_panel_and_area_state():
    area_data = AreaData(
        entry_delay_active=True,
        exit_delay_active=False,
        entry_delay=15,
        exit_delay=0,
        panic_state=False,
        alarm_memory=True,
        alarm_state="0",
    )
    panel = _panel(area_data)
    panel.coordinator.data.armed = True
    panel.coordinator.data.armed_mode = "armed"
    panel.coordinator.data.zones_faulted = [0]
    panel.coordinator.data.faulted_zone_names = ["Zone 1: Front Door"]
    panel.coordinator.data.outputs_active = [1]
    panel.coordinator.data.active_output_names = ["Output 2: Siren"]
    panel.coordinator.data.bypassed_zones = []
    panel.coordinator.last_update_success = True

    attrs = panel.extra_state_attributes

    assert attrs["armed"] is True
    assert attrs["connection_status"] == "Connected"
    assert attrs["zones_faulted_count"] == 1
    assert attrs["outputs_active_count"] == 1
    assert attrs["alarm_memory"] is True
    assert attrs["alarm_triggered"] is False


def test_extra_state_attributes_reports_disconnected_status():
    panel = _panel(AreaData())
    panel.coordinator.last_update_success = False
    assert panel.extra_state_attributes["connection_status"] == "Disconnected"


@pytest.mark.parametrize(
    ("method_name", "coordinator_method"),
    [
        ("async_alarm_arm_home", "async_alarm_arm_home"),
        ("async_alarm_arm_away", "async_alarm_arm_away"),
        ("async_alarm_arm_night", "async_alarm_arm_night"),
        ("async_alarm_arm_vacation", "async_alarm_arm_vacation"),
        ("async_alarm_arm_custom_bypass", "async_alarm_arm_custom_bypass"),
        ("async_alarm_arm_home_instant", "async_alarm_arm_home_instant"),
        ("async_alarm_arm_night_instant", "async_alarm_arm_night_instant"),
    ],
)
async def test_each_arm_variant_delegates_to_its_matching_coordinator_method(
    method_name, coordinator_method
):
    panel = _panel(AreaData())
    setattr(panel.coordinator, coordinator_method, AsyncMock(return_value=True))

    await getattr(panel, method_name)("1234")

    getattr(panel.coordinator, coordinator_method).assert_awaited_once_with(0, 1234)


async def test_run_command_wraps_a_homeassistant_error_from_the_coordinator_unchanged():
    """A HomeAssistantError raised by the coordinator must propagate as-is,
    not get double-wrapped by the generic Exception handler."""
    panel = _panel(AreaData())
    panel.coordinator.async_alarm_arm_home = AsyncMock(
        side_effect=HomeAssistantError("already the right kind of error")
    )

    with pytest.raises(HomeAssistantError, match="already the right kind of error"):
        await panel.async_alarm_arm_home("1234")
