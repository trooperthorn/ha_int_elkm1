"""Models for Elk-M1 integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .coordinator import ElkDataUpdateCoordinator


@dataclass(slots=True)
class ElkRuntimeData:
    """Data class for Elk-M1 runtime data storage in Home Assistant config entries."""

    prefix: str
    mac: str | None
    auto_configure: bool
    config: dict[str, Any]
    coordinator: ElkDataUpdateCoordinator
    connection: Any | None = None


@dataclass(slots=True)
class AreaData:
    """Normalized per-area state.

    Arming fields are numeric protocol values. Alarm state remains its exact
    one-character wire value because valid v1.90 states include ':' through
    'B' and must never be coerced to integers.
    """

    alarm_state: str = "0"
    armed_status: int = 0
    arm_up_state: int = 0
    timer1: int = 0
    timer2: int = 0
    entry_delay_active: bool = False
    exit_delay_active: bool = False
    entry_delay: int = 0
    exit_delay: int = 0
    panic_state: bool = False
    alarm_memory: bool = False


@dataclass(slots=True)
class ElkPanelData:
    """Typed snapshot of Elk-M1 panel state, as built by the coordinator.

    Element lists are references to helpers.elk's live objects, not copies.
    """

    panel_version: str | None = None
    num_areas: int = 1
    areas: dict[int, AreaData] = field(default_factory=dict)
    zones: list[Any] = field(default_factory=list)
    panel: Any = None
    outputs: list[Any] = field(default_factory=list)
    tasks: list[Any] = field(default_factory=list)
    thermostats: list[Any] = field(default_factory=list)
    lights: list[Any] = field(default_factory=list)
    counters: list[Any] = field(default_factory=list)
    settings: list[Any] = field(default_factory=list)
    keypads: list[Any] = field(default_factory=list)
    armed: bool = False
    armed_mode: str = "disarmed"
    last_user: int | None = None
    last_user_name: str = "Unknown"
    last_keypad: int | None = None
    last_user_time: str | None = None
    zones_faulted: list[int] = field(default_factory=list)
    faulted_zone_names: list[str] = field(default_factory=list)
    outputs_active: list[int] = field(default_factory=list)
    active_output_names: list[str] = field(default_factory=list)
    trouble_status: bool = False
    troubles: dict[str, bool] = field(default_factory=dict)
    trouble_details: dict[str, int] = field(default_factory=dict)
    raw_trouble_status: str = ""
    ac_power: bool | None = None
    battery_status: str = "Unknown"
    panel_temperature: float | None = None
    fire_alarm_active: bool = False
    bypassed_zones: list[str] = field(default_factory=list)
