"""Manufacturer-derived protocol semantic and framing regression tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from elkm1_lib.const import AlarmState

from custom_components.elkm1.helpers.framing import (
    extract_frames,
    has_valid_length_and_checksum,
)
from custom_components.elkm1.helpers.troublestatus import (
    normalize_trouble_status,
    parse_trouble_details,
)
from custom_components.elkm1.light import ElkPlcLight
from custom_components.elkm1.protocol import alarm_is_active, protocol_value


def _wire(command: str, data: str = "") -> str:
    message = f"{len(data) + 6:02X}{command}{data}00"
    checksum = (256 - sum(map(ord, message))) % 256
    return f"{message}{checksum:02X}"


def test_extract_frames_accepts_every_documented_terminator():
    one = _wire("VN", "050003080000")
    two = _wire("XK", "0102030405060708")
    three = _wire("ZC", "0010")

    frames, remainder = extract_frames(f"{one}\r{two}\n{three}\r\npartial")

    assert frames == [one, two, three]
    assert remainder == "partial"
    assert all(has_valid_length_and_checksum(frame) for frame in frames)


def test_checksum_rejects_corruption():
    frame = _wire("VN", "050003080000")
    assert has_valid_length_and_checksum(frame)
    assert not has_valid_length_and_checksum(frame[:-1] + "0")


@pytest.mark.parametrize("state", tuple("0123456789:;<=>?@AB"))
def test_protocol_value_preserves_every_alarm_symbol(state):
    assert protocol_value(AlarmState(state)) == state


@pytest.mark.parametrize("state", tuple("3456789:;<=>?@AB"))
def test_full_alarm_table_is_active(state):
    assert alarm_is_active(state)


@pytest.mark.parametrize("state", ("0", "1", "2", "U"))
def test_non_full_alarm_states_are_not_active(state):
    assert not alarm_is_active(state)


def test_ss_reserved_bytes_removed_and_detail_decoded():
    status = list("0" * 34)
    status[5] = "A"
    raw = "".join(status) + "00"

    assert len(normalize_trouble_status(raw)) == 34
    assert parse_trouble_details(raw)["transmitter_low_battery"] == 17


@pytest.mark.parametrize(
    ("status", "expected"),
    [(0, 0), (1, 255), (2, 5), (50, 128), (99, 252)],
)
def test_lighting_status_brightness_semantics(status, expected):
    entity = object.__new__(ElkPlcLight)
    entity._index = 0
    light = MagicMock(status=status)
    entity.coordinator = MagicMock()
    entity.coordinator.data.lights = [light]

    assert entity.brightness == expected
