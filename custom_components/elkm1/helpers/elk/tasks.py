"""Automation task element and collection."""

from __future__ import annotations

from time import time
from typing import TYPE_CHECKING

from .const import Max, TextDescriptions
from .elements import Element, Elements
from .message import tn_encode
from .notify import Notifier

if TYPE_CHECKING:
    from .connection import Connection


class Task(Element):
    """One automation task."""

    def __init__(self, index: int, connection: Connection, notifier: Notifier) -> None:
        super().__init__(index, connection, notifier)
        self.last_change: float | None = None

    def activate(self) -> None:
        """Activate this task."""
        self._connection.send(tn_encode(self._index))


class Tasks(Elements[Task]):
    """All tasks."""

    def __init__(self, connection: Connection, notifier: Notifier) -> None:
        super().__init__(connection, notifier, Task, Max.TASKS.value)
        notifier.attach("TC", self._tc_handler)

    def sync(self) -> None:
        """Request names for every task."""
        self.get_descriptions(TextDescriptions.TASK.value)

    def _tc_handler(self, task: int) -> None:
        self.elements[task].setattr("last_change", time(), True)
