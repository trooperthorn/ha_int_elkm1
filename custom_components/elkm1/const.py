"""Constants for Elk-M1 integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.const import ATTR_CODE, CONF_ZONE

DOMAIN = "elkm1"
MANUFACTURER = "Elk Products"
MODEL = "M1 Gold / M1EZ8"
LOGIN_TIMEOUT = 20

# Connection Configuration Keys & Types
CONF_CONNECTION_TYPE = "connection_type"
CONF_SERIAL_PORT = "serial_port"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PIN = "pin"
CONF_BAUD_RATE = "baud_rate"
CONF_DEVICE_ID = "device_id"
CONF_MAC_ADDRESS = "mac_address"

CONNECTION_SERIAL = "serial"
CONNECTION_NETWORK = "network"

COORDINATOR_UPDATE_INTERVAL = 30

CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = COORDINATOR_UPDATE_INTERVAL
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 300

CONF_AUTO_CONFIGURE = "auto_configure"
CONF_AREA = "area"
CONF_COUNTER = "counter"
CONF_KEYPAD = "keypad"
CONF_OUTPUT = "output"
CONF_PLC = "plc"
CONF_SETTING = "setting"
CONF_TASK = "task"
CONF_THERMOSTAT = "thermostat"
CONF_TEMPERATURE_UNIT = "temperature_unit"

DISCOVER_SCAN_TIMEOUT = 10
DISCOVERY_INTERVAL = timedelta(minutes=15)

# Hardcoded M1 Gold Hardware Maximums to replace elkm1_lib.const.Max
ELK_ELEMENTS = {
    CONF_AREA: 8,
    CONF_COUNTER: 64,
    CONF_KEYPAD: 16,
    CONF_OUTPUT: 208,
    CONF_PLC: 256,
    CONF_SETTING: 20,
    CONF_TASK: 32,
    CONF_THERMOSTAT: 16,
    CONF_ZONE: 208,
}

# Keypad and automation event constants
EVENT_ELKM1_KEYPAD_KEY_PRESSED = "elkm1.keypad_key_pressed"

ATTR_DURATION = "duration"
ATTR_KEYPAD_ID = "keypad_id"
ATTR_KEY = "key"
ATTR_KEY_NAME = "key_name"
ATTR_KEYPAD_NAME = "keypad_name"
ATTR_CHANGED_BY_KEYPAD = "changed_by_keypad"
ATTR_CHANGED_BY_ID = "changed_by_id"
ATTR_CHANGED_BY_TIME = "changed_by_time"
ATTR_VALUE = "value"

# Native service schema validation for strict PIN enforcement
ELK_USER_CODE_SERVICE_SCHEMA: dict[Any, Any] = {
    vol.Required(ATTR_CODE): vol.All(vol.Coerce(int), vol.Range(0, 999999))
}
