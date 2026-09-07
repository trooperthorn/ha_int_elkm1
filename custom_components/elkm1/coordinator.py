"""Data update coordinator for Elk-M1 Control integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    ATTR_KEY,
    ATTR_KEY_NAME,
    ATTR_KEYPAD_ID,
    ATTR_KEYPAD_NAME,
    ATTR_USER_NUMBER,
    ATTR_VALID,
    CONF_BAUD_RATE,
    CONF_CONNECTION_TYPE,
    CONF_PIN,
    CONF_SERIAL_PORT,
    COORDINATOR_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_ELKM1_KEYPAD_KEY_PRESSED,
    EVENT_ELKM1_LOG_EVENT,
    EVENT_ELKM1_USER_CODE_ENTERED,
)
from .event_log import describe_elk_event
from .helpers.elk import Elk
from .helpers.elk.const import ArmedStatus, ArmLevel
from .helpers.elk.message import as_encode, az_encode, cs_encode, lw_encode, ss_encode
from .helpers.transport import ElkConnectionManager
from .helpers.troublestatus import (
    normalize_trouble_status,
    parse_trouble_details,
    parse_troubles,
)
from .models import AreaData, ElkPanelData
from .programming import async_get_tracker
from .protocol import (
    FIRE_ZONE_DEFINITIONS,
    alarm_is_fire,
    alarm_is_panic,
    numeric_value,
    protocol_value,
)
from .vocabulary import translate_elk_voice

_LOGGER = logging.getLogger(__name__)

# Ceiling on first-setup wait (a full baud sweep plus backoff), not a retry count.
CONNECT_TIMEOUT = 30.0
COMMAND_RESPONSE_TIMEOUT = 6.0
POLL_RESPONSE_TIMEOUT = 12.0
# Consecutive silent polls before we stop trusting this transport and force a
# fresh open. A stream that never raises (no OSError, no EOF) but also never
# answers leaves _entry_connect's own reconnect loop with nothing to react to;
# see docs/decisions.md.
POLL_TIMEOUT_RECONNECT_THRESHOLD = 2


class ElkDataUpdateCoordinator(DataUpdateCoordinator[ElkPanelData]):
    """Coordinator for Elk-M1 panel state (local_push; `update_interval` is a safety-net poll)."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry_data: dict[str, Any],
        on_baud_detected: Callable[[int], None] | None = None,
        poll_interval: int = COORDINATOR_UPDATE_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Elk-M1 Control",
            update_interval=timedelta(seconds=poll_interval),
        )

        self._config_data = config_entry_data
        self._elk: Elk | None = None
        self._connection_manager: ElkConnectionManager | None = None
        self._connection_type: str = config_entry_data[CONF_CONNECTION_TYPE]
        self._pin: str = str(config_entry_data.get(CONF_PIN, ""))
        self._on_baud_detected = on_baud_detected
        self._url = self._build_connection_url()
        self._raw_trouble_status = ""
        self._keypad_status: dict[int, dict[str, Any]] = {}
        # Populated from IC (Send Valid/Invalid User Code); None until the panel sends one.
        self._last_user: int | None = None
        self._last_keypad: int | None = None
        self._last_user_time: datetime | None = None
        self.last_command_timeout: str | None = None
        # Broadcast counts per message type; panel_settings.py infers the Xmit Changes bits from them.
        self._broadcast_counts: dict[str, int] = dict.fromkeys(
            ("ZC", "CC", "TC", "PC", "KC", "LD"), 0
        )
        self.last_push_update: datetime | None = None
        self.last_poll_success: datetime | None = None
        self._consecutive_poll_timeouts = 0
        self.data = ElkPanelData()

    @property
    def broadcast_counts(self) -> dict[str, int]:
        """Return counts of unsolicited broadcasts seen per message type."""
        return dict(self._broadcast_counts)

    @property
    def connected(self) -> bool:
        """Return True if currently connected to the panel."""
        return self._elk is not None and self._elk.is_connected()

    @property
    def transport_diagnostics(self) -> dict[str, Any]:
        """Return redaction-safe connection lifecycle diagnostics."""
        manager = self._connection_manager
        return {
            "transport": self._connection_type,
            "transport_state": (manager.transport_state if manager is not None else "stopped"),
            "detected_baud": manager.detected_baud if manager is not None else None,
            "login_state": manager.login_state if manager is not None else "unknown",
            "reconnect_count": manager.reconnect_count if manager is not None else 0,
            "last_failure_category": (
                manager.last_failure_category if manager is not None else None
            ),
            "last_push_update": (
                self.last_push_update.isoformat() if self.last_push_update else None
            ),
            "last_poll_success": (
                self.last_poll_success.isoformat() if self.last_poll_success else None
            ),
            "broadcast_counts": self.broadcast_counts,
            "last_command_timeout": self.last_command_timeout,
            "keypad_status": self._keypad_status,
        }

    def _build_connection_url(self) -> str:
        """Build the serial connection URL."""
        serial_port = self._config_data.get(CONF_SERIAL_PORT)
        if not serial_port:
            raise ValueError("Serial port not configured")
        return f"serial://{serial_port}"

    @staticmethod
    def _get_enum_value(obj: Any, default: int = 0) -> int:
        """Safely extract integer value from enum or string objects."""
        return numeric_value(obj, default)

    async def _async_setup(self) -> None:
        """One-time connection setup, run once before the first refresh."""
        elk = Elk({"url": self._url})
        manager = ElkConnectionManager(
            elk,
            cached_baud=self._config_data.get(CONF_BAUD_RATE),
            on_baud_detected=self._on_baud_detected,
        )
        self._connection_manager = manager

        elk.add_handler("EE", self._handle_timer_event)
        elk.add_handler("LD", self._handle_log_event)
        elk.add_handler("IC", self._handle_user_code)
        elk.add_handler("AM", self._handle_alarm_memory)
        elk.add_handler("SS", self._handle_trouble_status)
        elk.add_handler("ZD", self._handle_zone_definitions)
        elk.add_handler("SD", self._handle_description_sync)
        elk.add_handler("PC_ALL", self._handle_all_lights)
        elk.add_handler("KC_DETAIL", self._handle_keypad_detail)
        elk.add_handler("timeout", self._handle_command_timeout)
        elk.add_handler("disconnected", self._handle_disconnected)
        elk.add_handler("RP", self._handle_rp_status)
        elk.add_handler("IE", self._handle_installer_exit)
        for msg_type in self._broadcast_counts:
            elk.add_handler(msg_type, self._count_broadcast(msg_type))
        if elk.panel is not None:
            elk.panel.add_callback(self._handle_voice_message)

        # Wait for "login", not "connected": only login proves the panel replied. See docs/design.md.
        login_succeeded_event = asyncio.Event()
        login_failed_event = asyncio.Event()

        def _on_login(succeeded: bool) -> None:
            manager.mark_login(succeeded)
            if succeeded:
                login_succeeded_event.set()
                if self._elk is not None and self._elk.is_connected():
                    # log-when-unavailable (quality_scale.yaml): async_set_update_error
                    # already logs the initial "unavailable" transition once; this is
                    # the matching one-time "recovered" log for the push-driven login
                    # path, since only DataUpdateCoordinator's own poll path
                    # (_async_refresh) logs recovery for us automatically.
                    if not self.last_update_success:
                        _LOGGER.info("Elk-M1 connection recovered")
                    self.async_set_updated_data(self._build_normalized_data())
            else:
                login_failed_event.set()

        elk.add_handler("login", _on_login)

        self._elk = elk
        manager.start()

        succeeded_task = asyncio.create_task(
            login_succeeded_event.wait(), name="elkm1-login-success"
        )
        failed_task = asyncio.create_task(login_failed_event.wait(), name="elkm1-login-failure")
        try:
            done, _pending = await asyncio.wait(
                (succeeded_task, failed_task),
                timeout=CONNECT_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except BaseException:
            await manager.async_stop()
            self._elk = None
            raise
        finally:
            for task in (succeeded_task, failed_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(succeeded_task, failed_task, return_exceptions=True)

        if failed_task in done:
            await manager.async_stop()
            self._elk = None
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            )

        if succeeded_task not in done:
            await manager.async_stop()
            self._elk = None
            raise UpdateFailed(f"Timed out connecting to Elk-M1 at {self._url}")

        self._register_push_callbacks()

    def _register_push_callbacks(self) -> None:
        """Push a fresh snapshot whenever any tracked element changes state."""
        assert self._elk is not None

        def _on_change(_element: Any, _changeset: dict[str, Any]) -> None:
            self.async_set_updated_data(self._build_normalized_data())

        for collection_name in (
            "areas",
            "zones",
            "outputs",
            "tasks",
            "thermostats",
            "lights",
            "counters",
            "settings",
        ):
            for element in getattr(self._elk, collection_name):
                element.add_callback(_on_change)

        for keypad in self._elk.keypads:
            keypad.add_callback(_on_change)
            keypad.add_callback(self._handle_keypad_change)

    def _handle_keypad_change(self, keypad: Any, changeset: dict[str, Any]) -> None:
        """Fire an HA event when a keypad key is pressed (for automations)."""
        if "last_keypress" not in changeset:
            return
        keypress = changeset["last_keypress"]
        if not keypress:
            return
        key_name, key = keypress
        event_data: dict[str, Any] = {
            ATTR_KEYPAD_ID: keypad.index + 1,
            ATTR_KEYPAD_NAME: keypad.name,
            ATTR_KEY: key,
            ATTR_KEY_NAME: key_name,
        }
        event_data.update(self._keypad_status.get(keypad.index, {}))
        self.hass.bus.async_fire(
            EVENT_ELKM1_KEYPAD_KEY_PRESSED,
            event_data,
        )

    def _handle_user_code(self, code: str, user: int, keypad: int) -> None:
        """Track the panel's IC (user code) report for the alarm entity's changed_by.

        `user` is 0-indexed and negative when the panel reports an invalid code
        (see helpers/elk/message.py's ic_decode); a negative value clears attribution
        rather than attaching an event to the wrong user. Fires promptly so
        automations (Alarmo sync included) see who armed/disarmed with no poll delay.
        """
        valid = user >= 0
        self._last_user = user if valid else None
        self._last_keypad = keypad
        self._last_user_time = datetime.now(UTC)
        self.hass.bus.async_fire(
            EVENT_ELKM1_USER_CODE_ENTERED,
            {
                ATTR_KEYPAD_ID: keypad + 1,
                ATTR_USER_NUMBER: (user + 1) if valid else None,
                ATTR_VALID: valid,
            },
        )
        self.async_set_updated_data(self._build_normalized_data())

    def _handle_keypad_detail(
        self,
        keypad: int,
        key: int,
        function_key_lights: tuple[int, ...],
        bypass_requires_code: bool,
        beep_chime_by_area: tuple[int, ...],
    ) -> None:
        """Preserve the complete v1.90 KC status fields (function-key lights,
        bypass-requires-code, beep/chime by area) alongside the plain KC
        keypad/key event - see helpers/elk/message.py's kc_detail_decode."""
        self._keypad_status[keypad] = {
            "function_key_lights": list(function_key_lights),
            "bypass_requires_code": bypass_requires_code,
            "beep_chime_by_area": list(beep_chime_by_area),
        }

    def _handle_all_lights(self, house_index: int, aggregate_code: int) -> None:
        """Apply a PC house/unit 00 aggregate update to all 16 house units."""
        if self._elk is None:
            return
        if aggregate_code not in (1, 2, 7):
            _LOGGER.warning("Ignoring unknown ELK all-lights code %s", aggregate_code)
            return
        light_level = 1 if aggregate_code == 2 else 0
        start = house_index * 16
        for light_index in range(start, start + 16):
            light = self._elk.lights[light_index]
            light.setattr("status", light_level, True)

    def _handle_command_timeout(self, msg_code: str | None) -> None:
        """Expose library-level command timeouts in transport diagnostics."""
        self.last_command_timeout = msg_code

    def _count_broadcast(self, msg_type: str) -> Callable[..., None]:
        """Return a handler that increments this message type's seen-count."""

        def _handler(**_kwargs: Any) -> None:
            self._broadcast_counts[msg_type] += 1
            self.last_push_update = datetime.now(UTC)

        return _handler

    def _handle_disconnected(self, **_kwargs: Any) -> None:
        """Mark entities unavailable while the entry-owned task reconnects."""
        if self._connection_manager is not None:
            self._connection_manager.mark_disconnected()
        self._consecutive_poll_timeouts = 0
        self.async_set_update_error(UpdateFailed("ELK-M1 transport disconnected"))

    def _handle_timer_event(
        self, area: int, is_exit: bool, timer1: int, timer2: int, armed_status: Any
    ) -> None:
        """Fire an HA event for entry/exit timer updates (used by automations)."""
        self.hass.bus.async_fire(
            "elkm1_timer_event",
            {
                "area": area + 1,
                "type": "exit" if is_exit else "entry",
                "timer1": timer1,
                "timer2": timer2,
                "armed_status": self._get_enum_value(armed_status),
            },
        )

    def _handle_log_event(self, area: int, log: dict[str, Any]) -> None:
        """Fire an HA event for a new system log (LD) entry.

        `log["event"]` is the panel's raw numeric event code (see
        helpers/elk/message.py's ld_decode); event_log.py translates it to
        the description Elk's own ElkRP tool shows, since the code alone
        (e.g. 4176) isn't meaningful to a user. Only sent when G35
        (Transmit Event Log) is enabled - see docs/protocol.md.
        """
        self.hass.bus.async_fire(
            EVENT_ELKM1_LOG_EVENT,
            {
                "area": area + 1,
                "event": log["event"],
                "description": describe_elk_event(log["event"]),
                "number": log["number"],
                "index": log["index"],
                "timestamp": log["timestamp"],
            },
        )

    def _handle_rp_status(self, remote_programming_status: Any) -> None:
        """Feed the panel's own RP (remote programming) status to the session tracker.

        The panel cannot say who is programming it; programming.py matches this
        against the claim the Elk Programmer app announced, or records the
        session as unattributed and raises a Repair issue.
        """
        connected = self._get_enum_value(remote_programming_status) != 0
        if self.config_entry is not None:
            async_get_tracker(self.hass).async_rp_status(self.config_entry.entry_id, connected)
        self.async_set_updated_data(self._build_normalized_data())

    def _handle_installer_exit(self) -> None:
        """IE: programming ended, from a keypad or a remote session; the hub resyncs."""
        if self.config_entry is not None:
            async_get_tracker(self.hass).async_rp_status(self.config_entry.entry_id, False)

    def _handle_alarm_memory(self, alarm_memory: list[bool]) -> None:
        """Fire an HA event when alarm memory changes."""
        self.hass.bus.async_fire(
            "elkm1_alarm_memory",
            {"areas": [i + 1 for i, flagged in enumerate(alarm_memory) if flagged]},
        )

    def _handle_zone_definitions(self, zone_definitions: list[Any]) -> None:
        """Request voltage (zv) for analog zones once definitions are known."""
        if not self._elk:
            return
        for zone_index, definition in enumerate(zone_definitions):
            if self._get_enum_value(definition) == 34:
                cast(Any, self._elk.zones[zone_index]).get_voltage()

    def _handle_description_sync(
        self, desc_type: int, unit: int, desc: str, show_on_keypad: bool
    ) -> None:
        """Notify listeners as each element's panel-assigned name arrives."""
        self.async_update_listeners()

    def _handle_trouble_status(self, system_trouble_status: str) -> None:
        """Store the raw SS trouble string and push an updated snapshot."""
        self._raw_trouble_status = normalize_trouble_status(system_trouble_status)
        self.async_set_updated_data(self._build_normalized_data())

    async def async_disconnect(self) -> None:
        """Disconnect from ELK-M1 panel."""
        manager = self._connection_manager
        self._connection_manager = None
        if manager is not None:
            try:
                await manager.async_stop()
                _LOGGER.info("Disconnected from ELK-M1")
            except (OSError, AttributeError) as err:
                _LOGGER.error("Error disconnecting: %s", err)
            finally:
                self._elk = None

    def _build_normalized_data(self) -> ElkPanelData:
        """Convert underlying library objects into a typed state snapshot."""
        if not self._elk:
            return self.data

        zones = list(self._elk.zones)
        panel = self._elk.panel
        areas = list(self._elk.areas)
        outputs = list(self._elk.outputs)
        tasks = list(self._elk.tasks)
        thermostats = list(self._elk.thermostats)
        lights = list(self._elk.lights)
        counters = list(self._elk.counters)
        settings = list(self._elk.settings)
        keypads = list(self._elk.keypads)

        configured_areas = [a for a in areas if a.configured] or areas[:1]
        num_areas = max(len(configured_areas), 1)

        areas_dict: dict[int, AreaData] = {}
        for area in configured_areas:
            t1 = getattr(area, "timer1", 0)
            t2 = getattr(area, "timer2", 0)
            is_exit = bool(getattr(area, "is_exit", False))
            armed_val = self._get_enum_value(area.armed_status)  # type: ignore[attr-defined]
            alarm_state = protocol_value(area.alarm_state)  # type: ignore[attr-defined]
            areas_dict[area.index] = AreaData(
                alarm_state=alarm_state,
                armed_status=armed_val,
                arm_up_state=self._get_enum_value(area.arm_up_state),  # type: ignore[attr-defined]
                timer1=t1,
                timer2=t2,
                entry_delay_active=not is_exit and (t1 > 0 or t2 > 0),
                exit_delay_active=is_exit and (t1 > 0 or t2 > 0),
                entry_delay=max(t1, t2) if not is_exit else 0,
                exit_delay=max(t1, t2) if is_exit else 0,
                panic_state=alarm_is_panic(alarm_state),
                alarm_memory=getattr(area, "alarm_memory", False),
            )

        faulted_indices: list[int] = []
        faulted_names: list[str] = []
        bypassed_names: list[str] = []
        fire_alarm = any(alarm_is_fire(area.alarm_state) for area in areas_dict.values())

        for zone in zones:
            if not zone.configured:
                continue
            logical = self._get_enum_value(zone.logical_status)  # type: ignore[attr-defined]
            definition = self._get_enum_value(zone.definition)  # type: ignore[attr-defined]

            # ZoneLogicalStatus: 0=normal, 1=trouble, 2=violated, 3=bypassed.
            if logical == 2:
                faulted_indices.append(zone.index)
                faulted_names.append(f"Zone {zone.index + 1}: {zone.name}")
            if logical == 3:
                bypassed_names.append(f"Zone {zone.index + 1}: {zone.name}")
            if definition in FIRE_ZONE_DEFINITIONS and bool(
                getattr(zone, "triggered_alarm", False)
            ):
                fire_alarm = True

        active_outputs: list[int] = []
        active_output_names: list[str] = []
        for output in outputs:
            if output.configured and output.output_on:  # type: ignore[attr-defined]
                active_outputs.append(output.index)
                active_output_names.append(f"Output {output.index + 1}: {output.name}")

        panel_temp = None
        for zone in zones:
            if zone.configured and zone.temperature > -60:  # type: ignore[attr-defined]
                panel_temp = zone.temperature  # type: ignore[attr-defined]
                break

        is_any_armed = any(a.armed_status != 0 for a in areas_dict.values())
        troubles = parse_troubles(self._raw_trouble_status)
        trouble_details = parse_trouble_details(self._raw_trouble_status)
        trouble_known = bool(self._raw_trouble_status)

        last_user_name = "Unknown"
        if self._last_user is not None:
            # elk.users syncs via "sd" (TextDescriptions.USER) on every connect/resync;
            # username() returns "" if that name was never programmed on the panel.
            resolved = self._elk.users.username(self._last_user) if self._elk else ""
            last_user_name = resolved or f"User {self._last_user + 1}"

        return ElkPanelData(
            panel_version=getattr(panel, "elkm1_version", None),
            num_areas=num_areas,
            areas=areas_dict,
            zones=zones,
            panel=panel,
            outputs=outputs,
            tasks=tasks,
            thermostats=thermostats,
            lights=lights,
            counters=counters,
            settings=settings,
            keypads=keypads,
            armed=is_any_armed,
            armed_mode="armed" if is_any_armed else "disarmed",
            last_user=self._last_user,
            last_user_name=last_user_name,
            last_keypad=self._last_keypad,
            last_user_time=(
                self._last_user_time.isoformat() if self._last_user_time else None
            ),
            zones_faulted=faulted_indices,
            faulted_zone_names=faulted_names,
            outputs_active=active_outputs,
            active_output_names=active_output_names,
            trouble_status=any(troubles.values()),
            troubles=troubles,
            trouble_details=trouble_details,
            raw_trouble_status=self._raw_trouble_status,
            ac_power=(not troubles.get("ac_fail", False)) if trouble_known else None,
            battery_status=(
                "Low"
                if trouble_known and troubles.get("low_battery", False)
                else "Good"
                if trouble_known
                else "Unknown"
            ),
            panel_temperature=panel_temp,
            fire_alarm_active=fire_alarm,
            bypassed_zones=bypassed_names,
        )

    async def _async_update_data(self) -> ElkPanelData:
        """Request a protocol-safe status refresh; push remains the primary path."""
        if self.config_entry is not None:
            async_get_tracker(self.hass).async_check_claim(self.config_entry.entry_id)
        if not self._elk or not self._elk.is_connected():
            raise UpdateFailed("Not connected to Elk-M1")

        expected = {"AS", "AZ", "CS", "SS", "LW"}
        received: set[str] = set()
        refreshed = asyncio.Event()
        handlers: dict[str, Callable[..., None]] = {}

        for command in expected:

            def _mark_received(_command: str = command, **_payload: Any) -> None:
                received.add(_command)
                if received == expected:
                    refreshed.set()

            handlers[command] = _mark_received
            self._elk.add_handler(command, _mark_received)

        try:
            for message in (as_encode(), az_encode(), cs_encode(), ss_encode(), lw_encode()):
                self._elk.send(message)
            async with asyncio.timeout(POLL_RESPONSE_TIMEOUT):
                await refreshed.wait()
        except TimeoutError as err:
            missing = ", ".join(sorted(expected - received))
            self._consecutive_poll_timeouts += 1
            if self._consecutive_poll_timeouts >= POLL_TIMEOUT_RECONNECT_THRESHOLD:
                self._consecutive_poll_timeouts = 0
                _LOGGER.warning(
                    "ELK-M1 answered nothing for %d consecutive polls; "
                    "forcing the transport closed and reopening it",
                    POLL_TIMEOUT_RECONNECT_THRESHOLD,
                )
                await self._force_reconnect()
            raise UpdateFailed(f"ELK-M1 status refresh timed out waiting for: {missing}") from err
        except (ConnectionError, OSError) as err:
            raise UpdateFailed(f"ELK-M1 status refresh could not be sent: {err}") from err
        finally:
            for command, handler in handlers.items():
                self._elk.remove_handler(command, handler)

        self._consecutive_poll_timeouts = 0
        self.last_poll_success = datetime.now(UTC)
        return self._build_normalized_data()

    async def _force_reconnect(self) -> None:
        """Close and reopen the transport after it stops answering silently.

        A dead USB-serial adapter or an unresponsive panel doesn't always
        raise on write/read - the stream tasks stay alive with nothing to
        react to, so _entry_connect's own backoff-and-retry loop never
        triggers on its own. See docs/decisions.md.
        """
        manager = self._connection_manager
        if manager is None:
            return
        await manager.async_stop()
        manager.start()

    def _ensure_command_ready(self) -> None:
        """Reject writes that cannot currently reach the panel."""
        if self._elk is None or not self._elk.is_connected():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_disconnected"
            )
        if self._elk.is_paused():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="elkrp_paused"
            )

    async def async_queue_command(self, sender: Callable[[], None], description: str) -> bool:
        """Queue a command for which the ELK protocol defines no acknowledgement."""
        self._ensure_command_ready()
        try:
            sender()
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="queue_command_failed",
                translation_placeholders={"description": description, "error": str(err)},
            ) from err
        await asyncio.sleep(0)
        return True

    async def async_confirm_command(
        self,
        sender: Callable[[], None],
        response_command: str,
        description: str,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> bool:
        """Send a request and require its documented, validated response."""
        self._ensure_command_ready()
        assert self._elk is not None
        response = asyncio.Event()

        def _response_handler(**payload: Any) -> None:
            if predicate is None or predicate(payload):
                response.set()

        self._elk.add_handler(response_command, _response_handler)
        _LOGGER.debug("Sending %s, awaiting a matching %s reply", description, response_command)
        try:
            sender()
            async with asyncio.timeout(COMMAND_RESPONSE_TIMEOUT):
                await response.wait()
        except TimeoutError as err:
            self.last_command_timeout = response_command
            _LOGGER.debug(
                "%s did not confirm within %.1fs (no matching %s reply)",
                description,
                COMMAND_RESPONSE_TIMEOUT,
                response_command,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_not_confirmed",
                translation_placeholders={
                    "description": description,
                    "response_command": response_command,
                },
            ) from err
        except HomeAssistantError:
            raise
        except Exception as err:
            _LOGGER.debug("%s failed to send: %s", description, err)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="send_command_failed",
                translation_placeholders={"description": description, "error": str(err)},
            ) from err
        finally:
            self._elk.remove_handler(response_command, _response_handler)
        self.last_command_timeout = None
        _LOGGER.debug("Confirmed %s", description)
        return True

    async def async_alarm_disarm(self, area_index: int, code: int = 0) -> bool:
        """Send disarm command for specific area."""
        return await self._execute_arm_cmd(ArmLevel.DISARM, area_index, code)

    async def async_alarm_arm_away(self, area_index: int, code: int = 0) -> bool:
        """Send arm away command for specific area."""
        return await self._execute_arm_cmd(ArmLevel.ARMED_AWAY, area_index, code)

    async def async_alarm_arm_home(self, area_index: int, code: int = 0) -> bool:
        """Send arm stay command for specific area."""
        return await self._execute_arm_cmd(ArmLevel.ARMED_STAY, area_index, code)

    async def async_alarm_arm_night(self, area_index: int, code: int = 0) -> bool:
        """Send arm night command for specific area."""
        return await self._execute_arm_cmd(ArmLevel.ARMED_NIGHT, area_index, code)

    async def async_alarm_arm_vacation(self, area_index: int, code: int = 0) -> bool:
        """Send arm vacation command for specific area."""
        return await self._execute_arm_cmd(ArmLevel.ARMED_VACATION, area_index, code)

    async def async_alarm_arm_home_instant(self, area_index: int, code: int = 0) -> bool:
        """Send arm stay-instant command for specific area (no entry delay)."""
        return await self._execute_arm_cmd(ArmLevel.ARMED_STAY_INSTANT, area_index, code)

    async def async_alarm_arm_night_instant(self, area_index: int, code: int = 0) -> bool:
        """Send arm night-instant command for specific area (no entry delay)."""
        return await self._execute_arm_cmd(ArmLevel.ARMED_NIGHT_INSTANT, area_index, code)

    async def async_alarm_arm_custom_bypass(self, area_index: int, code: int = 0) -> bool:
        """Send arm-away command for specific area (custom bypass = arm-away)."""
        return await self._execute_arm_cmd(ArmLevel.ARMED_AWAY, area_index, code)

    async def async_alarm_force_arm_away(self, area_index: int, code: int = 0) -> bool:
        """Force arm-away, overriding a violated zone (a9, M1 5.3.0+)."""
        return await self._execute_arm_cmd(ArmLevel.FORCE_ARM_TO_AWAY_MODE, area_index, code)

    async def async_alarm_force_arm_stay(self, area_index: int, code: int = 0) -> bool:
        """Force arm-stay, overriding a violated zone (a:, M1 5.3.0+)."""
        return await self._execute_arm_cmd(ArmLevel.FORCE_ARM_TO_STAY_MODE, area_index, code)

    async def async_alarm_trigger(self, area_index: int, code: int = 0) -> bool:
        """Reject panic control, which the third-party protocol does not provide."""
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="panic_not_supported"
        )

    # a9/a: (force arm) are send-only command codes with no matching entry in
    # the AS reply's armed-status field; the panel reports a plain arm result
    # instead (see docs/protocol.md). Confirmation must wait for that, not for
    # the command byte itself to reappear.
    _FORCE_ARM_CONFIRMS_AS: ClassVar[dict[ArmLevel, str]] = {
        ArmLevel.FORCE_ARM_TO_AWAY_MODE: ArmedStatus.ARMED_AWAY.value,
        ArmLevel.FORCE_ARM_TO_STAY_MODE: ArmedStatus.ARMED_STAY.value,
    }

    def _log_area_snapshot(self, area_index: int, area: Any, when: str) -> None:
        """Debug-log an area's live status - the same fields the bench
        verification script logged manually before this was folded into the
        integration itself. See docs/decisions.md 2026-09-05."""
        _LOGGER.debug(
            "area %d %s: alarm_state=%s armed_status=%s arm_up_state=%s",
            area_index + 1,
            when,
            protocol_value(area.alarm_state),
            protocol_value(area.armed_status),
            self._get_enum_value(area.arm_up_state),
        )

    async def _execute_arm_cmd(self, level: ArmLevel, area_index: int, code: int = 0) -> bool:
        """Arm/disarm an area using helpers/elk's own checksummed Area helpers."""
        if not self._elk:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_unavailable"
            )
        active_pin = code if code > 0 else int(self._pin or 0)
        area = cast(Any, self._elk.areas[area_index])
        expected = self._FORCE_ARM_CONFIRMS_AS.get(level, level.value)

        self._log_area_snapshot(area_index, area, f"before {level.name}")
        if protocol_value(area.armed_status) == expected:
            _LOGGER.debug(
                "area %d already at %s - no command sent", area_index + 1, level.name
            )
            return True

        def _matches(payload: dict[str, Any]) -> bool:
            statuses = payload.get("armed_statuses", [])
            return area_index < len(statuses) and protocol_value(statuses[area_index]) == expected

        def sender() -> None:
            if level == ArmLevel.DISARM:
                area.disarm(active_pin)
            else:
                area.arm(level, active_pin)

        try:
            result = await self.async_confirm_command(
                sender, "AS", f"arm/disarm command ({level.name})", _matches
            )
        except HomeAssistantError:
            self._log_area_snapshot(area_index, area, f"after {level.name} did not confirm")
            raise
        self._log_area_snapshot(area_index, area, f"after {level.name} confirmed")
        return result

    async def bypass_zone(self, zone_number: int, pin_code: str | None = None) -> bool:
        """Bypass a zone (1-indexed, matching the panel's own numbering)."""
        if not self._elk:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_unavailable"
            )
        active_pin = int(pin_code) if pin_code else int(self._pin or 0)
        zone_index = zone_number - 1
        zone = cast(Any, self._elk.zones[zone_index])
        expected_bypassed = self._get_enum_value(zone.logical_status) != 3
        _LOGGER.debug(
            "zone %d (%s) before bypass toggle: logical_status=%s",
            zone_number,
            getattr(zone, "name", "?"),
            self._get_enum_value(zone.logical_status),
        )
        result = await self.async_confirm_command(
            lambda: zone.bypass(active_pin),
            "ZB",
            f"zone {zone_number} bypass toggle",
            lambda payload: (
                payload.get("zone_number") == zone_index
                and payload.get("zone_bypassed") is expected_bypassed
            ),
        )
        _LOGGER.debug(
            "zone %d (%s) after bypass toggle: logical_status=%s",
            zone_number,
            getattr(zone, "name", "?"),
            self._get_enum_value(zone.logical_status),
        )
        return result

    async def unbypass_zone(self, zone_number: int, pin_code: str | None = None) -> bool:
        """Clear a zone's bypass by re-sending the toggle-only `zb` command."""
        return await self.bypass_zone(zone_number, pin_code)

    async def trigger_zone(self, zone_number: int) -> bool:
        """Trigger a zone; the protocol defines no direct acknowledgement."""
        if not self._elk:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_unavailable"
            )
        zone = cast(Any, self._elk.zones[zone_number - 1])
        return await self.async_queue_command(
            zone.trigger, f"zone {zone_number} trigger (unconfirmed)"
        )

    async def bypass_area(self, area_index: int, pin_code: str | None = None) -> bool:
        """Bypass all violated burglar zones in an area with ``zb999``.

        A confirmed ``True`` only means the panel processed the ``zb999``
        broadcast, not that every violated zone actually became bypassed - a
        zone with bypass disabled in its own zone options (e.g. a main
        entry/exit door, by design) stays violated regardless. The per-zone
        debug log below is how that distinction shows up. See
        docs/decisions.md 2026-09-05.
        """
        if not self._elk:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_unavailable"
            )
        active_pin = int(pin_code) if pin_code else int(self._pin or 0)
        area = cast(Any, self._elk.areas[area_index])
        violated_zones = [
            zone
            for zone in cast(Any, self._elk.zones)
            if getattr(zone, "area", -1) == area_index
            and self._get_enum_value(zone.logical_status) == 2
        ]
        result = await self.async_confirm_command(
            lambda: area.bypass(active_pin),
            "ZB",
            f"area {area_index + 1} bypass",
            lambda payload: payload.get("zone_number") == 998,
        )
        for zone in violated_zones:
            _LOGGER.debug(
                "  zone %d (%s) logical_status now: %s",
                zone.index + 1,
                getattr(zone, "name", "?"),
                self._get_enum_value(zone.logical_status),
            )
        return result

    async def clear_bypass_area(self, area_index: int, pin_code: str | None = None) -> bool:
        """Clear all burglar-zone bypasses in an area with ``zb000``."""
        if not self._elk:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_unavailable"
            )
        active_pin = int(pin_code) if pin_code else int(self._pin or 0)
        area = cast(Any, self._elk.areas[area_index])
        return await self.async_confirm_command(
            lambda: area.clear_bypass(active_pin),
            "ZB",
            f"area {area_index + 1} clear bypass",
            lambda payload: payload.get("zone_number") == -1,
        )

    async def display_message(
        self,
        area_index: int = 0,
        line1: str = "",
        line2: str = "",
        beep: bool = False,
        clear: int = 1,
        timeout: int = 0,
    ) -> bool:
        """Display a message on all keypads in an area via Area.display_message().

        clear defaults to 1 ("clear message with * key"), not the protocol
        doc's own first-listed value 0: live-tested against a real panel, 0
        and 2 both showed nothing on the keypad and only 1 displayed the
        message. See docs/live_qualification.md.
        """
        if not self._elk:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_unavailable"
            )
        area = cast(Any, self._elk.areas[area_index])
        return await self.async_queue_command(
            lambda: area.display_message(clear, beep, timeout, line1, line2),
            "keypad display message",
        )

    async def speak_word(self, word: int) -> bool:
        """Speak a single word from the panel's voice vocabulary."""
        if not self._elk or self._elk.panel is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_unavailable"
            )
        panel = self._elk.panel
        return await self.async_queue_command(lambda: panel.speak_word(word), "speak word")

    async def speak_phrase(self, phrase: int) -> bool:
        """Speak a phrase from the panel's voice vocabulary."""
        if not self._elk or self._elk.panel is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_unavailable"
            )
        panel = self._elk.panel
        return await self.async_queue_command(lambda: panel.speak_phrase(phrase), "speak phrase")

    async def set_panel_time(self, when: datetime | None = None) -> bool:
        """Write the panel's real-time clock (defaults to the current time)."""
        if not self._elk or self._elk.panel is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="panel_unavailable"
            )
        panel = self._elk.panel
        return await self.async_confirm_command(lambda: panel.set_time(when), "RR", "clock update")

    def _handle_voice_message(self, *args: Any, **kwargs: Any) -> None:
        """Process incoming voice command arrays and fire a Home Assistant event."""
        try:
            words = None
            if args:
                words = args[0] if len(args) == 1 else args[-1]
            elif "words" in kwargs:
                words = kwargs["words"]
            elif "changeset" in kwargs:
                words = kwargs["changeset"]

            if not isinstance(words, (list, tuple)):
                return

            word_ints = [int(w) for w in words]
            readable_message = translate_elk_voice(word_ints)

            if readable_message:
                _LOGGER.info(
                    "Elk-M1 Voice Translated: '%s' (Raw IDs: %s)",
                    readable_message,
                    word_ints,
                )
                self.hass.bus.async_fire(
                    "elkm1_voice_announcement",
                    {
                        "source": "elk_m1",
                        "raw_ids": word_ints,
                        "message": readable_message,
                    },
                )
        except Exception:
            _LOGGER.exception("Failed to translate and fire Elk voice message")
