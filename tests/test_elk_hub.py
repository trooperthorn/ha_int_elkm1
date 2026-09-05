"""Unit tests for helpers/elk/hub.py's `Elk` hub: element construction, the
login/sync handshake, and connection delegation. Closes a gap left by the
2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.elkm1.helpers.elk.hub import Elk


def _elk(url: str = "elk://1.2.3.4:2101", **extra) -> Elk:
    config = {"url": url, **extra}
    elk = Elk(config)
    elk._connection.writer = MagicMock()  # so send()/send_raw() don't reject as disconnected
    return elk


ELEMENT_ATTRS = (
    "areas",
    "counters",
    "keypads",
    "lights",
    "outputs",
    "panel",
    "settings",
    "tasks",
    "thermostats",
    "users",
    "zones",
)


def test_constructor_builds_every_element_collection():
    elk = _elk()
    for attr in ELEMENT_ATTRS:
        assert getattr(elk, attr) is not None


def test_default_element_list_matches_what_call_sync_handlers_iterates():
    elk = _elk()
    assert set(elk.element_list) == set(ELEMENT_ATTRS)


def test_element_list_can_be_overridden_via_config():
    elk = _elk(element_list=["panel", "zones"])
    assert elk.element_list == ["panel", "zones"]


def test_connection_property_returns_the_owned_connection():
    elk = _elk()
    assert elk.connection is elk._connection


def test_add_and_remove_handler_delegate_to_the_notifier():
    elk = _elk()
    calls = []
    handler = lambda **_: calls.append(1)  # noqa: E731
    elk.add_handler("VN", handler)
    elk._notifier.notify("VN", {})
    assert calls == [1]

    elk.remove_handler("VN", handler)
    elk._notifier.notify("VN", {})
    assert calls == [1]  # unchanged - handler was removed


def test_send_delegates_to_the_connection():
    elk = _elk()
    message = MagicMock(message="06vn00", response_command="VN")
    elk.send(message)
    assert elk._connection._write_queue[0].msg == "06vn00"


def test_disconnect_is_connected_and_is_paused_delegate_to_the_connection():
    elk = _elk()
    assert elk.is_connected() is True
    assert elk.is_paused() is False

    elk.disconnect()
    assert elk.is_connected() is False


async def test_connect_raises_not_implemented():
    elk = _elk()
    with pytest.raises(NotImplementedError, match="not used"):
        await elk.connect()


# --------------------------------------------------------------------------
# Login handshake
# --------------------------------------------------------------------------


def test_login_status_success_marks_logged_in_and_does_not_disconnect():
    elk = _elk()
    elk._notifier.notify("login", {"succeeded": True})
    assert elk._logged_in is True
    assert elk.is_connected() is True


def test_login_status_failure_disconnects(caplog):
    elk = _elk()
    elk._notifier.notify("login", {"succeeded": False})
    assert elk._logged_in is False
    assert elk.is_connected() is False
    assert "Invalid username or password" in caplog.text


def test_got_first_message_fires_login_success_when_not_yet_logged_in():
    """Non-secure schemes have no explicit login reply, so the first message
    of any kind (a "VN" sync reply) is treated as proof of a working link."""
    elk = _elk()
    logins = []
    elk.add_handler("login", lambda **payload: logins.append(payload))

    elk._notifier.notify("VN", {"elkm1_version": "5.3.18", "xep_version": "0.0.0"})

    assert logins == [{"succeeded": True}]


def test_got_first_message_does_nothing_once_already_logged_in():
    """A secure scheme's real login event must not be overwritten by a later
    first-message login synthesis."""
    elk = _elk()
    elk._notifier.notify("login", {"succeeded": True})
    logins = []
    elk.add_handler("login", lambda **payload: logins.append(payload))

    elk._notifier.notify("VN", {"elkm1_version": "5.3.18", "xep_version": "0.0.0"})

    assert logins == []


def test_disconnected_resets_the_logged_in_flag():
    elk = _elk()
    elk._notifier.notify("login", {"succeeded": True})
    assert elk._logged_in is True

    elk._notifier.notify("disconnected", {})
    assert elk._logged_in is False


# --------------------------------------------------------------------------
# _connected: credential handling and sync trigger
# --------------------------------------------------------------------------


def test_connected_sends_no_credentials_for_a_non_secure_scheme():
    elk = _elk("elk://1.2.3.4:2101")
    elk._connection.send_raw = MagicMock()
    elk._notifier.notify("connected", {})
    elk._connection.send_raw.assert_not_called()


def test_connected_sends_userid_and_password_for_a_secure_scheme():
    elk = _elk("elks://1.2.3.4:2601", userid="admin", password="secret")
    elk._connection.send_raw = MagicMock()
    elk._notifier.notify("connected", {})
    elk._connection.send_raw.assert_any_call("admin")
    elk._connection.send_raw.assert_any_call("secret")


def test_connected_triggers_sync_and_requests_ua_last():
    elk = _elk(element_list=["panel"])
    elk._connection.send = MagicMock()
    elk._notifier.notify("connected", {})

    sent_commands = [call.args[0].message[2:4] for call in elk._connection.send.call_args_list]
    assert sent_commands[-1] == "ua"


def test_sync_complete_fires_once_and_detaches_itself():
    elk = _elk(element_list=["panel"])
    elk._connection.send = MagicMock()
    completions = []
    elk.add_handler("sync_complete", lambda: completions.append(1))

    elk._notifier.notify("connected", {})  # arms the one-shot UA handler
    elk._notifier.notify("UA", {"user_code": 0, "valid_areas": 0, "diagnostic": "", "user_code_length": 0, "user_code_type": 0, "temperature_units": "F"})

    assert completions == [1]

    completions.clear()
    elk._notifier.notify(
        "UA", {"user_code": 0, "valid_areas": 0, "diagnostic": "", "user_code_length": 0, "user_code_type": 0, "temperature_units": "F"}
    )
    assert completions == []  # detached - a later, unrelated UA must not re-fire it
