"""Enums and sizing constants for the ELK-M1 RS-232 ASCII protocol.

Ported from the (now removed) `elkm1-lib` dependency, verified against
`ELK-M1_RS232_PROTOCOL.Ver+1.90.pdf` and, where noted in docs/protocol.md,
against real hardware. See docs/decisions.md for why this repo owns the
protocol implementation directly instead of depending on elkm1-lib.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class Max(Enum):
    """Max number of elements the panel can report per collection."""

    AREAS = 8
    COUNTERS = 64
    KEYPADS = 16
    OUTPUTS = 208
    SETTINGS = 20
    TASKS = 32
    THERMOSTATS = 16  # noqa: PIE796 - genuinely shares KEYPADS' hardware max, not an accident
    USERS = 203
    LIGHTS = 256
    ZONES = 208  # noqa: PIE796 - genuinely shares OUTPUTS' hardware max, not an accident
    ZONE_TEMPS = 16  # noqa: PIE796 - genuinely shares KEYPADS' hardware max, not an accident


class ZoneType(Enum):
    """Zone definition values (what a zone means to the panel's arming logic)."""

    DISABLED = 0
    BURGLAR_ENTRY_EXIT_1 = 1
    BURGLAR_ENTRY_EXIT_2 = 2
    BURGLAR_PERIMETER_INSTANT = 3
    BURGLAR_INTERIOR = 4
    BURGLAR_INTERIOR_FOLLOWER = 5
    BURGLAR_INTERIOR_NIGHT = 6
    BURGLAR_INTERIOR_NIGHT_DELAY = 7
    BURGLAR24_HOUR = 8
    BURGLAR_BOX_TAMPER = 9
    FIRE_ALARM = 10
    FIRE_VERIFIED = 11
    FIRE_SUPERVISORY = 12
    AUX_ALARM_1 = 13
    AUX_ALARM_2 = 14
    KEYFOB = 15
    NON_ALARM = 16
    CARBON_MONOXIDE = 17
    EMERGENCY_ALARM = 18
    FREEZE_ALARM = 19
    GAS_ALARM = 20
    HEAT_ALARM = 21
    MEDICAL_ALARM = 22
    POLICE_ALARM = 23
    POLICE_NO_INDICATION = 24
    WATER_ALARM = 25
    KEY_MOMENTARY_ARM_DISARM = 26
    KEY_MOMENTARY_ARM_AWAY = 27
    KEY_MOMENTARY_ARM_STAY = 28
    KEY_MOMENTARY_DISARM = 29
    KEY_ON_OFF = 30
    MUTE_AUDIBLES = 31
    POWER_SUPERVISORY = 32
    TEMPERATURE = 33
    ANALOG_ZONE = 34
    PHONE_KEY = 35
    INTERCOM_KEY = 36


class ZonePhysicalStatus(Enum):
    """Zone physical (electrical loop) status."""

    UNCONFIGURED = 0
    OPEN = 1
    EOL = 2
    SHORT = 3


class ZoneLogicalStatus(Enum):
    """Zone logical status, as reported by ZS/ZC."""

    NORMAL = 0
    TROUBLED = 1
    VIOLATED = 2
    BYPASSED = 3


class ArmedStatus(Enum):
    """AS reply: area armed status."""

    DISARMED = "0"
    ARMED_AWAY = "1"
    ARMED_STAY = "2"
    ARMED_STAY_INSTANT = "3"
    ARMED_TO_NIGHT = "4"
    ARMED_TO_NIGHT_INSTANT = "5"
    ARMED_TO_VACATION = "6"


class ArmUpState(Enum):
    """AS reply: area arm-up state (readiness/exit-timer/force-arm status)."""

    NOT_READY_TO_ARM = "0"
    READY_TO_ARM = "1"
    CAN_BE_FORCE_ARMED = "2"
    ARMED_AND_EXIT_TIMER_RUNNING = "3"
    FULLY_ARMED = "4"
    FORCE_ARMED = "5"
    ARMED_WITH_BYPASS = "6"


class AlarmState(Enum):
    """AS reply: area alarm state (section 4.2.13 alarm-type table)."""

    NO_ALARM_ACTIVE = "0"
    ENTRANCE_DELAY_ACTIVE = "1"
    ALARM_ABORT_DELAY_ACTIVE = "2"
    FIRE_ALARM = "3"
    MEDICAL_ALARM = "4"
    POLICE_ALARM = "5"
    BURGLAR_ALARM = "6"
    AUX_1_ALARM = "7"
    AUX_2_ALARM = "8"
    AUX_3_ALARM = "9"
    AUX_4_ALARM = ":"
    CARBON_MONOXIDE_ALARM = ";"
    EMERGENCY_ALARM = "<"
    FREEZE_ALARM = "="
    GAS_ALARM = ">"
    HEAT_ALARM = "?"
    WATER_ALARM = "@"
    FIRE_SUPERVISORY = "A"
    VERIFY_FIRE = "B"
    UNSUPERVISED_ZONE_TROUBLE = "U"


class ArmLevel(Enum):
    """Arming level for the a0-a: (al) command family."""

    DISARM = "0"
    ARMED_AWAY = "1"
    ARMED_STAY = "2"
    ARMED_STAY_INSTANT = "3"
    ARMED_NIGHT = "4"
    ARMED_NIGHT_INSTANT = "5"
    ARMED_VACATION = "6"
    ARM_TO_NEXT_AWAY_MODE = "7"
    ARM_TO_NEXT_STAY_MODE = "8"
    FORCE_ARM_TO_AWAY_MODE = "9"
    FORCE_ARM_TO_STAY_MODE = ":"


class ZoneAlarmState(Enum):
    """AZ reply: per-zone alarm state."""

    NO_ALARM = "0"
    BURGLAR_ENTRY_EXIT_1 = "1"
    BURGLAR_ENTRY_EXIT_2 = "2"
    BURGLAR_PERIMETER_INSTANT = "3"
    BURGLAR_INTERIOR = "4"
    BURGLAR_INTERIOR_FOLLOWER = "5"
    BURGLAR_INTERIOR_NIGHT = "6"
    BURGLAR_INTERIOR_NIGHT_DELAY = "7"
    BURGLAR_24_HOUR = "8"
    BURGLAR_BOX_TAMPER = "9"
    FIRE_ALARM = ":"
    FIRE_VERIFIED = ";"
    FIRE_SUPERVISORY = "<"
    AUX_ALARM_1 = "="
    AUX_ALARM_2 = ">"
    KEYFOB = "?"
    NON_ALARM = "@"
    CARBON_MONOXIDE = "A"
    EMERGENCY_ALARM = "B"
    FREEZE_ALARM = "C"
    GAS_ALARM = "D"
    HEAT_ALARM = "E"
    MEDICAL_ALARM = "F"
    POLICE_ALARM = "G"
    POLICE_NO_INDICATION = "H"
    WATER_ALARM = "I"


class KeypadKeys(Enum):
    """DD field of the KC reply: which key was pressed."""

    NO_KEY = 0
    USER_CODE_ENTERED = 0  # noqa: PIE796 - the protocol reuses 0 for both cases
    STAR = 11
    POUND = 12
    F1 = 13
    F2 = 14
    F3 = 15
    F4 = 16
    STAY = 17
    EXIT = 18
    CHIME = 19
    BYPASS = 20
    ELK = 21
    DOWN = 22
    UP = 23
    RIGHT = 24
    LEFT = 25
    F6 = 26
    F5 = 27
    DATA_KEY_MODE = 28


class FunctionKeys(Enum):
    """kf command / KF reply: which function key."""

    FORCE_KF_SYNC = "0"
    F1 = "1"
    F2 = "2"
    F3 = "3"
    F4 = "4"
    F5 = "5"
    F6 = "6"
    STAR = "*"
    CHIME = "C"


class ChimeMode(Enum):
    """Per-area chime mode, from the KC reply's beep/chime field."""

    OFF = 0
    CHIME = 1
    VOICE = 2
    CHIMEANDVOICE = 3


class ThermostatSetting(Enum):
    """Element to set via the ts command."""

    MODE = 0
    HOLD = 1
    FAN = 2
    GET_TEMPERATURE = 3
    COOL_SETPOINT = 4
    HEAT_SETPOINT = 5


class ThermostatMode(Enum):
    """Thermostat operating mode."""

    OFF = 0
    HEAT = 1
    COOL = 2
    AUTO = 3
    EMERGENCY_HEAT = 4


class ThermostatFan(Enum):
    """Thermostat fan mode."""

    AUTO = 0
    ON = 1


class SettingFormat(Enum):
    """Display/encoding format of a custom value (Setting)."""

    NUMBER = 0
    TIMER = 1
    TIME_OF_DAY = 2


class ElkRPStatus(Enum):
    """RP reply: ElkRP remote-programming connection status."""

    DISCONNECTED = 0
    CONNECTED = 1
    INITIALIZING = 2


class TextDescription(NamedTuple):
    """A text-description type/count pair for the sd (text description) command."""

    desc_type: int
    number_descriptions: int


class TextDescriptions(Enum):
    """Types of description strings the panel can be asked for via sd."""

    ZONE = TextDescription(0, Max.ZONES.value)
    AREA = TextDescription(1, Max.AREAS.value)
    USER = TextDescription(2, Max.USERS.value)
    KEYPAD = TextDescription(3, Max.KEYPADS.value)
    OUTPUT = TextDescription(4, 64)
    TASK = TextDescription(5, Max.TASKS.value)
    TELEPHONE = TextDescription(6, 0)
    LIGHT = TextDescription(7, Max.LIGHTS.value)
    ALARM_DURATION = TextDescription(8, 0)
    SETTING = TextDescription(9, Max.SETTINGS.value)
    COUNTER = TextDescription(10, Max.COUNTERS.value)
    THERMOSTAT = TextDescription(11, Max.THERMOSTATS.value)
    FUNCTION_KEY_1 = TextDescription(12, 0)
    FUNCTION_KEY_2 = TextDescription(13, 0)
    FUNCTION_KEY_3 = TextDescription(14, 0)
    FUNCTION_KEY_4 = TextDescription(15, 0)
    FUNCTION_KEY_5 = TextDescription(16, 0)
    FUNCTION_KEY_6 = TextDescription(17, 0)
    AUDIO_ZONE = TextDescription(18, 0)
    AUDIO_SOURCE = TextDescription(19, 0)
