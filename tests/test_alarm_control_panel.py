"""Tests for alarm_control_panel.py: state mapping and the action-exceptions
fix (a failed command used to be swallowed and only logged - HA's service
call/automation trace would show success even when the panel rejected or
never received the command).
"""

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
    with pytest.raises(HomeAssistantError, match="does not support"):
        await panel.async_alarm_trigger("1234")


async def test_invalid_pin_does_not_fall_back_to_configured_pin():
    panel = _panel(AreaData())
    with pytest.raises(HomeAssistantError, match="numeric digits"):
        await panel.async_alarm_disarm("12A4")
