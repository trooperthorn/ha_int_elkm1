"""Unit tests for helpers/elk/lights.py's `Light`/`Lights`. Closes a gap left
by the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.elkm1.helpers.elk.lights import Lights
from custom_components.elkm1.helpers.elk.notify import Notifier


def _lights() -> tuple[Lights, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    lights = Lights(connection, notifier)
    connection.reset_mock()
    return lights, connection, notifier


@pytest.mark.parametrize(("level", "expected_command"), [(0, "pf"), (-5, "pf"), (98, "pn"), (100, "pn")])
def test_level_at_the_off_and_full_on_boundaries_uses_the_dedicated_commands(level, expected_command):
    lights, connection, _notifier = _lights()
    lights[0].level(level)
    assert connection.send.call_args[0][0].message[2:4] == expected_command


def test_level_between_the_boundaries_uses_pc_dimming():
    lights, connection, _notifier = _lights()
    lights[0].level(50, time=10)
    assert connection.send.call_args[0][0].message[2:4] == "pc"


def test_toggle_sends_pt():
    lights, connection, _notifier = _lights()
    lights[0].toggle()
    assert connection.send.call_args[0][0].message[2:4] == "pt"


def test_sync_requests_all_four_banks_and_names():
    lights, connection, _notifier = _lights()
    lights.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["ps", "ps", "ps", "ps", "sd"]


def test_pc_handler_updates_the_named_light():
    lights, _connection, notifier = _lights()
    notifier.notify("PC", {"housecode": "A02", "index": 1, "light_level": 55})
    assert lights[1].status == 55


def test_ps_handler_updates_the_named_bank_only():
    lights, _connection, notifier = _lights()
    statuses = [0] * 64
    statuses[0] = 42
    notifier.notify("PS", {"bank": 1, "statuses": statuses})
    assert lights[64].status == 42
    assert lights[0].status == 0
