"""Bulk transfer between the panel and the account: receive all, send changed.

A receive reads every mapped table item by item, decodes each record, and
merges it into the account while reporting what differed from the local copy.
ElkRP does the same thing one form at a time; the only difference here is
that unanswered items are recorded rather than treated as fatal, so a panel
without an expander simply yields fewer records.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..model import specs
from ..model.account import Account
from ..model.records import decode_record, encode_record
from . import messages as m
from .panel import WIRE
from .session import Session, SessionError, Timeout, WrongReply

Progress = Callable[[str, int, int, str], None]

RECEIVE_ORDER = (
    "global",
    "area",
    "keypad",
    "zone",
    "user",
    "output",
    "task",
    "telephone",
    "lighting",
)


@dataclass
class ReceiveReport:
    read: dict[str, int] = field(default_factory=dict)
    changed: dict[str, list[int]] = field(default_factory=dict)
    unanswered: dict[str, list[int]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def item_range(spec: specs.RecordSpec, limit: int | None = None) -> range:
    count = spec.count if limit is None else min(spec.count, limit)
    return range(spec.first, spec.first + count)


async def receive_all(
    session: Session,
    account: Account,
    progress: Progress | None = None,
    tables: tuple[str, ...] = RECEIVE_ORDER,
    limits: dict[str, int] | None = None,
) -> ReceiveReport:
    """Read every mapped record into the account. Local edits are overwritten."""
    report = ReceiveReport()
    for name in tables:
        spec = specs.SPECS_BY_NAME[name]
        wire = WIRE.get(name)
        if wire is None:
            report.errors.append(f"{name}: no wire mapping")
            continue
        items = list(item_range(spec, (limits or {}).get(name)))
        total = len(items)
        for i, number in enumerate(items, start=1):
            try:
                raw = await session.read_record(wire.record, wire.item(number), wire.size, wire.sub)
            except Timeout:
                report.unanswered.setdefault(name, []).append(number)
                if progress:
                    progress(name, i, total, f"{spec.label} {number}: no reply")
                continue
            except WrongReply as err:
                report.unanswered.setdefault(name, []).append(number)
                report.errors.append(f"{spec.label} {number}: {err}")
                if progress:
                    progress(name, i, total, f"{spec.label} {number}: {err}")
                continue
            except SessionError as err:
                report.errors.append(f"{spec.label} {number}: {err}; receive stopped")
                return report
            decoded = decode_record(spec, raw)
            local = account.tables.setdefault(name, {}).get(number)
            if local is None or encode_record(spec, local) != raw:
                report.changed.setdefault(name, []).append(number)
            if local is None:
                account.tables[name][number] = decoded
            else:
                local.update(decoded)
            report.read[name] = report.read.get(name, 0) + 1
            if progress:
                progress(name, i, total, f"{spec.label} {number}")
    return report


async def send_record(session: Session, account: Account, name: str, number: int) -> bytes:
    """Write one record and return the raw reply body."""
    spec = specs.SPECS_BY_NAME[name]
    wire = WIRE[name]
    payload = encode_record(spec, account.record(name, number))
    return await session.send_receive(
        m.write_record(wire.record, wire.item(number), payload, wire.sub)
    )


async def verify_record(
    session: Session, account: Account, name: str, number: int
) -> tuple[int, int]:
    """Return (panel CRC, local CRC) for one record using the panel's 0x7E command."""
    from .framing import crc16

    spec = specs.SPECS_BY_NAME[name]
    wire = WIRE[name]
    panel_crc = await session.record_crc(wire.record, wire.item(number))
    local_crc = crc16(encode_record(spec, account.record(name, number)))
    return panel_crc, local_crc
