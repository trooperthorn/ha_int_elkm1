"""Tests for scene.py: the ElkTask entity's name fallback and activation
command.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.elkm1.models import ElkPanelData, ElkRuntimeData
from custom_components.elkm1.scene import ElkTask, async_setup_entry


def _task(index: int, task_obj) -> ElkTask:
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(tasks=[task_obj])

    config_entry = MagicMock()
    config_entry.entry_id = "entry1"

    entity = ElkTask(coordinator, config_entry, index)

    async def _queue(sender, _description):
        sender()
        return True

    coordinator.async_queue_command = AsyncMock(side_effect=_queue)
    return entity


def test_init_sets_unique_id():
    entity = _task(0, MagicMock())

    assert entity._attr_unique_id == "entry1_task_1"


def test_get_obj_returns_none_when_index_out_of_range():
    entity = _task(0, MagicMock())
    entity._index = 5

    assert entity._get_obj() is None


def test_name_uses_panel_name_when_available():
    task = MagicMock()
    task.name = "Good Night"
    entity = _task(0, task)

    assert entity.name == "Good Night"


def test_name_falls_back_when_obj_missing():
    entity = _task(0, MagicMock())
    entity._index = 9

    assert entity.name == "Task 10"


async def test_async_activate_calls_task_activate():
    task = MagicMock()
    entity = _task(0, task)

    await entity.async_activate()

    task.activate.assert_called_once()


async def test_async_activate_is_a_noop_when_obj_missing():
    entity = _task(0, MagicMock())
    entity._index = 9

    await entity.async_activate()

    entity.coordinator.async_queue_command.assert_not_called()


async def test_setup_entry_creates_entity_for_configured_task(hass, mock_serial_entry):
    task = MagicMock()
    task.index = 0
    task.configured = True
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(tasks=[task])
    coordinator.async_add_listener.return_value = lambda: None

    mock_serial_entry.add_to_hass(hass)
    mock_serial_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_serial_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []
    await async_setup_entry(hass, mock_serial_entry, lambda ents: added.extend(ents))

    assert len(added) == 1
    assert isinstance(added[0], ElkTask)
