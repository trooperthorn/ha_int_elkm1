"""Unit tests for helpers/elk/users.py's `User`/`Users`. Closes a gap left by
the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.elkm1.helpers.elk.notify import Notifier
from custom_components.elkm1.helpers.elk.users import Users


def _users() -> tuple[Users, MagicMock, Notifier]:
    connection = MagicMock()
    notifier = Notifier()
    users = Users(connection, notifier)
    connection.reset_mock()
    return users, connection, notifier


def test_sync_only_requests_names_no_code_data_is_ever_exposed():
    users, connection, _notifier = _users()
    users.sync()
    sent_commands = [call.args[0].message[2:4] for call in connection.send.call_args_list]
    assert sent_commands == ["sd"]


def test_username_returns_the_panel_configured_name():
    users, _connection, _notifier = _users()
    users[0].setattr("name", "Sean")
    assert users.username(0) == "Sean"


def test_username_returns_the_default_placeholder_for_an_unnamed_user():
    users, _connection, _notifier = _users()
    assert users.username(1) == users[1].default_name()


def test_username_returns_special_names_for_the_reserved_range():
    """0-based 200/201/202 (raw panel codes 201/202/203 - M1 Ver. 4.4.2+,
    spec section 4.16) - not simple placeholder-named array elements, a real
    bug found and fixed while adding this test (see docs/decisions.md
    2026-09-05: the general range check used to shadow these before the
    special-case comparisons were ever reached)."""
    users, _connection, _notifier = _users()
    assert users.username(200) == "*Program*"
    assert users.username(201) == "*Elk RP*"
    assert users.username(202) == "*Quick arm*"


def test_username_does_not_return_a_placeholder_name_for_the_reserved_indices():
    """The reserved indices must never fall through to a generic
    `Element-NNN`-style placeholder name, even though they are technically
    within the collection's array bounds."""
    users, _connection, _notifier = _users()
    for reserved in (200, 201, 202):
        name = users.username(reserved)
        assert not name.startswith("User-")


def test_username_returns_empty_string_for_an_unknown_number():
    users, _connection, _notifier = _users()
    assert users.username(9999) == ""
    assert users.username(-1) == ""
