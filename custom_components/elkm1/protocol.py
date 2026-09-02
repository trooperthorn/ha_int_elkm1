"""ELK M1 protocol semantics not safely represented by elkm1-lib 2.2.15."""

from __future__ import annotations

from typing import Any

# ELK-M1 RS-232 ASCII Protocol v1.90, section 4.2.13.
ALARM_STATE_NO_ALARM = "0"
ALARM_STATE_ENTRANCE_DELAY = "1"
ALARM_STATE_ABORT_DELAY = "2"
ALARM_STATE_FULL_ALARM = frozenset("3456789:;<=>?@AB")
FIRE_ALARM_STATES = frozenset(("3", "A", "B"))
PANIC_ALARM_STATES = frozenset(("4", "5", "<"))
_NUMERIC_ERRORS = (TypeError, ValueError)

# ELK-M1 RS-232 ASCII Protocol v1.90, section 4.40.3.
FIRE_ZONE_DEFINITIONS = frozenset((10, 11, 12))


def protocol_value(value: Any, default: str = "0") -> str:
    """Return an ELK enum's wire value without unsafe numeric coercion."""
    raw = getattr(value, "value", value)
    if isinstance(raw, str) and len(raw) == 1:
        return raw
    if isinstance(raw, (int, float)):
        return str(int(raw))
    return default


def numeric_value(value: Any, default: int = 0) -> int:
    """Return a numeric ELK enum value, rejecting symbolic protocol values."""
    raw = getattr(value, "value", value)
    try:
        return int(raw)
    except _NUMERIC_ERRORS:
        return default


def alarm_is_active(state: str) -> bool:
    """Return whether an AS alarm state is a documented full alarm."""
    return state in ALARM_STATE_FULL_ALARM


def alarm_is_fire(state: str) -> bool:
    """Return whether an AS alarm state is fire-related."""
    return state in FIRE_ALARM_STATES


def alarm_is_panic(state: str) -> bool:
    """Return whether an AS state represents a human panic category."""
    return state in PANIC_ALARM_STATES
