"""Counter element and collection.

`Counter.value` is `None` until a `CV` message arrives - not a bug, the
value genuinely isn't known yet. Consumers (see `number.py`'s
`native_value`) must check for `None` before using it; see
docs/decisions.md 2026-09-05 for the incident this caused before that
guard existed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import Max, TextDescriptions
from .elements import Element, Elements
from .message import cv_encode, cx_encode
from .notify import Notifier

if TYPE_CHECKING:
    from .connection import Connection


class Counter(Element):
    """One counter (a general-purpose numeric register)."""

    def __init__(self, index: int, connection: Connection, notifier: Notifier) -> None:
        super().__init__(index, connection, notifier)
        self.value: int | None = None

    def get(self) -> None:
        """Request this counter's current value."""
        self._connection.send(cv_encode(self._index))

    def set(self, value: int) -> None:
        """Write this counter's value."""
        self._connection.send(cx_encode(self._index, value))

    def _configured_was_set(self) -> None:
        self._connection.send(cv_encode(self.index), priority_send=True)


class Counters(Elements[Counter]):
    """All counters."""

    def __init__(self, connection: Connection, notifier: Notifier) -> None:
        super().__init__(connection, notifier, Counter, Max.COUNTERS.value)
        notifier.attach("CV", self._cv_handler)

    def sync(self) -> None:
        """Request names for every counter; values are fetched on demand."""
        self.get_descriptions(TextDescriptions.COUNTER.value)

    def _cv_handler(self, counter: int, value: int) -> None:
        self.elements[counter].setattr("value", value, True)
