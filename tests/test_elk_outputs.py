"""Unit tests for helpers/elk/outputs.py's `Output`/`Outputs`. Closes a gap
left by the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.helpers.elk.const import Max
from custom_components.elkm1.helpers.elk.notify import Notifier
from custom_components.elkm1.helpers.elk.outputs import Outputs


def _outputs() -> tuple[Outputs, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    outputs = Outputs(connection, notifier)
    connection.reset_mock()
    return outputs, connection, notifier


def test_turn_off_sends_cf():
    outputs, connection, _notifier = _outputs()
    outputs[0].turn_off()
    assert connection.send.call_args[0][0].message[2:4] == "cf"


def test_turn_on_sends_cn_with_the_given_duration():
    outputs, connection, _notifier = _outputs()
    outputs[0].turn_on(120)
    sent = connection.send.call_args[0][0].message
    assert sent[2:4] == "cn"
    assert sent[7:12] == "00120"


def test_toggle_sends_ct():
    outputs, connection, _notifier = _outputs()
    outputs[0].toggle()
    assert connection.send.call_args[0][0].message[2:4] == "ct"


def test_sync_requests_status_and_names():
    outputs, connection, _notifier = _outputs()
    outputs.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["cs", "sd"]


def test_cc_handler_updates_a_single_output():
    outputs, _connection, notifier = _outputs()
    notifier.notify("CC", {"output": 4, "output_status": True})
    assert outputs[4].output_on is True
    assert outputs[0].output_on is False


def test_cs_handler_updates_every_output():
    outputs, _connection, notifier = _outputs()
    statuses = [False] * Max.OUTPUTS.value
    statuses[0] = True
    notifier.notify("CS", {"output_status": statuses})
    assert outputs[0].output_on is True
    assert outputs[1].output_on is False
