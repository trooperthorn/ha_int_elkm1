"""Mapping between record specs and the wire: which opcode carries which table.

Only tables whose ElkRP send and receive path has been traced to a single
opcode, sub-code, item number, and fixed record size are mapped. Everything
else is reported as unmapped rather than guessed, so the GUI refuses to send
it. Citations are file and line in the decompiled M1G2/M1G tree; see
docs/protocol.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model import specs
from . import messages as m


@dataclass(frozen=True)
class WireMap:
    record: m.Record
    size: int
    sub: int = 0
    fixed_item: int | None = None
    note: str = ""

    def item(self, number: int) -> int:
        return self.fixed_item if self.fixed_item is not None else number


WIRE: dict[str, WireMap] = {
    specs.AREA.name: WireMap(m.Record.AREA, 24, note="Area_Definitions.cs 5795-5836, 6305-6350"),
    specs.ZONE.name: WireMap(
        m.Record.ZONE, 32, note="Zone_Definitions.cs 9726-9748, 10414-10489 (32 bytes on 4.0.0+)"
    ),
    specs.KEYPAD.name: WireMap(
        m.Record.KEYPAD, 28, sub=0, note="Keypad_Definitions.cs 10442-10499, 11098-11199 (page 0)"
    ),
    specs.USER.name: WireMap(m.Record.USER_CODE, 28, note="User_Codes.cs 7531-7536, 8093-8102"),
    specs.OUTPUT.name: WireMap(
        m.Record.DESCRIPTION, 28, sub=1, note="Outputs.cs 3788-3830, 4213-4258 (text class 1)"
    ),
    specs.TASK.name: WireMap(
        m.Record.DESCRIPTION, 28, sub=3, note="Tasks.cs 7130-7326 (text class 3 for tasks)"
    ),
    specs.TELEPHONE.name: WireMap(
        m.Record.TELEPHONE, 88, note="Telephone_Numbers.cs 8630-8638, 9222-9230"
    ),
    specs.GLOBAL.name: WireMap(
        m.Record.GLOBAL,
        48,
        sub=0,
        fixed_item=1,
        note="Globals_Data.cs 7969-8052, 8401-8476 (48 bytes above firmware 4.3)",
    ),
    specs.X10.name: WireMap(
        m.Record.X10, 28, sub=1, note="X10_Outputs.cs 4546-4672, 5029-5114 (count 1 per request)"
    ),
}

UNMAPPED_REASON: dict[str, str] = {
    specs.VOICE_MESSAGE.name: (
        "voice messages are read in pages (opcode 0x0D, Voice_Messages.cs 3432-3440); "
        "the page layout is not yet traced"
    ),
}


def wire_for(spec_name: str) -> WireMap:
    try:
        return WIRE[spec_name]
    except KeyError:
        raise LookupError(
            UNMAPPED_REASON.get(spec_name, f"{spec_name} has no wire mapping")
        ) from None
