"""Tests for device automation actions (speak_phrase, display_message)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.elkm1.const import DOMAIN
from custom_components.elkm1.device_action import (
    async_call_action_from_config,
    async_get_actions,
)


async def test_async_get_actions_returns_both_actions_for_an_elkm1_device(hass) -> None:
    device_id = "device-1"
    with patch(
        "custom_components.elkm1.device_action.dr.async_get"
    ) as mock_async_get:
        registry = MagicMock()
        registry.async_get.return_value = MagicMock(identifiers={(DOMAIN, "aa:bb:cc")})
        mock_async_get.return_value = registry

        actions = await async_get_actions(hass, device_id)

    assert actions == [
        {"device_id": device_id, "domain": DOMAIN, "type": "speak_phrase"},
        {"device_id": device_id, "domain": DOMAIN, "type": "display_message"},
    ]


async def test_async_get_actions_returns_empty_for_unknown_device(hass) -> None:
    with patch(
        "custom_components.elkm1.device_action.dr.async_get"
    ) as mock_async_get:
        registry = MagicMock()
        registry.async_get.return_value = None
        mock_async_get.return_value = registry

        actions = await async_get_actions(hass, "missing-device")

    assert actions == []


async def test_async_get_actions_returns_empty_for_device_of_another_domain(hass) -> None:
    with patch(
        "custom_components.elkm1.device_action.dr.async_get"
    ) as mock_async_get:
        registry = MagicMock()
        registry.async_get.return_value = MagicMock(identifiers={("other_domain", "1")})
        mock_async_get.return_value = registry

        actions = await async_get_actions(hass, "device-1")

    assert actions == []


async def test_async_call_action_from_config_speak_phrase(hass) -> None:
    config = {"type": "speak_phrase", "phrase_number": 5}

    with patch(
        "homeassistant.core.ServiceRegistry.async_call", AsyncMock()
    ) as mock_call:
        await async_call_action_from_config(hass, config, {}, None)

    mock_call.assert_awaited_once_with(
        DOMAIN, "speak_phrase", {"number": 5}, context=None
    )


async def test_async_call_action_from_config_display_message(hass) -> None:
    config = {"type": "display_message", "line1": "Hello"}

    with patch(
        "homeassistant.core.ServiceRegistry.async_call", AsyncMock()
    ) as mock_call:
        await async_call_action_from_config(hass, config, {}, None)

    mock_call.assert_awaited_once_with(
        DOMAIN, "display_message", {"line1": "Hello"}, context=None
    )


async def test_async_call_action_from_config_display_message_defaults_empty_line(
    hass,
) -> None:
    config = {"type": "display_message"}

    with patch(
        "homeassistant.core.ServiceRegistry.async_call", AsyncMock()
    ) as mock_call:
        await async_call_action_from_config(hass, config, {}, None)

    mock_call.assert_awaited_once_with(
        DOMAIN, "display_message", {"line1": ""}, context=None
    )


async def test_async_call_action_from_config_speak_phrase_defaults_none_number(
    hass,
) -> None:
    config = {"type": "speak_phrase"}

    with patch(
        "homeassistant.core.ServiceRegistry.async_call", AsyncMock()
    ) as mock_call:
        await async_call_action_from_config(hass, config, {}, None)

    mock_call.assert_awaited_once_with(
        DOMAIN, "speak_phrase", {"number": None}, context=None
    )
