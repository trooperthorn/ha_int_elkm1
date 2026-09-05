"""Tests for sensor.py: the panel/active-zones summary sensors, the analog/
temperature ElkZone sensor's state and attribute computation, and
async_setup_entry's definition-based zone filtering (only definitions 33
and 34 become sensors).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.elkm1.helpers.elk.const import ZoneType
from custom_components.elkm1.helpers.elk.zones import Zone
from custom_components.elkm1.models import ElkPanelData, ElkRuntimeData
from custom_components.elkm1.sensor import (
    UNDEFINED_TEMPERATURE,
    ElkActiveZonesSensor,
    ElkPanel,
    ElkSensor,
    ElkZone,
    async_setup_entry,
)


def test_get_enum_value_reads_value_attribute_from_enum_like_object():
    sensor = object.__new__(ElkSensor)
    assert sensor._get_enum_value(ZoneType.ANALOG_ZONE) == 34


def test_get_enum_value_reads_digit_string_as_int():
    sensor = object.__new__(ElkSensor)
    assert sensor._get_enum_value("34") == 34


def test_get_enum_value_returns_default_for_non_digit_string():
    sensor = object.__new__(ElkSensor)
    assert sensor._get_enum_value("not-a-number", default=7) == 7


def _active_zones_sensor(data: ElkPanelData | None) -> ElkActiveZonesSensor:
    sensor = object.__new__(ElkActiveZonesSensor)
    coordinator = MagicMock()
    coordinator.data = data
    sensor.coordinator = coordinator
    return sensor


def test_active_zones_native_value_is_zero_without_coordinator_data():
    sensor = _active_zones_sensor(None)
    assert sensor.native_value == 0


def test_active_zones_native_value_counts_faulted_zones():
    sensor = _active_zones_sensor(ElkPanelData(zones_faulted=[1, 3, 5]))
    assert sensor.native_value == 3


def test_active_zones_attributes_default_without_coordinator_data():
    sensor = _active_zones_sensor(None)
    assert sensor.extra_state_attributes == {"open_entities": "None"}


def test_active_zones_attributes_lists_faulted_zone_names():
    sensor = _active_zones_sensor(ElkPanelData(faulted_zone_names=["Front Door", "Garage"]))
    assert sensor.extra_state_attributes == {"open_entities": "Front Door, Garage"}


def test_active_zones_attributes_none_when_no_zones_faulted():
    sensor = _active_zones_sensor(ElkPanelData(faulted_zone_names=[]))
    assert sensor.extra_state_attributes == {"open_entities": "None"}


def _panel_sensor(data: ElkPanelData | None, connected: bool = True) -> ElkPanel:
    panel = object.__new__(ElkPanel)
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.connected = connected
    panel.coordinator = coordinator
    return panel


def test_panel_native_value_connected():
    panel = _panel_sensor(ElkPanelData(), connected=True)
    assert panel.native_value == "Connected"


def test_panel_native_value_disconnected():
    panel = _panel_sensor(ElkPanelData(), connected=False)
    assert panel.native_value == "Disconnected"


def test_panel_attributes_empty_without_coordinator_data():
    panel = _panel_sensor(None)
    assert panel.extra_state_attributes == {}


def test_panel_attributes_include_raw_and_parsed_trouble_status():
    panel = _panel_sensor(ElkPanelData(raw_trouble_status="10000000"))
    attrs = panel.extra_state_attributes
    assert attrs["system_trouble_status_raw"] == "10000000"
    assert "system_trouble_status_parsed" in attrs


def _zone_sensor(index: int, data: ElkPanelData | None) -> ElkZone:
    zone = object.__new__(ElkZone)
    zone._index = index
    zone._temperature_unit = "°F"
    coordinator = MagicMock()
    coordinator.data = data
    zone.coordinator = coordinator
    return zone


def test_zone_get_obj_none_without_coordinator_data():
    zone = _zone_sensor(0, None)
    assert zone._get_obj() is None


def test_zone_get_obj_none_when_index_out_of_range():
    zone = _zone_sensor(5, ElkPanelData(zones=[MagicMock()]))
    assert zone._get_obj() is None


def test_zone_get_obj_returns_matching_zone():
    zone_obj = MagicMock()
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone._get_obj() is zone_obj


def test_zone_name_falls_back_when_no_obj():
    zone = _zone_sensor(2, None)
    assert zone.name == "Zone 3"


def test_zone_name_uses_panel_reported_name():
    zone_obj = MagicMock()
    zone_obj.name = "Pool Temperature"
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.name == "Pool Temperature"


def test_zone_icon_is_thermometer_for_temperature_definition():
    zone_obj = MagicMock(definition=33)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.icon == "mdi:thermometer-lines"


def test_zone_icon_is_speedometer_for_analog_definition():
    zone_obj = MagicMock(definition=34)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.icon == "mdi:speedometer"


def test_zone_icon_is_speedometer_without_obj():
    zone = _zone_sensor(0, None)
    assert zone.icon == "mdi:speedometer"


def test_zone_device_class_temperature():
    zone_obj = MagicMock(definition=33)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.device_class == "temperature"


def test_zone_device_class_voltage():
    zone_obj = MagicMock(definition=34)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.device_class == "voltage"


def test_zone_device_class_none_for_unmapped_definition():
    zone_obj = MagicMock(definition=1)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.device_class is None


def test_zone_state_class_temperature_and_voltage_are_measurement():
    temp_zone = MagicMock(definition=33)
    volt_zone = MagicMock(definition=34)
    assert _zone_sensor(0, ElkPanelData(zones=[temp_zone])).state_class == "measurement"
    assert _zone_sensor(0, ElkPanelData(zones=[volt_zone])).state_class == "measurement"


def test_zone_state_class_none_for_unmapped_definition():
    zone_obj = MagicMock(definition=1)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.state_class is None


def test_zone_native_unit_is_fahrenheit_for_temperature():
    zone_obj = MagicMock(definition=33)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.native_unit_of_measurement == "°F"


def test_zone_native_unit_is_volt_for_analog():
    zone_obj = MagicMock(definition=34)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.native_unit_of_measurement == "V"


def test_zone_native_unit_is_none_for_unmapped_definition():
    zone_obj = MagicMock(definition=1)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.native_unit_of_measurement is None


def test_zone_native_value_none_without_obj():
    zone = _zone_sensor(0, None)
    assert zone.native_value is None


def test_zone_native_value_returns_temperature_as_string():
    zone_obj = MagicMock(definition=33, temperature=72)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.native_value == "72"


def test_zone_native_value_temperature_undefined_is_none():
    """Temperature at or below UNDEFINED_TEMPERATURE means no reading has
    arrived yet from the panel.
    """
    zone_obj = MagicMock(definition=33, temperature=UNDEFINED_TEMPERATURE)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.native_value is None


def test_zone_native_value_returns_voltage_as_string():
    zone_obj = MagicMock(definition=34, voltage=13.2)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.native_value == "13.2"


def test_zone_native_value_none_for_unmapped_definition():
    zone_obj = MagicMock(definition=1)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.native_value is None


def test_zone_attributes_empty_without_obj():
    zone = _zone_sensor(0, None)
    assert zone.extra_state_attributes == {}


def test_zone_attributes_reflect_status_and_bypass_flag():
    zone_obj = MagicMock(definition=33, physical_status=1, logical_status=3)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    attrs = zone.extra_state_attributes
    assert attrs["physical_status"] == 1
    assert attrs["logical_status"] == 3
    assert attrs["definition"] == 33
    assert attrs["bypassed"] is True


def test_zone_attributes_bypassed_false_when_not_bypassed():
    zone_obj = MagicMock(definition=33, physical_status=0, logical_status=0)
    zone = _zone_sensor(0, ElkPanelData(zones=[zone_obj]))
    assert zone.extra_state_attributes["bypassed"] is False


async def test_zone_async_zone_bypass_calls_coordinator():
    zone = _zone_sensor(0, None)
    zone.coordinator.bypass_zone = AsyncMock()

    await zone.async_zone_bypass("1234")

    zone.coordinator.bypass_zone.assert_called_once_with(1, "1234")


async def test_zone_async_zone_trigger_calls_coordinator():
    zone = _zone_sensor(3, None)
    zone.coordinator.trigger_zone = AsyncMock()

    await zone.async_zone_trigger()

    zone.coordinator.trigger_zone.assert_called_once_with(4)


def _make_zone(index: int, definition: ZoneType, name: str = "") -> Zone:
    conn = MagicMock()
    notifier = MagicMock()
    zone = Zone(index, conn, notifier)
    zone.setattr("definition", definition, False)
    zone._configured = True
    zone.name = name or f"Zone {index + 1}"
    return zone


async def test_setup_entry_only_creates_sensors_for_temperature_and_analog_zones(
    hass, mock_network_entry
):
    temp_zone = _make_zone(0, ZoneType.TEMPERATURE, "Attic Temp")
    analog_zone = _make_zone(1, ZoneType.ANALOG_ZONE, "Well Voltage")
    door_zone = _make_zone(2, ZoneType.BURGLAR_ENTRY_EXIT_1, "Front Door")

    coordinator = MagicMock()
    coordinator.data = ElkPanelData(zones=[temp_zone, analog_zone, door_zone])
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)

    mock_network_entry.add_to_hass(hass)
    mock_network_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_network_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []

    def _async_add_entities(new_entities):
        added.extend(new_entities)

    await async_setup_entry(hass, mock_network_entry, _async_add_entities)

    zone_sensors = [e for e in added if isinstance(e, ElkZone)]
    assert len(zone_sensors) == 2
    assert {z._index for z in zone_sensors} == {0, 1}

    assert any(isinstance(e, ElkPanel) for e in added)
    assert any(isinstance(e, ElkActiveZonesSensor) for e in added)
