"""Tests for ElkDataUpdateCoordinator: login/auth handling and command
dispatch, verified against real helpers.elk.Elk objects where practical.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.elkm1.const import (
    CONF_CONNECTION_TYPE,
    CONF_HOST,
    CONF_PIN,
    CONNECTION_NETWORK,
)
from custom_components.elkm1.coordinator import ElkDataUpdateCoordinator
from custom_components.elkm1.helpers.elk.const import (
    AlarmState,
    ArmedStatus,
    ArmLevel,
    ArmUpState,
    ZoneLogicalStatus,
    ZoneType,
)
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
    """Build the minimal helpers.elk-shaped object used by normalization tests."""
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


@pytest.mark.parametrize("_patch_login", [True], indirect=True)
async def test_ld_reply_fires_a_log_event_with_a_human_readable_description(hass, _patch_login):
    """An "LD" (system log) reply must fire EVENT_ELKM1_LOG_EVENT with the
    event code's description from event_log.py, not just the bare code."""
    coordinator = _make_coordinator(hass)
    await coordinator._async_setup()
    assert coordinator._elk is not None

    events = []
    hass.bus.async_listen(
        "elkm1.log_event", lambda event: events.append(event.data)
    )

    coordinator._elk._notifier.notify(
        "LD",
        {
            "area": 0,
            "log": {
                "event": 4176,
                "number": 1,
                "index": 1,
                "timestamp": "2026-09-05T05:00:00+00:00",
            },
        },
    )
    await hass.async_block_till_done()

    assert events == [
        {
            "area": 1,
            "event": 4176,
            "description": "zone 176 state",
            "number": 1,
            "index": 1,
            "timestamp": "2026-09-05T05:00:00+00:00",
        }
    ]
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
    """Each arm-variant coordinator method sends the correct ArmLevel."""
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
        pytest.raises(HomeAssistantError) as exc_info,
    ):
        await coordinator.async_confirm_command(lambda: None, "AS", "test arm")

    assert exc_info.value.translation_key == "command_not_confirmed"
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


# --------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------


def test_broadcast_counts_returns_a_copy_not_the_live_dict(hass):
    coordinator = _make_coordinator(hass)
    counts = coordinator.broadcast_counts
    counts["ZC"] = 999
    assert coordinator.broadcast_counts["ZC"] == 0


def test_transport_diagnostics_defaults_when_no_connection_manager(hass):
    coordinator = _make_coordinator(hass)
    diagnostics = coordinator.transport_diagnostics
    assert diagnostics["transport_state"] == "stopped"
    assert diagnostics["detected_baud"] is None
    assert diagnostics["login_state"] == "unknown"
    assert diagnostics["reconnect_count"] == 0
    assert diagnostics["last_failure_category"] is None


def test_transport_diagnostics_reflects_the_connection_manager(hass):
    coordinator = _make_coordinator(hass)
    manager = MagicMock()
    manager.transport_state = "connected"
    manager.detected_baud = 115200
    manager.login_state = "authenticated"
    manager.reconnect_count = 2
    manager.last_failure_category = "timeout"
    coordinator._connection_manager = manager

    diagnostics = coordinator.transport_diagnostics

    assert diagnostics["transport_state"] == "connected"
    assert diagnostics["detected_baud"] == 115200
    assert diagnostics["login_state"] == "authenticated"
    assert diagnostics["reconnect_count"] == 2
    assert diagnostics["last_failure_category"] == "timeout"


def test_connected_false_before_any_elk_instance(hass):
    coordinator = _make_coordinator(hass)
    assert coordinator.connected is False


def test_connected_reflects_the_elk_instance(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.is_connected.return_value = True
    assert coordinator.connected is True


# --------------------------------------------------------------------------
# Connection URL construction
# --------------------------------------------------------------------------


def test_build_connection_url_raises_for_missing_serial_port(hass):
    from custom_components.elkm1.const import CONNECTION_SERIAL

    with pytest.raises(ValueError, match="Serial port not configured"):
        _make_coordinator(hass, **{CONF_CONNECTION_TYPE: CONNECTION_SERIAL})


def test_build_connection_url_raises_for_missing_host(hass):
    with pytest.raises(ValueError, match="Host not configured"):
        _make_coordinator(hass, **{CONF_HOST: ""})


def test_build_connection_url_raises_for_unknown_connection_type(hass):
    with pytest.raises(ValueError, match="Unknown connection type"):
        _make_coordinator(hass, **{CONF_CONNECTION_TYPE: "carrier_pigeon"})


def test_build_connection_url_defaults_the_network_port(hass):
    coordinator = _make_coordinator(hass, **{CONF_HOST: "1.2.3.4"})
    assert coordinator._url == "elk://1.2.3.4:2101"


def test_obfuscated_url_passes_through_serial_urls_unredacted(hass):
    from custom_components.elkm1.const import CONF_SERIAL_PORT, CONNECTION_SERIAL

    coordinator = _make_coordinator(
        hass, **{CONF_CONNECTION_TYPE: CONNECTION_SERIAL, CONF_SERIAL_PORT: "COM3"}
    )
    assert coordinator._obfuscated_url() == "serial://COM3"


def test_obfuscated_url_redacts_the_host_but_keeps_the_scheme(hass):
    coordinator = _make_coordinator(hass)
    assert coordinator._obfuscated_url() == "elk://<redacted>"


def test_obfuscated_url_falls_back_when_there_is_no_scheme(hass):
    coordinator = _make_coordinator(hass)
    coordinator._url = "not-a-url"
    assert coordinator._obfuscated_url() == "<redacted>"


# --------------------------------------------------------------------------
# _async_setup: secure network credentials and error handling
# --------------------------------------------------------------------------


@pytest.mark.parametrize("_patch_login", [True], indirect=True)
async def test_async_setup_sends_configured_credentials_for_a_secure_scheme(hass, _patch_login):
    from custom_components.elkm1.const import CONF_PASSWORD, CONF_USERNAME

    coordinator = _make_coordinator(
        hass,
        **{CONF_HOST: "elks://1.2.3.4:2601", CONF_USERNAME: "admin", CONF_PASSWORD: "secret"},
    )
    captured_config: dict[str, object] = {}
    from custom_components.elkm1.helpers.elk import Elk as RealElk

    original_init = RealElk.__init__

    def _spy_init(self, config, *args, **kwargs):
        captured_config.update(config)
        original_init(self, config, *args, **kwargs)

    with patch.object(RealElk, "__init__", _spy_init):
        await coordinator._async_setup()

    assert captured_config["userid"] == "admin"
    assert captured_config["password"] == "secret"
    await coordinator.async_disconnect()


async def test_async_setup_logs_recovery_only_after_a_prior_failure(hass, caplog):
    """Companion to test_async_setup_logs_recovery_after_a_prior_failure -
    same connected-writer fixture, but starting "already healthy" so the
    recovery log must NOT fire (a real test of the `if not
    self.last_update_success` guard, not just an always-silent one)."""

    def fake_start(self) -> None:
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        self.connection.writer = writer
        self.elk._notifier.notify("login", {"succeeded": True})

    coordinator = _make_coordinator(hass)
    coordinator.last_update_success = True  # simulate "already healthy" - no recovery log expected

    with (
        patch(
            "custom_components.elkm1.coordinator.ElkConnectionManager.start",
            fake_start,
        ),
        caplog.at_level(logging.INFO),
    ):
        await coordinator._async_setup()

    assert "connection recovered" not in caplog.text
    await coordinator.async_disconnect()


async def test_async_setup_logs_recovery_after_a_prior_failure(hass, caplog):
    """The "recovered" log is only reachable when the panel is actually
    connected at login time - `_patch_login`'s fake `start()` never opens a
    real transport, so `elk.is_connected()` is always False there and this
    branch needs its own fixture that also fakes a connected writer."""

    def fake_start(self) -> None:
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        self.connection.writer = writer
        self.elk._notifier.notify("login", {"succeeded": True})

    coordinator = _make_coordinator(hass)
    coordinator.last_update_success = False  # simulate "was unavailable" - recovery log expected

    with (
        patch(
            "custom_components.elkm1.coordinator.ElkConnectionManager.start",
            fake_start,
        ),
        caplog.at_level(logging.INFO),
    ):
        await coordinator._async_setup()

    assert "Elk-M1 connection recovered" in caplog.text
    await coordinator.async_disconnect()


async def test_async_setup_stops_the_manager_on_unexpected_cancellation(hass):
    """A BaseException (e.g. task cancellation) during the login wait must
    still tear down the connection manager and clear `_elk`, not leak it."""
    coordinator = _make_coordinator(hass)

    async def _raise_cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    with (
        patch(
            "custom_components.elkm1.coordinator.ElkConnectionManager.start",
            lambda self: None,
        ),
        patch("asyncio.wait", _raise_cancelled),
        pytest.raises(asyncio.CancelledError),
    ):
        await coordinator._async_setup()

    assert coordinator._elk is None


# --------------------------------------------------------------------------
# Event-firing handlers
# --------------------------------------------------------------------------


async def test_handle_keypad_change_fires_on_a_real_keypress(hass):
    coordinator = _make_coordinator(hass)
    events = []
    hass.bus.async_listen("elkm1.keypad_key_pressed", lambda event: events.append(event.data))
    keypad = SimpleNamespace(index=0, name="Front Door")

    coordinator._handle_keypad_change(keypad, {"last_keypress": ("STAR", 11)})
    await hass.async_block_till_done()

    assert events == [
        {"keypad_id": 1, "keypad_name": "Front Door", "key": 11, "key_name": "STAR"}
    ]


def test_handle_keypad_change_ignores_unrelated_changesets(hass):
    coordinator = _make_coordinator(hass)
    events = []
    hass.bus.async_listen("elkm1.keypad_key_pressed", lambda event: events.append(event.data))
    keypad = SimpleNamespace(index=0, name="Front Door")

    coordinator._handle_keypad_change(keypad, {"area": 1})
    coordinator._handle_keypad_change(keypad, {"last_keypress": None})

    assert events == []


async def test_handle_user_code_clears_attribution_for_an_invalid_code(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    events = []
    hass.bus.async_listen("elkm1.user_code_entered", lambda event: events.append(event.data))

    coordinator._handle_user_code("1234", -1, 0)
    await hass.async_block_till_done()

    assert coordinator._last_user is None
    assert events == [{"keypad_id": 1, "user_number": None, "valid": False}]


def test_handle_keypad_detail_stores_the_full_status(hass):
    coordinator = _make_coordinator(hass)
    coordinator._handle_keypad_detail(0, 11, (2, 0, 1, 0, 0, 0), False, (2, 0, 0, 0, 0, 0, 0, 0))
    assert coordinator._keypad_status[0] == {
        "function_key_lights": [2, 0, 1, 0, 0, 0],
        "bypass_requires_code": False,
        "beep_chime_by_area": [2, 0, 0, 0, 0, 0, 0, 0],
    }


def test_handle_all_lights_ignores_an_undocumented_aggregate_code(hass, caplog):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.lights = [MagicMock() for _ in range(16)]

    coordinator._handle_all_lights(0, 99)

    for light in coordinator._elk.lights:
        light.setattr.assert_not_called()
    assert "Ignoring unknown ELK all-lights code" in caplog.text


def test_handle_all_lights_is_a_noop_before_elk_is_connected(hass):
    coordinator = _make_coordinator(hass)
    coordinator._handle_all_lights(0, 2)  # must not raise


def test_handle_command_timeout_records_the_message_code(hass):
    coordinator = _make_coordinator(hass)
    coordinator._handle_command_timeout("AS")
    assert coordinator.last_command_timeout == "AS"


def test_handle_disconnected_marks_the_manager_and_sets_update_error(hass):
    coordinator = _make_coordinator(hass)
    manager = MagicMock()
    coordinator._connection_manager = manager

    coordinator._handle_disconnected()

    manager.mark_disconnected.assert_called_once()
    assert coordinator.last_update_success is False


async def test_handle_timer_event_fires_with_the_correct_type(hass):
    """async: EventBus.async_fire() queues rather than delivers immediately
    when called while another dispatch is in flight (a prior test's
    teardown can still have one scheduled) - await async_block_till_done()
    so a queued dispatch is flushed before asserting, instead of relying on
    synchronous delivery."""
    coordinator = _make_coordinator(hass)
    events = []
    hass.bus.async_listen("elkm1_timer_event", lambda event: events.append(event.data))

    coordinator._handle_timer_event(0, True, 10, 0, ArmedStatus.ARMED_AWAY)
    await hass.async_block_till_done()

    assert events == [
        {"area": 1, "type": "exit", "timer1": 10, "timer2": 0, "armed_status": 1}
    ]


async def test_handle_alarm_memory_lists_only_flagged_areas(hass):
    coordinator = _make_coordinator(hass)
    events = []
    hass.bus.async_listen("elkm1_alarm_memory", lambda event: events.append(event.data))

    coordinator._handle_alarm_memory([True, False, False, True])
    await hass.async_block_till_done()

    assert events == [{"areas": [1, 4]}]


def test_handle_zone_definitions_requests_voltage_for_analog_zones(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    zones = [MagicMock() for _ in range(2)]
    coordinator._elk.zones = zones

    coordinator._handle_zone_definitions([ZoneType.DISABLED, ZoneType.ANALOG_ZONE])

    zones[0].get_voltage.assert_not_called()
    zones[1].get_voltage.assert_called_once()


def test_handle_zone_definitions_is_a_noop_before_elk_is_connected(hass):
    coordinator = _make_coordinator(hass)
    coordinator._handle_zone_definitions([ZoneType.ANALOG_ZONE])  # must not raise


def test_handle_trouble_status_normalizes_and_pushes_a_snapshot(hass):
    coordinator = _make_coordinator(hass)
    coordinator._build_normalized_data = MagicMock(return_value=coordinator.data)
    coordinator._handle_trouble_status("0" * 36)
    assert coordinator._raw_trouble_status == "0" * 34


# --------------------------------------------------------------------------
# async_disconnect
# --------------------------------------------------------------------------


async def test_async_disconnect_logs_and_swallows_a_transport_error(hass, caplog):
    coordinator = _make_coordinator(hass)
    manager = AsyncMock()
    manager.async_stop.side_effect = OSError("already closed")
    coordinator._connection_manager = manager
    coordinator._elk = MagicMock()

    await coordinator.async_disconnect()

    assert "Error disconnecting" in caplog.text
    assert coordinator._elk is None


async def test_async_disconnect_is_a_noop_without_a_manager(hass):
    coordinator = _make_coordinator(hass)
    await coordinator.async_disconnect()  # must not raise


# --------------------------------------------------------------------------
# _build_normalized_data edge cases
# --------------------------------------------------------------------------


def test_build_normalized_data_returns_cached_data_before_elk_is_connected(hass):
    coordinator = _make_coordinator(hass)
    assert coordinator._build_normalized_data() is coordinator.data


def test_build_normalized_data_lists_bypassed_zones(hass):
    coordinator = _make_coordinator(hass)
    zone = SimpleNamespace(
        index=0,
        name="Front Door",
        configured=True,
        logical_status=ZoneLogicalStatus.BYPASSED,
        definition=ZoneType.BURGLAR_ENTRY_EXIT_1,
        triggered_alarm=False,
        temperature=-60,
    )
    coordinator._elk = _normalized_elk(_area(), [zone])
    data = coordinator._build_normalized_data()
    assert data.bypassed_zones == ["Zone 1: Front Door"]


def test_build_normalized_data_lists_active_outputs(hass):
    coordinator = _make_coordinator(hass)
    output = SimpleNamespace(index=2, name="Siren", configured=True, output_on=True)
    elk = _normalized_elk(_area())
    elk.outputs = [output]
    coordinator._elk = elk
    data = coordinator._build_normalized_data()
    assert data.outputs_active == [2]
    assert data.active_output_names == ["Output 3: Siren"]


def test_build_normalized_data_finds_the_first_valid_zone_temperature(hass):
    coordinator = _make_coordinator(hass)
    cold_zone = SimpleNamespace(
        index=0,
        name="Attic",
        configured=True,
        logical_status=ZoneLogicalStatus.NORMAL,
        definition=ZoneType.TEMPERATURE,
        triggered_alarm=False,
        temperature=-60,
    )
    warm_zone = SimpleNamespace(
        index=1,
        name="Basement",
        configured=True,
        logical_status=ZoneLogicalStatus.NORMAL,
        definition=ZoneType.TEMPERATURE,
        triggered_alarm=False,
        temperature=68,
    )
    coordinator._elk = _normalized_elk(_area(), [cold_zone, warm_zone])
    data = coordinator._build_normalized_data()
    assert data.panel_temperature == 68


def test_build_normalized_data_resolves_the_last_user_name(hass):
    coordinator = _make_coordinator(hass)
    coordinator._last_user = 2
    elk = _normalized_elk(_area())
    elk.users = MagicMock()
    elk.users.username.return_value = "Sean"
    coordinator._elk = elk
    data = coordinator._build_normalized_data()
    assert data.last_user_name == "Sean"


def test_build_normalized_data_falls_back_to_a_generic_user_label(hass):
    coordinator = _make_coordinator(hass)
    coordinator._last_user = 2
    elk = _normalized_elk(_area())
    elk.users = MagicMock()
    elk.users.username.return_value = ""
    coordinator._elk = elk
    data = coordinator._build_normalized_data()
    assert data.last_user_name == "User 3"


# --------------------------------------------------------------------------
# _async_update_data error paths
# --------------------------------------------------------------------------


async def test_async_update_data_raises_when_not_connected(hass):
    coordinator = _make_coordinator(hass)
    with pytest.raises(UpdateFailed, match="Not connected"):
        await coordinator._async_update_data()


async def test_async_update_data_raises_update_failed_on_timeout(hass):
    coordinator = _make_coordinator(hass)
    elk = MagicMock()
    elk.is_connected.return_value = True
    coordinator._elk = elk

    from custom_components.elkm1 import coordinator as coordinator_module

    with (
        patch.object(coordinator_module, "POLL_RESPONSE_TIMEOUT", 0.01),
        pytest.raises(UpdateFailed, match="timed out waiting for"),
    ):
        await coordinator._async_update_data()


async def test_async_update_data_raises_update_failed_when_send_fails(hass):
    coordinator = _make_coordinator(hass)
    elk = MagicMock()
    elk.is_connected.return_value = True
    elk.send.side_effect = ConnectionError("disconnected")
    coordinator._elk = elk

    with pytest.raises(UpdateFailed, match="could not be sent"):
        await coordinator._async_update_data()


# --------------------------------------------------------------------------
# Command-guard and simple write-path error branches
# --------------------------------------------------------------------------


async def test_ensure_command_ready_rejects_when_disconnected(hass):
    coordinator = _make_coordinator(hass)
    with pytest.raises(HomeAssistantError) as exc_info:
        coordinator._ensure_command_ready()
    assert exc_info.value.translation_key == "panel_disconnected"


async def test_ensure_command_ready_rejects_while_paused(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.is_connected.return_value = True
    coordinator._elk.is_paused.return_value = True
    with pytest.raises(HomeAssistantError) as exc_info:
        coordinator._ensure_command_ready()
    assert exc_info.value.translation_key == "elkrp_paused"


async def test_async_queue_command_wraps_a_sender_exception(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.is_connected.return_value = True
    coordinator._elk.is_paused.return_value = False

    def _boom():
        raise RuntimeError("boom")

    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.async_queue_command(_boom, "test command")
    assert exc_info.value.translation_key == "queue_command_failed"


async def test_confirm_command_wraps_a_sender_exception(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.is_connected.return_value = True
    coordinator._elk.is_paused.return_value = False

    def _boom():
        raise RuntimeError("boom")

    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.async_confirm_command(_boom, "AS", "test command")
    assert exc_info.value.translation_key == "send_command_failed"


async def test_confirm_command_reraises_a_homeassistant_error_from_the_sender_unwrapped(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.is_connected.return_value = True
    coordinator._elk.is_paused.return_value = False

    def _boom():
        raise HomeAssistantError("already the right kind of error")

    with pytest.raises(HomeAssistantError, match="already the right kind of error"):
        await coordinator.async_confirm_command(_boom, "AS", "test command")


async def test_queue_command_returns_true_on_a_successful_send(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.is_connected.return_value = True
    coordinator._elk.is_paused.return_value = False
    sent = []

    result = await coordinator.async_queue_command(lambda: sent.append(1), "test command")

    assert result is True
    assert sent == [1]


async def test_alarm_trigger_is_rejected_the_protocol_has_no_panic_command(hass):
    coordinator = _make_coordinator(hass)
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.async_alarm_trigger(0)
    assert exc_info.value.translation_key == "panic_not_supported"


async def test_execute_arm_cmd_raises_when_elk_is_unavailable(hass):
    coordinator = _make_coordinator(hass)
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator._execute_arm_cmd(ArmLevel.ARMED_AWAY, 0)
    assert exc_info.value.translation_key == "panel_unavailable"


async def test_execute_arm_cmd_confirms_against_the_real_as_reply(hass):
    """Exercises the real (non-mocked) async_confirm_command/predicate path,
    not just the "already armed" early return."""
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    area.armed_status = ArmedStatus.DISARMED
    elk = MagicMock()
    elk.is_connected.return_value = True
    elk.is_paused.return_value = False
    elk.areas = [area]
    handlers: dict[str, object] = {}
    elk.add_handler.side_effect = lambda command, handler: handlers.update({command: handler})
    elk.remove_handler.side_effect = lambda command, _handler: handlers.pop(command, None)
    coordinator._elk = elk

    def _arm(level, code):
        handlers["AS"](armed_statuses=[ArmedStatus.ARMED_AWAY])

    area.arm.side_effect = _arm

    result = await coordinator._execute_arm_cmd(ArmLevel.ARMED_AWAY, 0, 4321)

    assert result is True
    area.arm.assert_called_once_with(ArmLevel.ARMED_AWAY, 4321)


async def test_execute_arm_cmd_is_a_noop_when_already_at_the_target_level(hass):
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    area.armed_status = ArmedStatus.ARMED_AWAY
    coordinator._elk = MagicMock()
    coordinator._elk.areas = [area]

    result = await coordinator._execute_arm_cmd(ArmLevel.ARMED_AWAY, 0)

    assert result is True
    area.arm.assert_not_called()
    area.disarm.assert_not_called()


async def test_force_arm_away_confirms_against_armed_away_not_the_command_byte(hass):
    """a9 (force arm away) is a send-only command code with no matching AS
    armed-status value; confirmation must wait for the plain ARMED_AWAY status
    the panel actually reports, not for '9' to reappear. See docs/decisions.md
    2026-09-05 (the arm/disarm timeout investigation, once Sean confirmed
    Areas 2-8 have no real zones and only Area 1's violated bench zones were
    blocking a normal arm)."""
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    area.armed_status = ArmedStatus.DISARMED
    elk = MagicMock()
    elk.is_connected.return_value = True
    elk.is_paused.return_value = False
    elk.areas = [area]
    handlers: dict[str, object] = {}
    elk.add_handler.side_effect = lambda command, handler: handlers.update({command: handler})
    elk.remove_handler.side_effect = lambda command, _handler: handlers.pop(command, None)
    coordinator._elk = elk

    def _arm(level, code):
        handlers["AS"](armed_statuses=[ArmedStatus.ARMED_AWAY])

    area.arm.side_effect = _arm

    result = await coordinator.async_alarm_force_arm_away(0, 4321)

    assert result is True
    area.arm.assert_called_once_with(ArmLevel.FORCE_ARM_TO_AWAY_MODE, 4321)


async def test_force_arm_stay_confirms_against_armed_stay(hass):
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    area.armed_status = ArmedStatus.DISARMED
    elk = MagicMock()
    elk.is_connected.return_value = True
    elk.is_paused.return_value = False
    elk.areas = [area]
    handlers: dict[str, object] = {}
    elk.add_handler.side_effect = lambda command, handler: handlers.update({command: handler})
    elk.remove_handler.side_effect = lambda command, _handler: handlers.pop(command, None)
    coordinator._elk = elk

    def _arm(level, code):
        handlers["AS"](armed_statuses=[ArmedStatus.ARMED_STAY])

    area.arm.side_effect = _arm

    result = await coordinator.async_alarm_force_arm_stay(0, 4321)

    assert result is True
    area.arm.assert_called_once_with(ArmLevel.FORCE_ARM_TO_STAY_MODE, 4321)


async def test_execute_arm_cmd_logs_area_snapshot_before_and_after_confirm(hass, caplog):
    """Debug logging is how a production install (which can't run the bench
    script) gets the same before/after area-status detail that script showed
    manually. See docs/decisions.md 2026-09-05."""
    caplog.set_level(logging.DEBUG, logger="custom_components.elkm1.coordinator")
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    area.armed_status = ArmedStatus.DISARMED
    area.alarm_state = AlarmState.NO_ALARM_ACTIVE
    area.arm_up_state = ArmUpState.READY_TO_ARM
    elk = MagicMock()
    elk.is_connected.return_value = True
    elk.is_paused.return_value = False
    elk.areas = [area]
    handlers: dict[str, object] = {}
    elk.add_handler.side_effect = lambda command, handler: handlers.update({command: handler})
    elk.remove_handler.side_effect = lambda command, _handler: handlers.pop(command, None)
    coordinator._elk = elk

    def _arm(level, code):
        handlers["AS"](armed_statuses=[ArmedStatus.ARMED_AWAY])

    area.arm.side_effect = _arm

    await coordinator.async_alarm_arm_away(0, 4321)

    assert "area 1 before ARMED_AWAY" in caplog.text
    assert "area 1 after ARMED_AWAY confirmed" in caplog.text


async def test_execute_arm_cmd_logs_area_snapshot_on_timeout(hass, caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.elkm1.coordinator")
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    area.armed_status = ArmedStatus.DISARMED
    area.alarm_state = AlarmState.NO_ALARM_ACTIVE
    area.arm_up_state = ArmUpState.NOT_READY_TO_ARM
    coordinator._elk = MagicMock()
    coordinator._elk.areas = [area]
    coordinator._elk.add_handler = MagicMock()
    coordinator._elk.remove_handler = MagicMock()

    with (
        patch("custom_components.elkm1.coordinator.COMMAND_RESPONSE_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError),
    ):
        await coordinator.async_alarm_arm_away(0, 4321)

    assert "area 1 after ARMED_AWAY did not confirm" in caplog.text


async def test_bypass_zone_logs_status_before_and_after(hass, caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.elkm1.coordinator")
    coordinator = _make_coordinator(hass)
    zone = MagicMock()
    zone.name = "Front Door"
    zone.logical_status = ZoneLogicalStatus.VIOLATED
    elk = MagicMock()
    elk.is_connected.return_value = True
    elk.is_paused.return_value = False
    elk.zones = [zone]
    handlers: dict[str, object] = {}
    elk.add_handler.side_effect = lambda command, handler: handlers.update({command: handler})
    elk.remove_handler.side_effect = lambda command, _handler: handlers.pop(command, None)
    coordinator._elk = elk

    def _bypass(code):
        handlers["ZB"](zone_number=0, zone_bypassed=True)

    zone.bypass.side_effect = _bypass

    await coordinator.bypass_zone(1, "4321")

    assert "zone 1 (Front Door) before bypass toggle" in caplog.text
    assert "zone 1 (Front Door) after bypass toggle" in caplog.text


async def test_bypass_area_logs_each_previously_violated_zone_afterward(hass, caplog):
    """A confirmed zb999 only means the panel processed the broadcast, not
    that every zone actually bypassed - a zone with bypass disabled (e.g. a
    main entry door) stays VIOLATED. This is the log line that reveals that
    distinction in production. See docs/decisions.md 2026-09-05."""
    caplog.set_level(logging.DEBUG, logger="custom_components.elkm1.coordinator")
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    front_door = MagicMock()
    front_door.index = 0
    front_door.name = "Front Door"
    front_door.area = 0
    front_door.logical_status = ZoneLogicalStatus.VIOLATED
    back_door = MagicMock()
    back_door.index = 1
    back_door.name = "Back Door"
    back_door.area = 0
    back_door.logical_status = ZoneLogicalStatus.VIOLATED
    elk = MagicMock()
    elk.is_connected.return_value = True
    elk.is_paused.return_value = False
    elk.areas = [area]
    elk.zones = [front_door, back_door]
    handlers: dict[str, object] = {}
    elk.add_handler.side_effect = lambda command, handler: handlers.update({command: handler})
    elk.remove_handler.side_effect = lambda command, _handler: handlers.pop(command, None)
    coordinator._elk = elk

    def _bypass(code):
        # Front Door's zone options refuse bypass; only Back Door clears.
        back_door.logical_status = ZoneLogicalStatus.BYPASSED
        handlers["ZB"](zone_number=998)

    area.bypass.side_effect = _bypass

    await coordinator.bypass_area(0, "4321")

    assert "zone 1 (Front Door) logical_status now: 2" in caplog.text
    assert "zone 2 (Back Door) logical_status now: 3" in caplog.text


async def test_alarm_arm_custom_bypass_arms_away(hass):
    coordinator = _make_coordinator(hass)
    area = MagicMock()
    area.armed_status = ArmedStatus.DISARMED
    coordinator._elk = MagicMock()
    coordinator._elk.areas = [area]
    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm_immediately)

    await coordinator.async_alarm_arm_custom_bypass(0, 4321)

    area.arm.assert_called_once_with(ArmLevel.ARMED_AWAY, 4321)


async def test_bypass_zone_raises_when_elk_is_unavailable(hass):
    coordinator = _make_coordinator(hass)
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.bypass_zone(1)
    assert exc_info.value.translation_key == "panel_unavailable"


async def test_trigger_zone_sends_the_zone_trigger(hass):
    coordinator = _make_coordinator(hass)
    zone = MagicMock()
    coordinator._elk = MagicMock()
    coordinator._elk.zones = [zone]
    coordinator.async_queue_command = AsyncMock(side_effect=_confirm_immediately)

    await coordinator.trigger_zone(1)

    zone.trigger.assert_called_once()


async def test_trigger_zone_raises_when_elk_is_unavailable(hass):
    coordinator = _make_coordinator(hass)
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.trigger_zone(1)
    assert exc_info.value.translation_key == "panel_unavailable"


async def test_bypass_area_raises_when_elk_is_unavailable(hass):
    coordinator = _make_coordinator(hass)
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.bypass_area(0)
    assert exc_info.value.translation_key == "panel_unavailable"


async def test_clear_bypass_area_raises_when_elk_is_unavailable(hass):
    coordinator = _make_coordinator(hass)
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.clear_bypass_area(0)
    assert exc_info.value.translation_key == "panel_unavailable"


async def test_display_message_raises_when_elk_is_unavailable(hass):
    coordinator = _make_coordinator(hass)
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.display_message(0)
    assert exc_info.value.translation_key == "panel_unavailable"


async def test_speak_word_sends_the_word(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator.async_queue_command = AsyncMock(side_effect=_confirm_immediately)

    await coordinator.speak_word(42)

    coordinator._elk.panel.speak_word.assert_called_once_with(42)


async def test_speak_word_raises_when_panel_is_unavailable(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.panel = None
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.speak_word(42)
    assert exc_info.value.translation_key == "panel_unavailable"


async def test_speak_phrase_sends_the_phrase(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator.async_queue_command = AsyncMock(side_effect=_confirm_immediately)

    await coordinator.speak_phrase(7)

    coordinator._elk.panel.speak_phrase.assert_called_once_with(7)


async def test_speak_phrase_raises_when_panel_is_unavailable(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.panel = None
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.speak_phrase(7)
    assert exc_info.value.translation_key == "panel_unavailable"


async def test_set_panel_time_sends_the_clock_update(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm_immediately)

    await coordinator.set_panel_time()

    coordinator._elk.panel.set_time.assert_called_once_with(None)


async def test_set_panel_time_raises_when_panel_is_unavailable(hass):
    coordinator = _make_coordinator(hass)
    coordinator._elk = MagicMock()
    coordinator._elk.panel = None
    with pytest.raises(HomeAssistantError) as exc_info:
        await coordinator.set_panel_time()
    assert exc_info.value.translation_key == "panel_unavailable"


# --------------------------------------------------------------------------
# _handle_voice_message (see docs/backlog.md - a known-broken feature;
# these tests pin its *actual* current behavior, not the intended one)
# --------------------------------------------------------------------------


def test_handle_voice_message_ignores_the_real_two_positional_arg_call(hass):
    """Element.add_callback always calls observer(self, self._changeset) -
    two positional args - so args[-1] is the changeset dict, which fails
    the isinstance(words, (list, tuple)) check and returns immediately.
    This is the actual, currently-broken behavior, not the intended one."""
    coordinator = _make_coordinator(hass)
    events = []
    hass.bus.async_listen("elkm1_voice_announcement", lambda event: events.append(event.data))

    coordinator._handle_voice_message(MagicMock(), {"some": "changeset"})

    assert events == []


async def test_handle_voice_message_translates_a_direct_word_list(hass):
    """If ever called with a single list/tuple argument (not the real
    two-positional-arg calling convention above), it does translate and fire."""
    coordinator = _make_coordinator(hass)
    events = []
    hass.bus.async_listen("elkm1_voice_announcement", lambda event: events.append(event.data))

    coordinator._handle_voice_message([471])
    await hass.async_block_till_done()

    assert events == [{"source": "elk_m1", "raw_ids": [471], "message": "zone"}]


def test_handle_voice_message_swallows_a_translation_error(hass):
    coordinator = _make_coordinator(hass)
    events = []
    hass.bus.async_listen("elkm1_voice_announcement", lambda event: events.append(event.data))

    coordinator._handle_voice_message(["not-an-int"])  # int(w) raises ValueError

    assert events == []


async def test_handle_voice_message_translates_a_words_kwarg(hass):
    coordinator = _make_coordinator(hass)
    events = []
    hass.bus.async_listen("elkm1_voice_announcement", lambda event: events.append(event.data))

    coordinator._handle_voice_message(words=[471])
    await hass.async_block_till_done()

    assert events == [{"source": "elk_m1", "raw_ids": [471], "message": "zone"}]


async def test_handle_voice_message_translates_a_changeset_kwarg(hass):
    coordinator = _make_coordinator(hass)
    events = []
    hass.bus.async_listen("elkm1_voice_announcement", lambda event: events.append(event.data))

    coordinator._handle_voice_message(changeset=[471])
    await hass.async_block_till_done()

    assert events == [{"source": "elk_m1", "raw_ids": [471], "message": "zone"}]
