"""Tests for binary_sensor.py: zone device_class mapping and the per-area
door/window aggregate sensor (the primary Better Thermostat integration
point - see docs/cross_integration.md).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.elkm1.binary_sensor import (
    _DEVICE_CLASS_MAP,
    _OPENING_DEFINITIONS,
    ElkAreaOpeningsBinarySensor,
    ElkBinarySensor,
    ElkTroubleBinarySensor,
    ElkZoneBypassBinarySensor,
    async_setup_entry,
)
from custom_components.elkm1.helpers.elk.const import ZoneLogicalStatus, ZoneType
from custom_components.elkm1.helpers.elk.zones import Zone
from custom_components.elkm1.models import AreaData, ElkPanelData, ElkRuntimeData


def _make_zone(index: int, definition: ZoneType, area: int = 0, name: str = "") -> Zone:
    """Build a real helpers.elk.Zone with the given definition/area, marked configured."""
    conn = MagicMock()
    notifier = MagicMock()
    zone = Zone(index, conn, notifier)
    zone.setattr("definition", definition, False)
    zone.setattr("area", area, False)
    zone._configured = True
    zone.name = name or f"Zone {index + 1}"
    return zone


def test_device_class_map_entry_exit_is_door():
    """Entry/exit zone types (1, 2) map to DOOR, not the old MOTION mistake for value 2."""
    assert _DEVICE_CLASS_MAP[1] == "door"
    assert _DEVICE_CLASS_MAP[2] == "door"


def test_device_class_map_perimeter_instant_is_generic_opening():
    """Perimeter-instant (3) maps to the generic OPENING class, not WINDOW."""
    assert _DEVICE_CLASS_MAP[3] == "opening"


def test_opening_definitions_cover_entry_exit_and_perimeter():
    assert {1, 2, 3} == _OPENING_DEFINITIONS


def _sensor_for_area(area_index: int, zones: list[Zone]) -> ElkAreaOpeningsBinarySensor:
    sensor = object.__new__(ElkAreaOpeningsBinarySensor)
    sensor._area_index = area_index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(num_areas=2, zones=zones)
    sensor.coordinator = coordinator
    return sensor


def test_area_openings_sensor_off_when_all_zones_closed():
    door = _make_zone(0, ZoneType.BURGLAR_ENTRY_EXIT_1, area=0, name="Front Door")
    sensor = _sensor_for_area(0, [door])
    assert sensor.is_on is False


def test_area_openings_sensor_on_when_a_door_opens():
    door = _make_zone(0, ZoneType.BURGLAR_ENTRY_EXIT_1, area=0, name="Front Door")
    door.setattr("logical_status", ZoneLogicalStatus.VIOLATED, False)
    sensor = _sensor_for_area(0, [door])

    assert sensor.is_on is True
    assert sensor.extra_state_attributes["open_zones"] == ["Front Door"]
    assert sensor.extra_state_attributes["open_zones_count"] == 1


def test_area_openings_sensor_ignores_non_opening_zone_types():
    """A fire-alarm zone opening shouldn't flip the door/window aggregate sensor."""
    smoke = _make_zone(0, ZoneType.FIRE_ALARM, area=0, name="Smoke Detector")
    smoke.setattr("logical_status", ZoneLogicalStatus.VIOLATED, False)
    sensor = _sensor_for_area(0, [smoke])

    assert sensor.is_on is False


def test_area_openings_sensor_isolates_areas():
    """A door open in area 2 must not affect area 1's aggregate sensor."""
    door_area_1 = _make_zone(0, ZoneType.BURGLAR_ENTRY_EXIT_1, area=0, name="Front Door")
    door_area_2 = _make_zone(1, ZoneType.BURGLAR_ENTRY_EXIT_1, area=1, name="Garage Door")
    door_area_2.setattr("logical_status", ZoneLogicalStatus.VIOLATED, False)

    zones = [door_area_1, door_area_2]
    sensor_area_1 = _sensor_for_area(0, zones)
    sensor_area_2 = _sensor_for_area(1, zones)

    assert sensor_area_1.is_on is False
    assert sensor_area_2.is_on is True


def _binary_sensor(zone_index: int, zones: list[Zone] | None) -> ElkBinarySensor:
    sensor = object.__new__(ElkBinarySensor)
    sensor._zone_index = zone_index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(zones=zones) if zones is not None else None
    sensor.coordinator = coordinator
    return sensor


def test_zone_binary_sensor_name_falls_back_before_the_zone_is_configured():
    sensor = _binary_sensor(0, None)
    assert sensor.name == "Zone 1"


def test_zone_binary_sensor_name_uses_the_panel_configured_name():
    zone = _make_zone(0, ZoneType.BURGLAR_ENTRY_EXIT_1, name="Front Door")
    sensor = _binary_sensor(0, [zone])
    assert sensor.name == "Front Door"


def test_zone_binary_sensor_is_off_when_zone_data_is_unavailable():
    sensor = _binary_sensor(0, None)
    assert sensor.is_on is False


def test_zone_binary_sensor_is_on_when_violated():
    zone = _make_zone(0, ZoneType.BURGLAR_ENTRY_EXIT_1)
    zone.setattr("logical_status", ZoneLogicalStatus.VIOLATED, False)
    sensor = _binary_sensor(0, [zone])
    assert sensor.is_on is True


def test_zone_binary_sensor_device_class_none_when_zone_data_is_unavailable():
    sensor = _binary_sensor(0, None)
    assert sensor.device_class is None


def test_zone_binary_sensor_device_class_from_definition():
    zone = _make_zone(0, ZoneType.BURGLAR_ENTRY_EXIT_1)
    sensor = _binary_sensor(0, [zone])
    assert sensor.device_class == "door"


def test_zone_binary_sensor_extra_state_attributes_empty_when_zone_data_is_unavailable():
    sensor = _binary_sensor(0, None)
    assert sensor.extra_state_attributes == {}


def test_zone_binary_sensor_extra_state_attributes_reports_bypassed_and_voltage():
    zone = _make_zone(0, ZoneType.BURGLAR_ENTRY_EXIT_1)
    zone.setattr("logical_status", ZoneLogicalStatus.BYPASSED, False)
    zone.setattr("voltage", 12.3, False)
    sensor = _binary_sensor(0, [zone])

    attrs = sensor.extra_state_attributes

    assert attrs["bypassed"] is True
    assert attrs["voltage"] == 12.3
    assert attrs["definition"] == ZoneType.BURGLAR_ENTRY_EXIT_1.value


def test_get_enum_value_accepts_a_digit_string_and_falls_back_otherwise():
    sensor = _binary_sensor(0, [])
    assert sensor._get_enum_value("5") == 5
    assert sensor._get_enum_value("not-a-number") == 0
    assert sensor._get_enum_value(None) == 0


def _trouble_sensor(name: str, data: ElkPanelData | None) -> ElkTroubleBinarySensor:
    sensor = object.__new__(ElkTroubleBinarySensor)
    sensor._trouble_name = name
    coordinator = MagicMock()
    coordinator.data = data
    sensor.coordinator = coordinator
    return sensor


def test_trouble_sensor_is_off_when_coordinator_has_no_data():
    sensor = _trouble_sensor("fire", None)
    assert sensor.is_on is False


def test_trouble_sensor_reflects_the_named_trouble():
    data = ElkPanelData(troubles={"fire": True})
    sensor = _trouble_sensor("fire", data)
    assert sensor.is_on is True


def test_trouble_sensor_extra_state_attributes_empty_without_data():
    sensor = _trouble_sensor("fire", None)
    assert sensor.extra_state_attributes == {}


def test_trouble_sensor_extra_state_attributes_empty_without_a_detail():
    data = ElkPanelData(troubles={"fire": True}, trouble_details={})
    sensor = _trouble_sensor("fire", data)
    assert sensor.extra_state_attributes == {}


def test_trouble_sensor_extra_state_attributes_reports_the_zone_number():
    data = ElkPanelData(troubles={"fire": True}, trouble_details={"fire": 17})
    sensor = _trouble_sensor("fire", data)
    assert sensor.extra_state_attributes == {"zone_or_device_number": 17}


def test_area_openings_sensor_empty_when_coordinator_has_no_data():
    sensor = _sensor_for_area(0, [])
    sensor.coordinator.data = None
    assert sensor._area_opening_zones() == []


def test_area_openings_get_enum_value_accepts_a_digit_string():
    sensor = _sensor_for_area(0, [])
    assert sensor._get_enum_value("5") == 5
    assert sensor._get_enum_value("not-a-number") == 0


class _FakeCoordinator:
    """Stands in for ElkDataUpdateCoordinator's async_add_listener/
    async_update_listeners pair, without needing a real DataUpdateCoordinator.
    """

    def __init__(self, data: ElkPanelData) -> None:
        self.data = data
        self._listeners: list = []

    def async_add_listener(self, callback):
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def async_update_listeners(self) -> None:
        for callback in list(self._listeners):
            callback()


async def test_zone_binary_sensor_appears_once_configured_after_setup(
    hass, mock_network_entry
):
    """A zone not yet `.configured` at setup must still get its entity once configured."""
    conn = MagicMock()
    notifier = MagicMock()
    zone = Zone(0, conn, notifier)
    zone.setattr("definition", ZoneType.BURGLAR_ENTRY_EXIT_1, False)
    # Not yet configured - the panel hasn't replied with this zone's name yet.
    assert zone.configured is False

    coordinator = _FakeCoordinator(ElkPanelData(num_areas=1, zones=[zone]))
    mock_network_entry.add_to_hass(hass)
    mock_network_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_network_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added_batches: list[list] = []

    def _async_add_entities(new_entities):
        added_batches.append(list(new_entities))

    await async_setup_entry(hass, mock_network_entry, _async_add_entities)

    # First pass: fixed trouble/area-openings entities only, no zone sensor yet.
    first_pass_zone_entities = [
        e for e in added_batches[0] if getattr(e, "_zone_index", None) == 0
    ]
    assert first_pass_zone_entities == []

    # Simulate the panel's SD reply for this zone arriving afterward.
    zone.setattr("name", "Front Door", False)
    zone._configured = True
    coordinator.async_update_listeners()

    zone_entities = [
        e for batch in added_batches for e in batch if getattr(e, "_zone_index", None) == 0
    ]
    assert len(zone_entities) == 1
    assert zone_entities[0].name == "Front Door"

    # Firing the listener again must not re-add the same zone a second time.
    coordinator.async_update_listeners()
    zone_entities = [
        e for batch in added_batches for e in batch if getattr(e, "_zone_index", None) == 0
    ]
    assert len(zone_entities) == 1


async def test_area_openings_setup_uses_real_area_indices_not_a_contiguous_range(
    hass, mock_network_entry
):
    """A panel can have a gap (e.g. Area 2 never programmed) while a later
    area (e.g. Area 8) is real. range(num_areas) would create a sensor for
    the unconfigured gap and skip the real later area entirely - see
    docs/decisions.md 2026-09-05."""
    coordinator = _FakeCoordinator(
        ElkPanelData(num_areas=3, areas={0: AreaData(), 2: AreaData(), 7: AreaData()})
    )
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

    opening_sensors = [e for e in added if isinstance(e, ElkAreaOpeningsBinarySensor)]
    assert {s._area_index for s in opening_sensors} == {0, 2, 7}


async def test_temperature_and_analog_zones_get_no_binary_sensor(hass, mock_network_entry):
    """Definitions 33 (temperature) and 34 (analog) are sensor.py entities,
    not binary sensors - async_setup_entry's zone filter must skip them."""
    conn = MagicMock()
    notifier = MagicMock()
    temp_zone = Zone(0, conn, notifier)
    temp_zone.setattr("definition", ZoneType.TEMPERATURE, False)
    temp_zone._configured = True
    temp_zone.name = "Attic"

    coordinator = _FakeCoordinator(ElkPanelData(num_areas=1, zones=[temp_zone]))
    mock_network_entry.add_to_hass(hass)
    mock_network_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_network_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added_batches: list[list] = []

    def _async_add_entities(new_entities):
        added_batches.append(list(new_entities))

    await async_setup_entry(hass, mock_network_entry, _async_add_entities)

    zone_entities = [
        e for batch in added_batches for e in batch if getattr(e, "_zone_index", None) == 0
    ]
    assert zone_entities == []


def _bypass_status_sensor(index: int, zone_obj) -> ElkZoneBypassBinarySensor:
    sensor = object.__new__(ElkZoneBypassBinarySensor)
    sensor._index = index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(zones=[zone_obj])
    sensor.coordinator = coordinator
    return sensor


def test_zone_bypass_status_is_on_when_bypassed():
    zone = MagicMock()
    zone.logical_status = ZoneLogicalStatus.BYPASSED
    sensor = _bypass_status_sensor(0, zone)
    assert sensor.is_on is True


def test_zone_bypass_status_is_off_when_not_bypassed():
    zone = MagicMock()
    zone.logical_status = ZoneLogicalStatus.NORMAL
    sensor = _bypass_status_sensor(0, zone)
    assert sensor.is_on is False


def test_zone_bypass_status_is_off_without_zone_object():
    """Index past the end of coordinator.data.zones - no crash, just off."""
    sensor = _bypass_status_sensor(5, MagicMock())
    sensor._index = 5
    sensor.coordinator.data = ElkPanelData(zones=[])
    assert sensor.is_on is False


def test_zone_bypass_status_name_falls_back_when_no_zone_object():
    sensor = _bypass_status_sensor(2, MagicMock())
    sensor.coordinator.data = ElkPanelData(zones=[])
    assert sensor.name == "Zone 3 Bypass"


def test_zone_bypass_status_name_suffixes_panel_reported_name():
    zone = MagicMock()
    zone.name = "Garage Door"
    sensor = _bypass_status_sensor(0, zone)
    assert sensor.name == "Garage Door Bypass"


def test_zone_bypass_status_init_sets_unique_id():
    coordinator = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "entry1"
    sensor = ElkZoneBypassBinarySensor(coordinator, config_entry, 4)
    assert sensor._index == 4
    assert sensor._attr_unique_id == "entry1_zone_5_bypass"


def test_zone_bypass_status_enum_value_default_for_non_numeric():
    assert ElkZoneBypassBinarySensor._enum_value("not-a-number", default=9) == 9


def test_zone_bypass_status_has_no_write_capability():
    """This entity must never expose turn_on/turn_off - see its docstring
    for why a code-less write path here would be a real security gap."""
    assert not hasattr(ElkZoneBypassBinarySensor, "async_turn_on")
    assert not hasattr(ElkZoneBypassBinarySensor, "async_turn_off")


async def test_binary_sensor_async_zone_bypass_threads_the_caller_supplied_code():
    """The elkm1.sensor_zone_bypass service (registered on this platform,
    schema requires `code`) is the only way to bypass a zone this platform
    covers - it must forward the caller's own code, not fall back silently."""
    sensor = _binary_sensor(0, [])
    sensor.coordinator.bypass_zone = AsyncMock()

    await sensor.async_zone_bypass("1234")

    sensor.coordinator.bypass_zone.assert_awaited_once_with(1, "1234")
