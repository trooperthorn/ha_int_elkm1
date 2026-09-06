"""Record specifications for every programmable Elk-M1 Gold table.

Each spec describes one EEPROM record as ElkRP stores it: the ordered byte
columns of the ElkRP account database are the record bytes themselves, so one
spec serves the database importer, the JSON account file, the wire encoder, and
the generated editor forms. Field names are ElkRP's own so a reader can match
them against the decompiled source; bit names come from the private ``*Bits``
enums in the corresponding ElkRP form. See docs/records.md for provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Kind(Enum):
    """How a field is stored in the record and shown in the editor."""

    U8 = "u8"
    TEXT = "text"
    VOICE = "voice"
    DIGITS = "digits"
    CODE = "code"
    BYTES = "bytes"
    U16 = "u16"


@dataclass(frozen=True)
class Bit:
    """One named bit or bit group inside a flag byte."""

    name: str
    lsb: int
    width: int = 1
    label: str = ""
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Field:
    """One field of a record."""

    name: str
    kind: Kind
    length: int = 1
    label: str = ""
    columns: tuple[str, ...] = ()
    bits: tuple[Bit, ...] = ()
    choices: tuple[str, ...] = ()
    minimum: int = 0
    maximum: int = 255
    hidden: bool = False

    @property
    def size(self) -> int:
        if self.kind is Kind.VOICE:
            return self.length * 2
        if self.kind is Kind.U16:
            return 2
        return self.length

    def column_names(self) -> tuple[str, ...]:
        """Database column names, one per byte, derived when not given."""
        if self.columns:
            return self.columns
        if self.kind is Kind.VOICE:
            return tuple(f"{self.name}{i}{h}" for i in range(1, self.length + 1) for h in "HL")
        if self.length == 1 and self.kind in (Kind.U8, Kind.BYTES):
            return (self.name,)
        return tuple(f"{self.name}{i}" for i in range(1, self.length + 1))


@dataclass(frozen=True)
class RecordSpec:
    """One EEPROM record type: its table, key, count, and ordered fields."""

    name: str
    table: str
    key: str
    count: int
    fields: tuple[Field, ...]
    label: str = ""
    first: int = 1
    crc_columns: tuple[str, ...] = ("UDCRC", "ModCRC")
    extra: tuple[Field, ...] = field(default_factory=tuple)

    @property
    def size(self) -> int:
        return sum(f.size for f in self.fields)

    def field_by_name(self, name: str) -> Field:
        for f in (*self.fields, *self.extra):
            if f.name == name:
                return f
        raise KeyError(name)


ZONE_FUNCTIONS: tuple[str, ...] = (
    "Disabled",
    "Burglar Entry/Exit 1",
    "Burglar Entry/Exit 2",
    "Burglar Perimeter Instant",
    "Burglar Interior",
    "Burglar Interior Follower",
    "Burglar Interior Night",
    "Burglar Interior Night Delay",
    "Burglar 24 Hour",
    "Burglar Box Tamper",
    "Fire Alarm",
    "Fire Verified",
    "Fire Supervisory",
    "Aux Alarm 1",
    "Aux Alarm 2",
    "Keyfob",
    "Non Alarm",
    "Carbon Monoxide",
    "Emergency Alarm",
    "Freeze Alarm",
    "Gas Alarm",
    "Heat Alarm",
    "Medical Alarm",
    "Police Alarm",
    "Police No Indication",
    "Water Alarm",
    "Key Momentary Arm/Disarm",
    "Key Momentary Arm Away",
    "Key Momentary Arm Stay",
    "Key Momentary Disarm",
    "Key On/Off",
    "Mute Audibles",
    "Power Supervisory",
    "Temperature",
    "Analog Zone",
    "Phone Key",
    "Intercom Key",
)

ZONE_HOOKUPS: tuple[str, ...] = (
    "EOL Supervised",
    "Normally Closed",
    "Normally Open",
    "Supervised Short",
    "Supervised Open",
    "4-Wire Smoke",
    "2-Wire Smoke (Zone 16)",
    "Analog",
)

AREA_NAMES: tuple[str, ...] = tuple(f"Area {i}" for i in range(1, 9))

# Global Programming G34 codes, installation manual page 36; 0 and 1 are both 300 baud.
SERIAL_BAUD_CODES: tuple[str, ...] = (
    "300",
    "300",
    "1200",
    "2400",
    "4800",
    "9600",
    "14400",
    "19200",
    "38400",
    "115200",
)

ZONE = RecordSpec(
    name="zone",
    label="Zones",
    table="ZoneDefinitions",
    key="ZoneNum",
    count=208,
    fields=(
        Field("ZnFunction", Kind.U8, label="Definition", choices=ZONE_FUNCTIONS),
        Field(
            "ZnFlag1",
            Kind.U8,
            label="Options",
            bits=(
                Bit("bypassable", 0, label="Bypassable"),
                Bit("activity_monitor", 1, label="Activity monitor"),
                Bit("fast_response", 2, label="Fast loop response"),
                Bit("force_arm", 3, label="Force arm"),
                Bit("chime", 4, label="Chime"),
                Bit("cross_zoned", 5, label="Cross zoned"),
                Bit("abort", 6, label="Alarm abort"),
                Bit("listen_in", 7, label="Listen in"),
            ),
        ),
        Field(
            "ZnFlag2",
            Kind.U8,
            label="Hookup and area",
            bits=(
                Bit("hookup", 0, 3, label="Hookup", choices=ZONE_HOOKUPS),
                Bit("swinger_shutdown", 3, label="Swinger shutdown"),
                Bit("area", 4, 3, label="Area", choices=AREA_NAMES),
                Bit("silent_alarm", 7, label="Silent alarm"),
            ),
        ),
        Field("ZnNotUsed1", Kind.U8, hidden=True),
        Field("ZnZoneName", Kind.TEXT, 16, label="Name"),
        Field("ZnVoice", Kind.VOICE, 6, label="Voice words"),
    ),
    extra=(
        Field("ZnRCAlarm", Kind.U8, label="Report code: alarm"),
        Field("ZnRCRestoral", Kind.U8, label="Report code: restoral"),
        Field("ZnRCBypass", Kind.U8, label="Report code: bypass"),
        Field("ZnRCTrouble", Kind.U8, label="Report code: trouble"),
    ),
)

AREA = RecordSpec(
    name="area",
    label="Areas",
    table="AreaDefinitions",
    key="AreaNum",
    count=8,
    fields=(
        Field("PName", Kind.TEXT, 16, label="Name"),
        Field("PExit1", Kind.U8, label="Exit delay 1 (s)"),
        Field("PEntrance1", Kind.U8, label="Entry delay 1 (s)"),
        Field("PExit2", Kind.U8, label="Exit delay 2 (s)"),
        Field("PEntrance2", Kind.U8, label="Entry delay 2 (s)"),
        Field(
            "PFlags1",
            Kind.U8,
            label="Arming options",
            bits=(
                Bit("quick_arm", 0, label="Quick arm (no code)"),
                Bit("closing_ringback", 1, 2, label="Closing ring-back"),
                Bit("auto_interior_off", 4, label="Auto interior off"),
                Bit("stay_key_scroll", 6, label="STAY key scrolls modes"),
            ),
        ),
        Field(
            "PFlags2",
            Kind.U8,
            label="Visible arm modes",
            bits=(
                Bit("show_night_instant", 3, label="Show Night Instant"),
                Bit("show_night", 4, label="Show Night"),
                Bit("show_stay_instant", 5, label="Show Stay Instant"),
                Bit("show_stay", 6, label="Show Stay"),
                Bit("double_press_arm", 7, label="Double press to arm"),
            ),
        ),
        Field("PArmTimeWindow", Kind.U8, label="Expected arm time window"),
        Field("PNotUsed", Kind.U8, hidden=True),
    ),
    extra=(
        Field("TeleCommAbortTime", Kind.U8, label="Communicator abort time"),
        Field("TeleCancelTime", Kind.U8, label="Cancel time"),
        Field("ARCAbort", Kind.U8, label="Report code: abort"),
        Field("ARCCancel", Kind.U8, label="Report code: cancel"),
        Field("ARCAutoClose", Kind.U8, label="Report code: auto close"),
        Field("ARCEarlyClose", Kind.U8, label="Report code: early close"),
        Field("ARCClosingExtended", Kind.U8, label="Report code: closing extended"),
        Field("ARCFailToClose", Kind.U8, label="Report code: fail to close"),
        Field("ARCLateClose", Kind.U8, label="Report code: late close"),
        Field("ARCKeySwitchClose", Kind.U8, label="Report code: keyswitch close"),
        Field("ARCDuress", Kind.U8, label="Report code: duress"),
        Field("ARCExcepOpen", Kind.U8, label="Report code: exception open"),
        Field("ARCEarlyOpen", Kind.U8, label="Report code: early open"),
        Field("ARCFailToOpen", Kind.U8, label="Report code: fail to open"),
        Field("ARCLateOpen", Kind.U8, label="Report code: late open"),
        Field("ARCKeySwitchOpen", Kind.U8, label="Report code: keyswitch open"),
        Field("ARCKPLockOut", Kind.U8, label="Report code: keypad lockout"),
        Field("ARCFailToComm", Kind.U8, label="Report code: fail to communicate"),
    ),
)

KEYPAD = RecordSpec(
    name="keypad",
    label="Keypads",
    table="KeypadDefinitions",
    key="KeypadNum",
    count=16,
    crc_columns=("UDCRC1", "ModCRC1"),
    fields=(
        Field("KeypadAreas", Kind.U8, label="Area", minimum=0, maximum=7),
        Field(
            "KPFlags1",
            Kind.U8,
            label="Display options",
            bits=(
                Bit("zone_response", 2, label="Show zone response"),
                Bit("temperature", 3, label="Show temperature"),
                Bit("date_time", 4, label="Show date and time"),
                Bit("area_name", 5, label="Show area name"),
            ),
        ),
        Field(
            "KPFlags2",
            Kind.U8,
            label="Function key light invert",
            bits=tuple(
                Bit(f"f{i}_invert_light", i - 1, label=f"F{i} invert light") for i in range(1, 7)
            ),
        ),
        Field(
            "KPFlags3",
            Kind.U8,
            label="Key requires code",
            bits=(
                Bit("bypass_key_code", 1, label="Bypass key requires code"),
                Bit("f6_code", 2, label="F6 requires code"),
                Bit("f5_code", 3, label="F5 requires code"),
                Bit("f4_code", 4, label="F4 requires code"),
                Bit("f3_code", 5, label="F3 requires code"),
                Bit("f2_code", 6, label="F2 requires code"),
                Bit("f1_code", 7, label="F1 requires code"),
            ),
        ),
        Field(
            "KPFlags4",
            Kind.U8,
            label="Backlight and tone",
            bits=(
                Bit("backlight", 0, 4, label="Backlight level"),
                Bit("key_tone", 4, 4, label="Key tone"),
            ),
        ),
        Field(
            "KPFlags5",
            Kind.U8,
            label="Silence options",
            bits=(
                Bit("silence_led", 1, label="Silence LED"),
                Bit("silence_chime", 2, label="Silence chime"),
                Bit("silence_exit", 3, label="Silence exit beeps"),
                Bit("silence_entry", 4, label="Silence entry beeps"),
                Bit("beep_volume", 5, 3, label="Beep volume"),
            ),
        ),
        Field("KeypadName", Kind.TEXT, 16, label="Name"),
        Field("KeyLEDState", Kind.U8, label="Function key LED defaults"),
        Field(
            "KPFlags6",
            Kind.U8,
            label="Function key light blink",
            bits=tuple(
                Bit(f"f{i}_blink_light", i - 1, label=f"F{i} blink light") for i in range(1, 7)
            ),
        ),
        Field(
            "KPFlags7",
            Kind.U8,
            label="Single key press",
            bits=tuple(
                Bit(f"f{i}_single_press", i - 1, label=f"F{i} single press") for i in range(1, 7)
            ),
        ),
        Field("NotUsed", Kind.BYTES, 3, hidden=True, columns=("NotUsed1", "NotUsed2", "NotUsed3")),
    ),
    extra=(
        *(
            Field(
                f"KeyF{i}Def",
                Kind.U16,
                label=f"F{i} task",
                columns=(f"KeyF{i}DefH", f"KeyF{i}DefL"),
            )
            for i in range(1, 7)
        ),
        *(
            Field(
                f"KeyF{i}LiteDef",
                Kind.U16,
                label=f"F{i} light event",
                columns=(f"KeyF{i}LiteDefH", f"KeyF{i}LiteDefL"),
            )
            for i in range(1, 7)
        ),
        Field("KPVerHW", Kind.U8, label="Keypad hardware version"),
    ),
)

USER = RecordSpec(
    name="user",
    label="User codes",
    table="UserCodes",
    key="CodeNum",
    count=199,
    fields=(
        Field("UCode", Kind.CODE, 6, label="Code"),
        Field(
            "UCFlags1",
            Kind.U8,
            label="Authorities",
            bits=(
                Bit("automation", 1, label="Automation menu"),
                Bit("master", 2, label="Master"),
                Bit("access", 4, label="Access"),
                Bit("bypass", 5, label="Bypass"),
                Bit("disarm", 6, label="Disarm"),
                Bit("arm", 7, label="Arm"),
            ),
        ),
        Field(
            "UCFlags2",
            Kind.U8,
            label="Duress",
            bits=(Bit("duress", 0, label="Duress code"),),
        ),
        Field("UCPartition", Kind.U8, label="Areas (bitmask, bit 0 = Area 1)"),
        Field("UCName", Kind.TEXT, 16, label="Name"),
        Field(
            "UCFlags3",
            Kind.U8,
            label="Temporary",
            bits=(Bit("temporary", 7, label="Temporary code"),),
        ),
        Field("UCNotUsed", Kind.BYTES, 2, hidden=True, columns=("UCNotUsed1", "UCNotUsed2")),
    ),
    extra=(
        Field("RCClose", Kind.U8, label="Report code: close"),
        Field("RCOpen", Kind.U8, label="Report code: open"),
    ),
)

OUTPUT = RecordSpec(
    name="output",
    label="Outputs",
    table="POutputs",
    key="OutputNum",
    count=208,
    fields=(
        Field("OPName", Kind.TEXT, 16, label="Name"),
        Field("OPVoice", Kind.VOICE, 6, label="Voice words"),
    ),
)

TASK = RecordSpec(
    name="task",
    label="Tasks",
    table="Tasks",
    key="TaskNum",
    count=32,
    fields=(
        Field("TaskName", Kind.TEXT, 16, label="Name"),
        Field("Voice", Kind.VOICE, 6, label="Voice words"),
    ),
)

TELEPHONE = RecordSpec(
    name="telephone",
    label="Telephone numbers",
    table="TelephoneNumbers",
    key="TeleNumID",
    count=8,
    fields=(
        Field("TeleNumber", Kind.DIGITS, 20, label="Number"),
        Field(
            "TeleFlag1",
            Kind.U8,
            label="Reports",
            bits=(
                Bit("global_system_events", 3, label="Global system events"),
                Bit("open_close", 4, label="Open and close"),
                Bit("zone_troubles", 5, label="Zone troubles and restores"),
                Bit("bypass", 6, label="Bypass and restores"),
                Bit("alarms", 7, label="Alarms and restores"),
            ),
        ),
        Field(
            "TeleFlag2",
            Kind.U8,
            label="Type and format",
            bits=(
                Bit("backup_of_previous", 3, label="Backup of previous number"),
                Bit("format", 4, 4, label="Reporting format"),
            ),
        ),
        Field("TeleAttempts", Kind.U8, label="Dial attempts"),
        *(Field(f"TeleAr{a}Acct", Kind.DIGITS, 6, label=f"Area {a} account") for a in range(1, 9)),
        Field("TeleName", Kind.TEXT, 16, label="Name"),
        Field("TeleNotUsed1", Kind.U8, hidden=True),
    ),
)

GLOBAL = RecordSpec(
    name="global",
    label="Global system definitions",
    table="Globals",
    key="",
    count=1,
    fields=(
        Field(
            "Global1Flags1",
            Kind.U8,
            label="System options",
            bits=(
                Bit("cross_zone_self_verify", 0, label="Cross zone self verify"),
                Bit("six_digit_codes", 2, label="Six digit user codes"),
                Bit("audible_trouble", 3, label="Audible trouble"),
                Bit("daylight_savings", 4, label="Daylight savings"),
                Bit("temp_celsius", 5, label="Temperature in Celsius"),
                Bit("date_mode", 6, label="Date format DD/MM"),
                Bit("clock_24h", 7, label="24 hour clock"),
            ),
        ),
        Field("CrossZnVerifyTime", Kind.U8, label="Cross zone verify time"),
        Field("FastLoopResponse", Kind.U8, label="Fast loop response"),
        Field("SlowLoopResponse", Kind.U8, label="Slow loop response"),
        Field(
            "Global1Nib1",
            Kind.U8,
            label="Telephone",
            bits=(
                Bit("two_way_talk_volume", 0, 3, label="Two way talk volume"),
                Bit("rings_until_answer", 4, 4, label="Rings until answer"),
            ),
        ),
        Field("CommonArea", Kind.U8, label="Common area"),
        Field(
            "Global1Flags2",
            Kind.U8,
            label="Siren",
            bits=(
                Bit("out1_siren_volume", 0, 3, label="Output 1 siren volume"),
                Bit("out1_volume_step", 3, 3, label="Output 1 volume step"),
                Bit("temporal", 6, label="Temporal fire pattern"),
            ),
        ),
        Field(
            "Global1Flags3",
            Kind.U8,
            label="Voice volume",
            bits=(
                Bit("out2_burglary_lockout", 1, label="Output 2 burglary lockout"),
                Bit("out1_message_volume", 2, 3, label="Output 1 message volume"),
                Bit("out1_alarm_message_volume", 5, 3, label="Output 1 alarm message volume"),
            ),
        ),
        Field("Out2CutOnTim", Kind.U8, label="Output 2 cut on time"),
        Field(
            "Global1Flags4",
            Kind.U8,
            label="Voice announcements",
            bits=(
                Bit("say_chime", 0, label="Say chime"),
                Bit("say_zone_trouble", 1, label="Say zone trouble"),
                Bit("say_system_trouble", 2, label="Say system trouble"),
                Bit("say_zone_status", 3, label="Say zone status"),
                Bit("say_alarms", 4, label="Say alarms"),
                Bit("say_system_messages", 5, label="Say system messages"),
                Bit("suppress_all_voice", 6, label="Suppress all voice"),
                Bit("out2_voltage", 7, label="Output 2 voltage"),
            ),
        ),
        Field("TWVCallbackTime", Kind.U8, label="Two way voice callback time"),
        Field(
            "Reserved",
            Kind.BYTES,
            4,
            hidden=True,
            columns=("Reserved1", "Reserved2", "Reserved3", "Reserved4"),
        ),
        Field("CSVerifyTime", Kind.U8, label="Central station verify time"),
        Field("CodeLockOut", Kind.U8, label="Code lockout"),
        Field("SysProgramCode", Kind.CODE, 6, label="Installer program code"),
        Field(
            "Reserved5",
            Kind.BYTES,
            6,
            hidden=True,
            columns=("Reserved5", "Reserved6", "Reserved7", "Reserved8", "Reserved9", "Reserved10"),
        ),
        Field(
            "Global1Flags5",
            Kind.U8,
            label="Telephone line",
            bits=(
                Bit("line_fault_timer", 0, 5, label="Telephone line fault timer"),
                Bit("ring_hang_ring", 5, label="Ring, hang, ring"),
                Bit("remote_control_level", 6, 2, label="Remote control level"),
            ),
        ),
        Field(
            "SendString",
            Kind.U8,
            label="Serial port transmit (Xmit) options",
            bits=(
                Bit("xmit_log", 0, label="Transmit event log"),
                Bit("xmit_zone_change", 1, label="Transmit zone changes"),
                Bit("xmit_output_change", 2, label="Transmit output changes"),
                Bit("xmit_task_change", 3, label="Transmit task changes"),
                Bit("xmit_plc_change", 4, label="Transmit lighting changes"),
                Bit("code_required", 7, label="Serial commands require code"),
            ),
        ),
        Field("StartDaylightSavings1", Kind.U8, label="DST start (day of week, month)"),
        Field("StartDaylightSavings2", Kind.U8, label="DST start (day of month)"),
        Field("StopDaylightSavings1", Kind.U8, label="DST stop (day of week, month)"),
        Field("StopDaylightSavings2", Kind.U8, label="DST stop (day of month)"),
        Field(
            "Global1Flags6",
            Kind.U8,
            label="Serial port",
            bits=(
                Bit(
                    "baud",
                    0,
                    4,
                    label="Serial port 0 baud (G34)",
                    choices=SERIAL_BAUD_CODES,
                ),
                Bit("two_way_listen_in", 4, label="Two way listen in"),
                Bit("keypad_keys_ascii", 5, label="Transmit keypad keys"),
            ),
        ),
        Field("S16", Kind.U8, label="Location 16 (meaning not yet traced)"),
        Field("S17", Kind.U8, label="Location 17 (meaning not yet traced)"),
        Field("S18", Kind.U8, label="Location 18 (meaning not yet traced)"),
        Field("S19", Kind.U8, label="Location 19 (meaning not yet traced)"),
        Field("S1A", Kind.U8, label="Location 1A (meaning not yet traced)"),
        Field("S1B", Kind.U8, label="Location 1B (meaning not yet traced)"),
        Field("S62", Kind.U8, label="Location 62 (meaning not yet traced)"),
        Field("SF5", Kind.U8, label="Location F5 (meaning not yet traced)"),
        Field("SF6", Kind.U8, label="Location F6 (meaning not yet traced)"),
        Field("SF7", Kind.U8, label="Location F7 (meaning not yet traced)"),
        Field("SDF", Kind.U8, label="Location DF (meaning not yet traced)"),
        Field("Country", Kind.U8, label="Country"),
    ),
    extra=(
        Field("AntiTakeover", Kind.U8, label="Anti-takeover (set by ElkRP; cannot be cleared)"),
    ),
)

X10 = RecordSpec(
    name="lighting",
    label="Lighting",
    table="X10Outputs",
    key="X10OutputNum",
    count=256,
    fields=(
        Field(
            "X10Flags1",
            Kind.U8,
            label="Options",
            bits=(
                Bit("two_way", 1, label="Two way"),
                Bit("type", 2, 3, label="Type"),
                Bit("format", 5, 3, label="Format"),
            ),
        ),
        Field("Description", Kind.TEXT, 15, label="Name"),
        Field("X10Voice", Kind.VOICE, 6, label="Voice words"),
    ),
)

VOICE_MESSAGE = RecordSpec(
    name="voice_message",
    label="Voice messages",
    table="VoiceMessages",
    key="MsgNum",
    count=999,
    fields=(Field("P", Kind.VOICE, 6, label="Words"),),
)

ALL_SPECS: tuple[RecordSpec, ...] = (
    AREA,
    ZONE,
    KEYPAD,
    USER,
    OUTPUT,
    TASK,
    TELEPHONE,
    GLOBAL,
    X10,
    VOICE_MESSAGE,
)

SPECS_BY_NAME: dict[str, RecordSpec] = {s.name: s for s in ALL_SPECS}
