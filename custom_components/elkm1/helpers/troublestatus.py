"""Parse the Elk-M1 system trouble status (SS) bitfield into per-condition booleans."""

from __future__ import annotations

# index -> (machine name, human name); unlisted indices are reserved in the SS reply.
TROUBLE_INDEX_NAMES: dict[int, tuple[str, str]] = {
    0: ("ac_fail", "AC Fail"),
    1: ("box_tamper", "Box Tamper"),
    2: ("fail_to_communicate", "Fail To Communicate"),
    3: ("eeprom_memory_error", "EEPROM Memory Error"),
    4: ("low_battery", "Low Battery Control"),
    5: ("transmitter_low_battery", "Transmitter Low Battery"),
    6: ("over_current", "Over Current"),
    7: ("telephone_fault", "Telephone Fault"),
    9: ("output_2", "Output 2"),
    10: ("missing_keypad", "Missing Keypad"),
    11: ("zone_expander", "Zone Expander"),
    12: ("output_expander", "Output Expander"),
    14: ("elkrp_remote_access", "ELKRP Remote Access"),
    16: ("common_area_not_armed", "Common Area Not Armed"),
    17: ("flash_memory_error", "Flash Memory Error"),
    18: ("security_alert", "Security Alert"),
    19: ("serial_port_expander", "Serial Port Expander"),
    20: ("lost_transmitter", "Lost Transmitter"),
    21: ("ge_smoke_cleanme", "GE Smoke CleanMe"),
    22: ("ethernet", "Ethernet"),
    31: ("display_message_line_1", "Display Message In Keypad Line 1"),
    32: ("display_message_line_2", "Display Message In Keypad Line 2"),
    33: ("fire", "Fire"),
}

# These positions carry a zone/device number (ASCII minus '0'), not a boolean flag.
TROUBLE_DETAIL_INDICES = frozenset((1, 5, 18, 20, 33))


def normalize_trouble_status(raw_status: str) -> str:
    """Return the 34 status bytes, excluding elkm1-lib's reserved ``00``."""
    return raw_status[:34]


def parse_troubles(raw_status: str) -> dict[str, bool]:
    """Parse a raw SS status string into {machine_name: is_active}.

    A position is inactive when '0' and active otherwise; zone numbers are
    not reported.
    """
    raw_status = normalize_trouble_status(raw_status)
    return {
        name: index < len(raw_status) and raw_status[index] != "0"
        for index, (name, _label) in TROUBLE_INDEX_NAMES.items()
    }


def parse_trouble_details(raw_status: str) -> dict[str, int]:
    """Return zone/device numbers carried by active detailed trouble fields."""
    raw_status = normalize_trouble_status(raw_status)
    details: dict[str, int] = {}
    for index in TROUBLE_DETAIL_INDICES:
        if index >= len(raw_status) or raw_status[index] == "0":
            continue
        name = TROUBLE_INDEX_NAMES[index][0]
        details[name] = ord(raw_status[index]) - ord("0")
    return details


def format_troubles(raw_status: str) -> str:
    """Return a human-readable, comma-separated list of active troubles."""
    active = parse_troubles(raw_status)
    labels = [label for index, (name, label) in TROUBLE_INDEX_NAMES.items() if active.get(name)]
    return ", ".join(labels) if labels else "Normal"
