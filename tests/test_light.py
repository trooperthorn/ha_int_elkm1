"""Tests for light.py: PLC status-to-brightness conversion and the
turn_on/turn_off command methods.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.elkm1.light import ElkPlcLight, async_setup_entry
from custom_components.elkm1.models import ElkPanelData, ElkRuntimeData


def _light(index: int, light_obj) -> ElkPlcLight:
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(lights=[light_obj])

    config_entry = MagicMock()
    config_entry.entry_id = "entry1"

    entity = ElkPlcLight(coordinator, config_entry, index)

    async def _queue(sender, _description):
        sender()
        return True

    coordinator.async_queue_command = AsyncMock(side_effect=_queue)
    return entity


def test_init_sets_unique_id_and_color_mode():
    entity = _light(0, MagicMock())

    assert entity._attr_unique_id == "entry1_light_1"
    assert entity._attr_color_mode == "brightness"


def test_get_obj_returns_none_when_index_out_of_range():
    entity = _light(0, MagicMock())
    entity._index = 5

    assert entity._get_obj() is None


def test_name_uses_panel_name_when_available():
    light = MagicMock()
    light.name = "Kitchen"
    entity = _light(0, light)

    assert entity.name == "Kitchen"


def test_name_falls_back_when_obj_missing():
    entity = _light(0, MagicMock())
    entity._index = 9

    assert entity.name == "Light 10"


def test_is_on_false_when_obj_missing():
    entity = _light(0, MagicMock())
    entity._index = 9

    assert entity.is_on is False


def test_is_on_true_when_status_positive():
    light = MagicMock()
    light.status = 50
    entity = _light(0, light)

    assert entity.is_on is True


def test_is_on_false_when_status_zero():
    light = MagicMock()
    light.status = 0
    entity = _light(0, light)

    assert entity.is_on is False


def test_brightness_none_when_obj_missing():
    entity = _light(0, MagicMock())
    entity._index = 9

    assert entity.brightness is None


def test_brightness_zero_when_status_zero():
    light = MagicMock()
    light.status = 0
    entity = _light(0, light)

    assert entity.brightness == 0


def test_brightness_full_when_status_is_full_on_flag():
    light = MagicMock()
    light.status = 1
    entity = _light(0, light)

    assert entity.brightness == 255


def test_brightness_scales_dim_percentage_to_ha_range():
    light = MagicMock()
    light.status = 50
    entity = _light(0, light)

    assert entity.brightness == round(50 * 255 / 100)


def test_brightness_caps_status_above_ninety_nine():
    light = MagicMock()
    light.status = 100
    entity = _light(0, light)

    assert entity.brightness == round(99 * 255 / 100)


async def test_turn_on_without_brightness_sends_full_level():
    light = MagicMock()
    entity = _light(0, light)

    await entity.async_turn_on()

    light.level.assert_called_once_with(100)


async def test_turn_on_with_brightness_scales_and_floors_at_two():
    light = MagicMock()
    entity = _light(0, light)

    await entity.async_turn_on(brightness=1)

    light.level.assert_called_once_with(2)


async def test_turn_on_with_brightness_scales_to_elk_range():
    light = MagicMock()
    entity = _light(0, light)

    await entity.async_turn_on(brightness=128)

    light.level.assert_called_once_with(round(128 * 100 / 255))


async def test_turn_on_is_a_noop_when_obj_missing():
    entity = _light(0, MagicMock())
    entity._index = 9

    await entity.async_turn_on()

    entity.coordinator.async_queue_command.assert_not_called()


async def test_turn_off_sends_zero_level():
    light = MagicMock()
    entity = _light(0, light)

    await entity.async_turn_off()

    light.level.assert_called_once_with(0)


async def test_turn_off_is_a_noop_when_obj_missing():
    entity = _light(0, MagicMock())
    entity._index = 9

    await entity.async_turn_off()

    entity.coordinator.async_queue_command.assert_not_called()


async def test_setup_entry_creates_entity_for_configured_light(hass, mock_network_entry):
    light = MagicMock()
    light.index = 0
    light.configured = True
    coordinator = MagicMock()
    coordinator.data = ElkPanelData(lights=[light])
    coordinator.async_add_listener.return_value = lambda: None

    mock_network_entry.add_to_hass(hass)
    mock_network_entry.runtime_data = ElkRuntimeData(
        prefix="",
        mac=mock_network_entry.unique_id,
        auto_configure=True,
        config={},
        coordinator=coordinator,
    )

    added: list = []
    await async_setup_entry(hass, mock_network_entry, lambda ents: added.extend(ents))

    assert len(added) == 1
    assert isinstance(added[0], ElkPlcLight)
