"""Tests for ElkDataUpdateCoordinator: login/auth handling and command
dispatch, verified against real elkm1_lib.Elk objects rather than mocks
wherever practical, since the actual bug classes found during development
(wrong event name, wrong enum values, wrong command encoding) only show up
against the real library's behavior.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from elkm1_lib.const import ArmLevel
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.elkm1.const import (
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PIN,
    CONNECTION_NETWORK,
)
from custom_components.elkm1.coordinator import ElkDataUpdateCoordinator


def _make_coordinator(hass, **data_overrides) -> ElkDataUpdateCoordinator:
    """Build a coordinator without going through ConfigEntry/DataUpdateCoordinator.__init__ ceremony."""
    data = {
        CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
        CONF_HOST: "elk://1.2.3.4",
        CONF_PIN: "1234",
        **data_overrides,
    }
    return ElkDataUpdateCoordinator(hass, data)


@pytest.fixture
def _patch_login(request):
    """Patch the entry-owned manager to synchronously fire login."""
    succeeded = request.param

    def fake_start(self) -> None:
        self.elk._notifier.notify("login", {"succeeded": succeeded})

    with patch(
        "custom_components.elkm1.coordinator.ElkConnectionManager.start",
        fake_start,
    ):
        yield


@pytest.mark.parametrize("_patch_login", [True], indirect=True)
async def test_async_setup_succeeds_on_login_success(hass, _patch_login):
    """A successful login leaves the coordinator connected, no exception."""
    coordinator = _make_coordinator(hass)
    await coordinator._async_setup()
    assert coordinator._elk is not None
    await coordinator.async_disconnect()


@pytest.mark.parametrize("_patch_login", [False], indirect=True)
async def test_async_setup_raises_auth_failed_on_login_failure(hass, _patch_login):
    """A rejected login raises ConfigEntryAuthFailed, triggering HA's reauth flow."""
    coordinator = _make_coordinator(hass)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_setup()
    assert coordinator._elk is None


async def test_async_setup_raises_update_failed_on_timeout(hass):
    """No login event at all (dead link) raises UpdateFailed, not a silent hang."""
    with patch(
        "custom_components.elkm1.coordinator.ElkConnectionManager.start",
        lambda self: None,
    ):
        coordinator = _make_coordinator(hass)
        from custom_components.elkm1 import coordinator as coordinator_module

        with (
            patch.object(coordinator_module, "CONNECT_TIMEOUT", 0.05),
            pytest.raises(UpdateFailed),
        ):
            await coordinator._async_setup()
    assert coordinator._elk is None


@pytest.mark.parametrize("_patch_login", [True], indirect=True)
async def test_sd_reply_notifies_coordinator_listeners(hass, _patch_login):
    """An "SD" (element name) reply must wake up coordinator.async_add_listener
    subscribers - this is what lets entity.async_add_dynamic_entities() add a
    zone/output/etc. entity as soon as it individually becomes `.configured`,
    rather than only at the platform's single async_setup_entry() call.
    """
    coordinator = _make_coordinator(hass)
    await coordinator._async_setup()
    assert coordinator._elk is not None

    calls = 0

    def _listener() -> None:
        nonlocal calls
        calls += 1

    coordinator.async_add_listener(_listener)

    coordinator._elk._notifier.notify(
        "SD", {"desc_type": 0, "unit": 0, "desc": "Front Door", "show_on_keypad": False}
    )

    assert calls == 1
    await coordinator.async_shutdown()
    await coordinator.async_disconnect()


async def test_poll_interval_is_configurable(hass):
    """poll_interval flows through to DataUpdateCoordinator.update_interval."""
    coordinator = ElkDataUpdateCoordinator(
        hass,
        {
            CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
            CONF_HOST: "elk://1.2.3.4",
        },
        poll_interval=90,
    )
    assert coordinator.update_interval == timedelta(seconds=90)


@pytest.mark.parametrize(
    ("method_name", "expected_level"),
    [
        ("async_alarm_disarm", ArmLevel.DISARM),
        ("async_alarm_arm_away", ArmLevel.ARMED_AWAY),
        ("async_alarm_arm_home", ArmLevel.ARMED_STAY),
        ("async_alarm_arm_night", ArmLevel.ARMED_NIGHT),
        ("async_alarm_arm_vacation", ArmLevel.ARMED_VACATION),
        ("async_alarm_arm_home_instant", ArmLevel.ARMED_STAY_INSTANT),
        ("async_alarm_arm_night_instant", ArmLevel.ARMED_NIGHT_INSTANT),
    ],
)
async def test_arm_commands_use_correct_arm_level(hass, method_name, expected_level):
    """Each arm-variant coordinator method sends the correct elkm1_lib ArmLevel."""
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    area.is_armed = MagicMock(return_value=False)
    coordinator._elk = MagicMock()
    coordinator._elk.areas = [area]

    await getattr(coordinator, method_name)(0, 4321)

    if expected_level == ArmLevel.DISARM:
        area.disarm.assert_called_once_with(4321)
    else:
        area.arm.assert_called_once_with(expected_level, 4321)


async def test_bypass_zone_and_unbypass_zone_both_toggle(hass):
    """Zone unbypass re-sends the same toggle command (protocol has no separate unbypass)."""
    coordinator = _make_coordinator(hass)
    zone = MagicMock()
    coordinator._elk = MagicMock()
    coordinator._elk.zones = [zone]

    await coordinator.bypass_zone(1, "4321")
    await coordinator.unbypass_zone(1, "4321")

    assert zone.bypass.call_count == 2
    zone.bypass.assert_called_with(4321)


async def test_bypass_area_toggles_all_zones(hass):
    """bypass_area calls Area.bypass(), the all-zone (999) toggle command."""
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    coordinator._elk = MagicMock()
    coordinator._elk.areas = [area]

    await coordinator.bypass_area(0, "4321")

    area.bypass.assert_called_once_with(4321)


async def test_display_message_uses_area_helper(hass):
    """display_message delegates to Area.display_message(), not a raw command string."""
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    coordinator._elk = MagicMock()
    coordinator._elk.areas = [area]

    await coordinator.display_message(
        area_index=0, line1="Hi", line2="There", beep=True, clear=1, timeout=30
    )

    area.display_message.assert_called_once_with(1, True, 30, "Hi", "There")
