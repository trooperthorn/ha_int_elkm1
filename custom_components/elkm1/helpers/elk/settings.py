"""Custom-value ("Setting") element and collection.

`Setting.value` is `None` until a `CR` message arrives - the same class of
"genuinely not known yet" state as `Counter.value`; see counters.py and
docs/decisions.md 2026-09-05.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import Max, SettingFormat, TextDescriptions
from .elements import Element, Elements
from .message import cp_encode, cw_encode
from .notify import Notifier

if TYPE_CHECKING:
    from .connection import Connection


class Setting(Element):
    """One custom value."""

    def __init__(self, index: int, connection: Connection, notifier: Notifier) -> None:
        super().__init__(index, connection, notifier)
        self.value_format = SettingFormat.NUMBER
        self.value: int | tuple[int, int] | None = None

    def set(self, value: int | tuple[int, int]) -> None:
        """Write this custom value."""
        if isinstance(value, tuple):
            if self.value_format != SettingFormat.TIME_OF_DAY:
                raise ValueError("Custom setting 'set' value is wrong format for Elk")
        elif self.value_format == SettingFormat.TIME_OF_DAY:
            raise ValueError("Custom setting 'set' for time of day must have tuple.")
        self._connection.send(cw_encode(self._index, value, self.value_format))


class Settings(Elements[Setting]):
    """All custom values."""

    def __init__(self, connection: Connection, notifier: Notifier) -> None:
        super().__init__(connection, notifier, Setting, Max.SETTINGS.value)
        notifier.attach("CR", self._cr_handler)

    def sync(self) -> None:
        """Request every custom value's current value and name."""
        self._connection.send(cp_encode())
        self.get_descriptions(TextDescriptions.SETTING.value)

    def _cr_handler(self, values: list[dict[str, Any]]) -> None:
        settings = self.elements
        for value in values:
            setting = settings[value["index"]]
            setting.setattr("value_format", value["value_format"], False)
            setting.setattr("value", value["value"], True)
