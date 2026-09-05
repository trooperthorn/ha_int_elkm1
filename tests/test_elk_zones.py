"""Unit tests for helpers/elk/zones.py's `Zone`/`Zones`. Closes a gap left by
the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.helpers.elk.const import (
    Max,
    ZoneAlarmState,
    ZoneLogicalStatus,
    ZonePhysicalStatus,
    ZoneType,
)
from custom_components.elkm1.helpers.elk.notify import Notifier
from custom_components.elkm1.helpers.elk.zones import Zones


def _zones() -> tuple[Zones, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    zones = Zones(connection, notifier)
    connection.reset_mock()
    return zones, connection, notifier


# --------------------------------------------------------------------------
# Zone
# --------------------------------------------------------------------------


def test_str_includes_type_status_and_area():
    zones, _connection, _notifier = _zones()
    zone = zones[0]
    zone.setattr("definition", ZoneType.BURGLAR_ENTRY_EXIT_1, False)
    zone.setattr("area", 2, False)
    text = str(zone)
    assert "type:BURGLAR_ENTRY_EXIT_1" in text
    assert "area:2" in text


def test_bypass_sends_zb_for_this_zone_only():
    zones, connection, _notifier = _zones()
    zones[4].bypass(1234)
    sent = connection.send.call_args[0][0].message
    assert sent[2:4] == "zb"
    assert sent[4:7] == "005"


def test_trigger_sends_zt():
    zones, connection, _notifier = _zones()
    zones[4].trigger()
    assert connection.send.call_args[0][0].message[2:4] == "zt"


def test_get_voltage_sends_zv():
    zones, connection, _notifier = _zones()
    zones[4].get_voltage()
    assert connection.send.call_args[0][0].message[2:4] == "zv"


# --------------------------------------------------------------------------
# Zones
# --------------------------------------------------------------------------


def test_sync_requests_alarm_definitions_partitions_statuses_and_names():
    zones, connection, _notifier = _zones()
    zones.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["az", "zd", "zp", "zs", "sd"]


def test_az_handler_marks_triggered_zones():
    zones, _connection, notifier = _zones()
    alarm_status = [ZoneAlarmState.NO_ALARM] * Max.ZONES.value
    alarm_status[8] = ZoneAlarmState.BURGLAR_BOX_TAMPER
    notifier.notify("AZ", {"alarm_status": alarm_status})
    assert zones[8].triggered_alarm is True
    assert zones[0].triggered_alarm is False


def test_lw_handler_updates_only_the_first_16_zones():
    zones, _connection, notifier = _zones()
    zone_temps = [32] * 16 + [-60] * (Max.ZONES.value - 16)
    notifier.notify("LW", {"keypad_temps": [0] * 16, "zone_temps": zone_temps})
    assert zones[0].temperature == 32
    assert zones[15].temperature == 32
    # Zone 16 (index 16) is outside LW's 16-zone coverage and stays default.
    assert zones[16].temperature == -60


def test_lw_handler_ignores_the_no_probe_sentinel():
    zones, _connection, notifier = _zones()
    zones[0].setattr("temperature", 15)
    notifier.notify("LW", {"keypad_temps": [0] * 16, "zone_temps": [-60] * 16})
    assert zones[0].temperature == 15  # unchanged - sentinel means "no probe"


def test_st_handler_updates_group_zero_only():
    zones, _connection, notifier = _zones()
    notifier.notify("ST", {"group": 0, "device": 3, "temperature": 40})
    assert zones[3].temperature == 40

    notifier.notify("ST", {"group": 1, "device": 3, "temperature": 99})
    assert zones[3].temperature == 40  # group 1 is keypads, not zones


def test_zb_handler_requests_full_status_for_bypass_all():
    _zones_obj, connection, notifier = _zones()
    notifier.notify("ZB", {"zone_number": -1, "zone_bypassed": True})
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert "zs" in sent_commands


def test_zb_handler_does_not_request_full_status_for_a_specific_zone():
    _zones_obj, connection, notifier = _zones()
    notifier.notify("ZB", {"zone_number": 4, "zone_bypassed": True})
    connection.send.assert_not_called()


def test_zc_handler_updates_the_named_zones_status():
    zones, _connection, notifier = _zones()
    notifier.notify(
        "ZC", {"zone_number": 4, "zone_status": (ZoneLogicalStatus.VIOLATED, ZonePhysicalStatus.OPEN)}
    )
    assert zones[4].logical_status == ZoneLogicalStatus.VIOLATED
    assert zones[4].physical_status == ZonePhysicalStatus.OPEN


def test_zd_handler_sets_every_zones_definition():
    zones, _connection, notifier = _zones()
    definitions = [ZoneType.DISABLED] * Max.ZONES.value
    definitions[0] = ZoneType.BURGLAR_ENTRY_EXIT_1
    notifier.notify("ZD", {"zone_definitions": definitions})
    assert zones[0].definition == ZoneType.BURGLAR_ENTRY_EXIT_1
    assert zones[1].definition == ZoneType.DISABLED


def test_zp_handler_sets_every_zones_area():
    zones, _connection, notifier = _zones()
    partitions = [0] * Max.ZONES.value
    partitions[10] = 2
    notifier.notify("ZP", {"zone_partitions": partitions})
    assert zones[10].area == 2


def test_zs_handler_sets_every_zones_status():
    zones, _connection, notifier = _zones()
    statuses = [(ZoneLogicalStatus.NORMAL, ZonePhysicalStatus.UNCONFIGURED)] * Max.ZONES.value
    statuses[5] = (ZoneLogicalStatus.TROUBLED, ZonePhysicalStatus.EOL)
    notifier.notify("ZS", {"zone_statuses": statuses})
    assert zones[5].logical_status == ZoneLogicalStatus.TROUBLED
    assert zones[5].physical_status == ZonePhysicalStatus.EOL


def test_zv_handler_updates_the_named_zones_voltage():
    zones, _connection, notifier = _zones()
    notifier.notify("ZV", {"zone_number": 4, "zone_voltage": 12.3})
    assert zones[4].voltage == 12.3
