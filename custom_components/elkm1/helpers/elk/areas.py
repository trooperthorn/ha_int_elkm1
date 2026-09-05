"""Area (partition) element and collection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import AlarmState, ArmedStatus, ArmLevel, ArmUpState, ChimeMode, Max, TextDescriptions
from .elements import Element, Elements
from .message import al_encode, as_encode, az_encode, dm_encode, zb_encode
from .notify import Notifier

if TYPE_CHECKING:
    from .connection import Connection


class Area(Element):
    """One area (partition)."""

    def __init__(self, index: int, connection: Connection, notifier: Notifier) -> None:
        super().__init__(index, connection, notifier)
        self.armed_status: ArmedStatus | None = None
        self.arm_up_state: ArmUpState | None = None
        self.alarm_state: AlarmState | None = None
        self.alarm_memory = False
        self.is_exit = False
        self.timer1 = 0
        self.timer2 = 0
        self.last_log: str | None = None
        self.chime_mode = None

    def is_armed(self) -> bool:
        """Whether this area is currently armed at any level."""
        if self.armed_status is None:
            return False
        return self.armed_status != ArmedStatus.DISARMED

    def in_alarm_state(self) -> bool:
        """Whether this area is currently in an active alarm condition."""
        return self.alarm_state not in {
            None,
            AlarmState.NO_ALARM_ACTIVE,
            AlarmState.ENTRANCE_DELAY_ACTIVE,
            AlarmState.ALARM_ABORT_DELAY_ACTIVE,
        }

    def arm(self, level: ArmLevel, code: int) -> None:
        """Arm (or disarm, via ArmLevel.DISARM) this area."""
        if self.is_armed() and level != ArmLevel.DISARM:
            return
        self._connection.send(al_encode(level, self._index, code))

    def disarm(self, code: int) -> None:
        """Disarm this area."""
        self.arm(ArmLevel.DISARM, code)

    def display_message(self, clear: int, beep: bool, timeout: int, line1: str, line2: str) -> None:
        """Display a message on every keypad assigned to this area."""
        self._connection.send(dm_encode(self._index, clear, beep, timeout, line1, line2))

    def bypass(self, code: int) -> None:
        """Bypass every currently-violated zone in this area."""
        self._connection.send(zb_encode(999, self._index, code))

    def clear_bypass(self, code: int) -> None:
        """Clear every zone bypass in this area."""
        self._connection.send(zb_encode(-1, self._index, code))


class Areas(Elements[Area]):
    """All 8 areas."""

    def __init__(self, connection: Connection, notifier: Notifier) -> None:
        super().__init__(connection, notifier, Area, Max.AREAS.value)
        notifier.attach("AM", self._am_handler)
        notifier.attach("AS", self._as_handler)
        notifier.attach("EE", self._ee_handler)
        notifier.attach("KF", self._kf_handler)
        notifier.attach("LD", self._ld_handler)

    def sync(self) -> None:
        """Request current status and names for every area."""
        self._connection.send(as_encode())
        self.get_descriptions(TextDescriptions.AREA.value)

    def _am_handler(self, alarm_memory: list[bool]) -> None:
        for area in self.elements:
            area.setattr("alarm_memory", alarm_memory[area.index], True)

    def _as_handler(
        self,
        armed_statuses: list[ArmedStatus],
        arm_up_states: list[ArmUpState],
        alarm_states: list[AlarmState],
        timer_seconds: int | None = None,
    ) -> None:
        # timer_seconds (the AS reply's M1-4.11+ trailing field) is not
        # tracked per-area here; EE already supplies timer1/timer2 for every
        # area with an active exit/entrance delay. See docs/protocol.md.
        del timer_seconds
        update_alarm_triggers = False
        for area in self.elements:
            area.setattr("armed_status", armed_statuses[area.index], False)
            area.setattr("arm_up_state", arm_up_states[area.index], False)
            if (
                area.alarm_state != alarm_states[area.index]
                or alarm_states[area.index] != AlarmState.NO_ALARM_ACTIVE
            ):
                update_alarm_triggers = True
            area.setattr("alarm_state", alarm_states[area.index], True)

        if update_alarm_triggers:
            self._connection.send(az_encode())

    def _ee_handler(
        self, area: int, is_exit: bool, timer1: int, timer2: int, armed_status: ArmedStatus
    ) -> None:
        area_element = self.elements[area]
        area_element.setattr("armed_status", armed_status, False)
        area_element.setattr("timer1", timer1, False)
        area_element.setattr("timer2", timer2, False)
        area_element.setattr("is_exit", is_exit, True)

    def _ld_handler(self, area: int, log: dict[str, Any]) -> None:
        """G35 (Transmit Event Log) must be enabled for LD messages to be sent."""
        if log["event"] in [1173, 1174]:
            log["user_number"] = log["number"]
        self.elements[area].setattr("last_log", log, True)

    def _kf_handler(self, keypad: int, key: str, chime_mode: list[int]) -> None:
        for area, mode in enumerate(chime_mode):
            try:
                name = ChimeMode(mode).name
            except ValueError:
                name = ""
            self.elements[area].setattr("chime_mode", (name, mode), True)
