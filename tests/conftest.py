"""Global fixtures for Elk-M1 integration tests."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.elkm1.const import DOMAIN


@pytest.fixture
def mock_serial_entry() -> MockConfigEntry:
    """A MockConfigEntry for a serial-connected panel, not yet added to hass."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "connection_type": "serial",
            "serial_port": "/dev/ttyUSB0",
            "device_id": "serial:/dev/ttyUSB0",
            "baud_rate": 115200,
            "prefix": "elkm1",
            "pin": "",
        },
        unique_id="serial:/dev/ttyUSB0",
    )


@pytest.fixture
def mock_elk() -> MagicMock:
    """A bare MagicMock standing in for a helpers.elk.Elk instance."""
    elk = MagicMock()
    elk.areas = [MagicMock() for _ in range(1)]
    elk.zones = []
    elk.counters = []
    return elk
