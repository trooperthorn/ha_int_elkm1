"""Tests for ElkDataUpdateCoordinator: login/auth handling and command
dispatch, verified against real elkm1_lib.Elk objects where practical.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from elkm1_lib.const import (
    AlarmState,
    ArmedStatus,
    ArmLevel,
    ArmUpState,
    ZoneLogicalStatus,
    ZoneType,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.elkm1.const import (
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PIN,
    CONNECTION_NETWORK,
)
from custom_components.elkm1.coordinator import ElkDataUpdateCoordinator
from custom_components.elkm1.helpers.transport import ElkConnectionManager


def _make_coordinator(hass, **data_overrides) -> ElkDataUpdateCoordinator:
    """Build a coordinator without going through ConfigEntry/DataUpdateCoordinator.__init__ ceremony."""
    data = {
        CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
        CONF_HOST: "elk://1.2.3.4",
        CONF_PIN: "1234",
        **data_overrides,
    }
    return ElkDataUpdateCoordinator(hass, data)


async def _confirm_immediately(sender, *_args, **_kwargs):
    sender()
    return True


def _normalized_elk(area, zones=()):
    """Build the minimal elkm1-lib-shaped object used by normalization tests."""
    return SimpleNamespace(
        areas=[area],
        zones=list(zones),
        panel=SimpleNamespace(elkm1_version="5.3.10"),
        outputs=[],
        tasks=[],
        thermostats=[],
        lights=[],
        counters=[],
        settings=[],
        keypads=[],
    )


def _area(**overrides):
    values = {
        "index": 0,
        "configured": True,
        "armed_status": ArmedStatus.DISARMED,
        "arm_up_state": ArmUpState.READY_TO_ARM,
        "alarm_state": AlarmState.NO_ALARM_ACTIVE,
        "alarm_memory": False,
        "is_exit": False,
        "timer1": 0,
        "timer2": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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
    """An "SD" (element name) reply must wake up coordinator.async_add_listener subscribers."""
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
    ("poll_interval", "expected_heartbeat_timeout"),
    [
        (30, 120.0),  # default poll interval stays under the default heartbeat window
        (90, 120.0),  # poll_interval + 30s margin still under the default window
        (200, 230.0),  # a long poll interval must scale the heartbeat window past it
        (300, 330.0),  # MAX_POLL_INTERVAL
    ],
)
async def test_async_setup_scales_heartbeat_timeout_with_poll_interval(
    hass, poll_interval, expected_heartbeat_timeout
):
    """A poll interval past the default 120s heartbeat window must not force reconnects."""
    coordinator = ElkDataUpdateCoordinator(
        hass,
        {CONF_CONNECTION_TYPE: CONNECTION_NETWORK, CONF_HOST: "elk://1.2.3.4"},
        poll_interval=poll_interval,
    )
    captured: dict[str, float] = {}
    original_init = ElkConnectionManager.__init__

    def _spy_init(self, elk, **kwargs):
        captured["heartbeat_timeout"] = kwargs.get("heartbeat_timeout")
        original_init(self, elk, **kwargs)

    with (
        patch.object(ElkConnectionManager, "__init__", _spy_init),
        patch.object(ElkConnectionManager, "start", lambda self: None),
        patch("custom_components.elkm1.coordinator.CONNECT_TIMEOUT", 0.05),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_setup()

    assert captured["heartbeat_timeout"] == expected_heartbeat_timeout


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
    area.armed_status = (
        ArmedStatus.ARMED_AWAY if expected_level == ArmLevel.DISARM else ArmedStatus.DISARMED
    )
    coordinator._elk = MagicMock()
    coordinator._elk.areas = [area]
    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm_immediately)

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
    zone.logical_status = ZoneLogicalStatus.NORMAL
    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm_immediately)

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
    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm_immediately)

    await coordinator.bypass_area(0, "4321")

    area.bypass.assert_called_once_with(4321)


async def test_clear_bypass_area_uses_zb000_helper(hass):
    """clear_bypass_area delegates to Area.clear_bypass(), not Area.bypass()."""
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    coordinator._elk = MagicMock()
    coordinator._elk.areas = [area]
    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm_immediately)

    await coordinator.clear_bypass_area(0, "4321")

    area.clear_bypass.assert_called_once_with(4321)
    area.bypass.assert_not_called()


@pytest.mark.parametrize("state", tuple("0123456789:;<=>?@AB"))
def test_all_documented_alarm_state_symbols_normalize_without_error(hass, state):
    coordinator = _make_coordinator(hass)
    alarm_state = AlarmState(state)
    coordinator._elk = _normalized_elk(_area(alarm_state=alarm_state))

    data = coordinator._build_normalized_data()

    assert data.areas[0].alarm_state == state


@pytest.mark.parametrize(
    ("is_exit", "timer1", "timer2", "entry", "exit_"),
    [
        (False, 10, 0, 10, 0),
        (False, 0, 20, 20, 0),
        (True, 10, 0, 0, 10),
        (True, 0, 20, 0, 20),
    ],
)
def test_entry_exit_timers_follow_ee_type(hass, is_exit, timer1, timer2, entry, exit_):
    coordinator = _make_coordinator(hass)
    coordinator._elk = _normalized_elk(_area(is_exit=is_exit, timer1=timer1, timer2=timer2))

    area_data = coordinator._build_normalized_data().areas[0]

    assert area_data.entry_delay == entry
    assert area_data.exit_delay == exit_
    assert area_data.entry_delay_active is (entry > 0)
    assert area_data.exit_delay_active is (exit_ > 0)


def test_power_battery_and_detailed_trouble_come_from_ss(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = _normalized_elk(_area())
    status = list("0" * 34)
    status[0] = "1"  # AC fail
    status[4] = "1"  # control low battery
    status[33] = "A"  # fire trouble at zone 17 (ASCII 'A' - ASCII '0')
    coordinator._raw_trouble_status = "".join(status)

    data = coordinator._build_normalized_data()

    assert data.ac_power is False
    assert data.battery_status == "Low"
    assert data.troubles["fire"] is True
    assert data.trouble_details["fire"] == 17


def test_unknown_trouble_state_is_not_reported_healthy(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = _normalized_elk(_area())

    data = coordinator._build_normalized_data()

    assert data.ac_power is None
    assert data.battery_status == "Unknown"


def test_fire_aggregate_excludes_box_tamper_and_includes_all_fire_types(hass):
    coordinator = _make_coordinator(hass)
    box_tamper = SimpleNamespace(
        index=0,
        name="Tamper",
        configured=True,
        logical_status=ZoneLogicalStatus.VIOLATED,
        definition=ZoneType.BURGLAR_BOX_TAMPER,
        triggered_alarm=True,
        temperature=-60,
    )
    verified_fire = SimpleNamespace(
        index=1,
        name="Smoke",
        configured=True,
        logical_status=ZoneLogicalStatus.VIOLATED,
        definition=ZoneType.FIRE_VERIFIED,
        triggered_alarm=True,
        temperature=-60,
    )
    coordinator._elk = _normalized_elk(_area(), [box_tamper, verified_fire])

    assert coordinator._build_normalized_data().fire_alarm_active is True


@pytest.mark.parametrize(("aggregate_code", "expected"), [(1, 0), (2, 1), (7, 0)])
def test_all_lights_aggregate_codes_update_entire_house(hass, aggregate_code, expected):
    coordinator = _make_coordinator(hass)
    lights = [MagicMock() for _ in range(32)]
    coordinator._elk = SimpleNamespace(lights=lights)

    coordinator._handle_all_lights(1, aggregate_code)

    for light in lights[:16]:
        light.setattr.assert_not_called()
    for light in lights[16:]:
        light.setattr.assert_called_once_with("status", expected, True)


async def test_periodic_refresh_requests_safe_status_families_but_not_zs(hass):
    coordinator = _make_coordinator(hass)
    handlers: dict[str, list] = {}
    sent: list[str] = []
    elk = MagicMock()
    elk.is_connected.return_value = True

    def _add_handler(command, handler):
        handlers.setdefault(command, []).append(handler)

    def _remove_handler(command, handler):
        handlers[command].remove(handler)

    def _send(message):
        sent.append(message.message[2:4])
        for handler in handlers.get(message.response_command, []):
            handler()

    elk.add_handler.side_effect = _add_handler
    elk.remove_handler.side_effect = _remove_handler
    elk.send.side_effect = _send
    coordinator._elk = elk
    coordinator._build_normalized_data = MagicMock(return_value=coordinator.data)

    await coordinator._async_update_data()

    assert sent == ["as", "az", "cs", "ss", "lw"]
    assert "zs" not in sent
    assert coordinator.last_poll_success is not None


async def test_confirmed_command_requires_matching_response(hass):
    coordinator = _make_coordinator(hass)
    handlers: dict[str, object] = {}
    elk = MagicMock()
    elk.is_connected.return_value = True
    elk.is_paused.return_value = False
    elk.add_handler.side_effect = lambda command, handler: handlers.update({command: handler})
    elk.remove_handler.side_effect = lambda command, _handler: handlers.pop(command)
    coordinator._elk = elk

    def _sender():
        handler = handlers["ZB"]
        handler(zone_number=7, zone_bypassed=True)
        handler(zone_number=0, zone_bypassed=True)

    await coordinator.async_confirm_command(
        _sender,
        "ZB",
        "test bypass",
        lambda payload: payload.get("zone_number") == 0,
    )

    assert not handlers


async def test_confirmed_command_times_out_instead_of_reporting_success(hass):
    coordinator = _make_coordinator(hass)
    elk = MagicMock()
    elk.is_connected.return_value = True
    elk.is_paused.return_value = False
    coordinator._elk = elk

    from custom_components.elkm1 import coordinator as coordinator_module

    with (
        patch.object(coordinator_module, "COMMAND_RESPONSE_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError, match="was not confirmed"),
    ):
        await coordinator.async_confirm_command(lambda: None, "AS", "test arm")

    assert coordinator.last_command_timeout == "AS"


async def test_display_message_uses_area_helper(hass):
    """display_message delegates to Area.display_message(), not a raw command string."""
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    coordinator._elk = MagicMock()
    coordinator._elk.areas = [area]
    coordinator.async_queue_command = AsyncMock(side_effect=_confirm_immediately)

    await coordinator.display_message(
        area_index=0, line1="Hi", line2="There", beep=True, clear=1, timeout=30
    )

    area.display_message.assert_called_once_with(1, True, 30, "Hi", "There")
