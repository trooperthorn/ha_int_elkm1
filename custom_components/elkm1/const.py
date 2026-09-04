"""Constants for Elk-M1 integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.const import ATTR_CODE, CONF_ZONE
from homeassistant.helpers import config_validation as cv

DOMAIN = "elkm1"
MANUFACTURER = "Elk Products"
MODEL = "M1 Gold / M1EZ8"
LOGIN_TIMEOUT = 20

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

ELK_USER_CODE_SERVICE_SCHEMA: dict[Any, Any] = {
    vol.Required(ATTR_CODE): vol.All(vol.Coerce(int), vol.Range(0, 999999))
}

SERVICE_ALARM_BYPASS = "alarm_bypass"
SERVICE_ALARM_CLEAR_BYPASS = "alarm_clear_bypass"
SERVICE_ALARM_ARM_HOME_INSTANT = "alarm_arm_home_instant"
SERVICE_ALARM_ARM_NIGHT_INSTANT = "alarm_arm_night_instant"
SERVICE_SENSOR_COUNTER_REFRESH = "sensor_counter_refresh"
SERVICE_SENSOR_COUNTER_SET = "sensor_counter_set"
SERVICE_SENSOR_ZONE_BYPASS = "sensor_zone_bypass"
SERVICE_SENSOR_ZONE_TRIGGER = "sensor_zone_trigger"
SERVICE_SWITCH_OUTPUT_TURN_ON_FOR = "switch_output_turn_on_for"

COUNTER_SET_SERVICE_SCHEMA: dict[Any, Any] = {
    vol.Required("value"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
}

ELK_OUTPUT_TURN_ON_FOR_SERVICE_SCHEMA: dict[Any, Any] = {
    vol.Required(ATTR_DURATION): vol.All(
        cv.time_period,
        vol.Range(min=timedelta(seconds=1), max=timedelta(seconds=65535)),
    ),
}
