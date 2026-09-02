"""Tests for number.py: the ElkCounter entity's set/refresh entity services,
and that ElkCustomValue correctly rejects them (those services only make
sense for counters).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.elkm1.models import ElkPanelData
from custom_components.elkm1.number import ElkCounter, ElkCustomValue


def _counter(index: int, counter_obj) -> ElkCounter:
    entity = object.__new__(ElkCounter)
    entity._index = index
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(counters=[counter_obj])

    async def _confirm(sender, *_args, **_kwargs):
        sender()
        return True

    coordinator.async_confirm_command = AsyncMock(side_effect=_confirm)
    entity.coordinator = coordinator
    return entity


async def test_counter_refresh_calls_get():
    counter = MagicMock()
    entity = _counter(0, counter)

    await entity.async_counter_refresh()

    counter.get.assert_called_once()


async def test_counter_set_calls_set_with_value():
    counter = MagicMock()
    entity = _counter(0, counter)

    await entity.async_counter_set(42)

    counter.set.assert_called_once_with(42)


async def test_native_value_reads_from_counter_object():
    counter = MagicMock()
    counter.value = 7
    entity = _counter(0, counter)

    assert entity.native_value == 7


async def test_custom_value_rejects_counter_refresh_service():
    entity = object.__new__(ElkCustomValue)

    with pytest.raises(HomeAssistantError):
        await entity.async_counter_refresh()


async def test_custom_value_rejects_counter_set_service():
    entity = object.__new__(ElkCustomValue)

    with pytest.raises(HomeAssistantError):
        await entity.async_counter_set(5)
