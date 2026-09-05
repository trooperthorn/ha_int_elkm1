"""User element and collection (names only - no code data is ever exposed)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import Max, TextDescriptions
from .elements import Element, Elements
from .notify import Notifier

if TYPE_CHECKING:
    from .connection import Connection


class User(Element):
    """One user (name only)."""


class Users(Elements[User]):
    """All users."""

    def __init__(self, connection: Connection, notifier: Notifier) -> None:
        super().__init__(connection, notifier, User, Max.USERS.value)

    def sync(self) -> None:
        """Request names for every user."""
        self.get_descriptions(TextDescriptions.USER.value)

    def username(self, user_number: int) -> str:
        """Return the panel-configured name for a user number, or a special
        name for the reserved raw codes 201/202/203 (Program/ElkRP/Quick-arm
        - M1 Ver. 4.4.2+, spec section 4.16), or "" if unknown.

        `user_number` is 0-based like every other index in this codebase
        (`ic_decode` already subtracts 1 from the panel's raw UUU field), so
        the reserved raw codes are checked here as 200/201/202. Checking
        them before the general range lookup matters: `Max.USERS.value` is
        203, so `0 <= user_number < self.max_elements` alone would silently
        shadow 200-202 with a placeholder `Element.name` instead of ever
        reaching these special names - a real bug found while adding this
        module's tests, fixed 2026-09-05 (see docs/decisions.md).
        """
        if user_number == 200:
            return "*Program*"
        if user_number == 201:
            return "*Elk RP*"
        if user_number == 202:
            return "*Quick arm*"
        if 0 <= user_number < self.max_elements:
            return self.elements[user_number].name
        return ""
