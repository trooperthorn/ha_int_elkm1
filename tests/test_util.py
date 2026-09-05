"""Tests for entity deprecation/migration helper.

deprecate_entity() is not called anywhere in the current integration code
(grep confirms no callers under custom_components/elkm1) - it appears to be
dead code left over from a planned migration path. These tests exercise its
documented behavior as written; see the coverage report for the flag.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.util import deprecate_entity


def test_deprecate_entity_migrates_legacy_entity_to_new_unique_id() -> None:
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "sensor.old_entity"
    entry = MagicMock(entity_id="sensor.old_entity")
    registry.async_get.side_effect = [entry, None]

    result = deprecate_entity(
        hass=MagicMock(),
        entity_registry=registry,
        platform="sensor",
        unique_id="old-unique-id",
        new_unique_id="new-unique-id",
        new_translation_key="new_key",
        old_entity_id="sensor.old_entity",
        new_entity_id="sensor.new_entity",
    )

    assert result is True
    registry.async_update_entity.assert_called_once_with(
        "sensor.old_entity", new_unique_id="new-unique-id"
    )


def test_deprecate_entity_skips_migration_when_new_entity_id_already_exists() -> None:
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "sensor.old_entity"
    entry = MagicMock(entity_id="sensor.old_entity")
    registry.async_get.side_effect = [entry, MagicMock()]

    result = deprecate_entity(
        hass=MagicMock(),
        entity_registry=registry,
        platform="sensor",
        unique_id="old-unique-id",
        new_unique_id="new-unique-id",
        new_translation_key="new_key",
        old_entity_id="sensor.old_entity",
        new_entity_id="sensor.new_entity",
    )

    assert result is True
    registry.async_update_entity.assert_not_called()


def test_deprecate_entity_skips_migration_when_already_at_new_entity_id() -> None:
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "sensor.new_entity"
    entry = MagicMock(entity_id="sensor.new_entity")
    registry.async_get.return_value = entry

    result = deprecate_entity(
        hass=MagicMock(),
        entity_registry=registry,
        platform="sensor",
        unique_id="old-unique-id",
        new_unique_id="new-unique-id",
        new_translation_key="new_key",
        old_entity_id="sensor.old_entity",
        new_entity_id="sensor.new_entity",
    )

    assert result is True
    registry.async_update_entity.assert_not_called()


def test_deprecate_entity_returns_true_when_entity_not_found() -> None:
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None

    result = deprecate_entity(
        hass=MagicMock(),
        entity_registry=registry,
        platform="sensor",
        unique_id="old-unique-id",
        new_unique_id="new-unique-id",
        new_translation_key="new_key",
        old_entity_id="sensor.old_entity",
        new_entity_id="sensor.new_entity",
    )

    assert result is True
    registry.async_update_entity.assert_not_called()


def test_deprecate_entity_returns_true_and_swallows_registry_errors() -> None:
    registry = MagicMock()
    registry.async_get_entity_id.side_effect = RuntimeError("registry unavailable")

    result = deprecate_entity(
        hass=MagicMock(),
        entity_registry=registry,
        platform="sensor",
        unique_id="old-unique-id",
        new_unique_id="new-unique-id",
        new_translation_key="new_key",
        old_entity_id="sensor.old_entity",
        new_entity_id="sensor.new_entity",
    )

    assert result is True
