"""Tests for panel configuration verification helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.elkm1.helpers.panel_settings import (
    check_panel_version,
    check_required_settings,
)


def _coordinator(version: str | None) -> SimpleNamespace:
    return SimpleNamespace(data=SimpleNamespace(panel_version=version))


@pytest.mark.parametrize(
    "version",
    [
        "4.6.8",
        "4.6.9",
        "4.7.0",  # minor above the 4.6.x floor, patch below 8 - still newer
        "4.9.9",
        "5.2.0",
        "5.2.1",
        "5.3.0",
        "6.0.0",  # a major version newer than either checked branch
        "7.1.4",
    ],
)
async def test_check_panel_version_accepts_supported_versions(version: str) -> None:
    result = await check_panel_version(_coordinator(version))

    assert result == version


@pytest.mark.parametrize(
    "version",
    [
        "4.6.7",  # below the documented 4.6.8 floor
        "4.5.9",
        "5.0.0",  # below the 5.2.0 floor even though major == 5
        "5.1.9",
    ],
)
async def test_check_panel_version_still_returns_version_below_floor(version: str) -> None:
    """A below-floor version is returned as-is (with a warning logged), not hidden."""
    result = await check_panel_version(_coordinator(version))

    assert result == version


async def test_check_panel_version_polls_until_available() -> None:
    """panel_version arrives asynchronously; poll rather than assume it's set yet."""
    coordinator = _coordinator(None)

    async def _sleep(_delay: float) -> None:
        coordinator.data.panel_version = "5.2.0"

    with patch(
        "custom_components.elkm1.helpers.panel_settings.asyncio.sleep",
        AsyncMock(side_effect=_sleep),
    ):
        result = await check_panel_version(coordinator)

    assert result == "5.2.0"


async def test_check_panel_version_returns_none_when_never_available() -> None:
    with patch(
        "custom_components.elkm1.helpers.panel_settings.asyncio.sleep",
        AsyncMock(),
    ):
        result = await check_panel_version(_coordinator(None))

    assert result is None


async def test_check_required_settings_reports_unconfirmed_by_default() -> None:
    coordinator = SimpleNamespace(broadcast_counts={"ZC": 3})

    status = await check_required_settings(coordinator)

    assert status[36]["enabled"] is True
    assert status[36]["broadcast_count"] == 3
    assert status[37]["enabled"] is False
    assert status[37]["broadcast_count"] == 0
