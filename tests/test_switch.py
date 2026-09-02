"""Tests for switch.py: output on/off/turn-on-for, and the zone bypass
switch's idempotent toggle-mapping (the protocol's `zb` bypass command is a
raw toggle, so turn_on/turn_off have to check current state before sending).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from elkm1_lib.const import ZoneLogicalStatus

from custom_components.elkm1.models import ElkPanelData
from custom_components.elkm1.switch import ElkOutput, ElkZoneBypassSwitch


def _output_switch(index: int, output_obj) -> ElkOutput:
    switch = object.__new__(ElkOutput)
    switch._index = index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(outputs=[output_obj])

    async def _queue(sender, _description):
        sender()
        return True

    coordinator.async_queue_command = AsyncMock(side_effect=_queue)
    switch.coordinator = coordinator
    return switch


async def test_output_turn_on_sends_indefinite_duration():
    output = MagicMock()
    switch = _output_switch(0, output)

    await switch.async_turn_on()

    output.turn_on.assert_called_once_with(0)


async def test_output_turn_off_sends_turn_off():
    output = MagicMock()
    switch = _output_switch(0, output)

    await switch.async_turn_off()

    output.turn_off.assert_called_once()


async def test_output_turn_on_for_converts_timedelta_to_seconds():
    output = MagicMock()
    switch = _output_switch(0, output)

    await switch.async_switch_output_turn_on_for(timedelta(minutes=2))

    output.turn_on.assert_called_once_with(120)


def _bypass_switch(index: int, zone_obj) -> ElkZoneBypassSwitch:
    switch = object.__new__(ElkZoneBypassSwitch)
    switch._index = index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(zones=[zone_obj])
    switch.coordinator = coordinator
    return switch


async def test_bypass_switch_turn_on_bypasses_when_not_already_bypassed():
    zone = MagicMock()
    zone.logical_status = ZoneLogicalStatus.NORMAL
    switch = _bypass_switch(0, zone)
    switch.coordinator.bypass_zone = AsyncMock()

    await switch.async_turn_on()

    switch.coordinator.bypass_zone.assert_called_once_with(1)


async def test_bypass_switch_turn_on_is_a_noop_when_already_bypassed():
    """The `zb` command toggles - calling it again would un-bypass, so
    turn_on must not send it if the zone is already bypassed.
    """
    zone = MagicMock()
    zone.logical_status = ZoneLogicalStatus.BYPASSED
    switch = _bypass_switch(0, zone)
    switch.coordinator.bypass_zone = AsyncMock()

    await switch.async_turn_on()

    switch.coordinator.bypass_zone.assert_not_called()


async def test_bypass_switch_turn_off_clears_bypass_when_bypassed():
    zone = MagicMock()
    zone.logical_status = ZoneLogicalStatus.BYPASSED
    switch = _bypass_switch(0, zone)
    switch.coordinator.bypass_zone = AsyncMock()

    await switch.async_turn_off()

    switch.coordinator.bypass_zone.assert_called_once_with(1)


async def test_bypass_switch_turn_off_is_a_noop_when_not_bypassed():
    zone = MagicMock()
    zone.logical_status = ZoneLogicalStatus.NORMAL
    switch = _bypass_switch(0, zone)
    switch.coordinator.bypass_zone = AsyncMock()

    await switch.async_turn_off()

    switch.coordinator.bypass_zone.assert_not_called()
