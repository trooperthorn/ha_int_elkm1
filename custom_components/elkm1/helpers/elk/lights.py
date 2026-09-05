"""PLC/X10 lighting element and collection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import Max, TextDescriptions
from .elements import Element, Elements
from .message import pc_encode, pf_encode, pn_encode, ps_encode, pt_encode
from .notify import Notifier

if TYPE_CHECKING:
    from .connection import Connection


class Light(Element):
    """One PLC/X10 lighting device."""

    def __init__(self, index: int, connection: Connection, notifier: Notifier) -> None:
        super().__init__(index, connection, notifier)
        self.status = 0

    def level(self, level: int, time: int = 0) -> None:
        """Set this light to a level (0 = off, >=98 = fully on, else dimmed)."""
        if level <= 0:
            self._connection.send(pf_encode(self._index))
        elif level >= 98:
            self._connection.send(pn_encode(self._index))
        else:
            self._connection.send(pc_encode(self._index, 9, level, time))

    def toggle(self) -> None:
        """Toggle this light."""
        self._connection.send(pt_encode(self._index))


class Lights(Elements[Light]):
    """All 256 possible PLC/X10 lighting devices."""

    def __init__(self, connection: Connection, notifier: Notifier) -> None:
        super().__init__(connection, notifier, Light, Max.LIGHTS.value)
        notifier.attach("PC", self._pc_handler)
        notifier.attach("PS", self._ps_handler)

    def sync(self) -> None:
        """Request current status (all 4 banks) and names for every light."""
        for i in range(4):
            self._connection.send(ps_encode(i))
        self.get_descriptions(TextDescriptions.LIGHT.value)

    def _pc_handler(self, housecode: str, index: int, light_level: int) -> None:
        self.elements[index].setattr("status", light_level, True)

    def _ps_handler(self, bank: int, statuses: list[int]) -> None:
        for i in range(bank * 64, (bank + 1) * 64):
            self.elements[i].setattr("status", statuses[i - bank * 64], True)
