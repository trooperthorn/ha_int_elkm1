"""The account: one panel's complete programming, held in memory and on disk.

An account mirrors ElkRP's per-panel record: identity and connection
settings plus one list of decoded records per spec. It is serialised as a
single JSON document so it can be diffed, versioned, and inspected with any
editor, which ElkRP's Jet database never allowed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import specs
from .records import Record, blank_record

FORMAT_VERSION = 1


@dataclass
class Connection:
    """How to reach the panel. Secrets are never written to the account file."""

    method: str = "network"
    host: str = ""
    port: int = 2101
    secure: bool = False
    serial_port: str = ""
    baud: int = 115200


@dataclass
class PanelIdentity:
    control_type: str = "M1G"
    serial_number: str = ""
    software_version: str = ""
    hardware_version: str = ""
    boot_version: str = ""
    voice_list_version: str = ""


@dataclass
class Account:
    name: str = "New account"
    notes: str = ""
    identity: PanelIdentity = field(default_factory=PanelIdentity)
    connection: Connection = field(default_factory=Connection)
    tables: dict[str, dict[int, Record]] = field(default_factory=dict)
    rules_text: str = ""

    @classmethod
    def blank(cls, name: str = "New account") -> Account:
        acct = cls(name=name)
        for spec in specs.ALL_SPECS:
            acct.tables[spec.name] = {}
        acct.tables[specs.GLOBAL.name][1] = blank_record(specs.GLOBAL)
        for n in range(1, specs.AREA.count + 1):
            acct.tables[specs.AREA.name][n] = blank_record(specs.AREA)
        return acct

    def record(self, spec_name: str, number: int) -> Record:
        table = self.tables.setdefault(spec_name, {})
        if number not in table:
            table[number] = blank_record(specs.SPECS_BY_NAME[spec_name])
        return table[number]

    def numbers(self, spec_name: str) -> list[int]:
        return sorted(self.tables.get(spec_name, {}))

    def to_json(self) -> str:
        doc: dict[str, Any] = {
            "format": FORMAT_VERSION,
            "name": self.name,
            "notes": self.notes,
            "identity": asdict(self.identity),
            "connection": asdict(self.connection),
            "tables": {
                name: {str(n): _jsonable(rec) for n, rec in sorted(table.items())}
                for name, table in self.tables.items()
            },
            "rules_text": self.rules_text,
        }
        return json.dumps(doc, indent=1)

    @classmethod
    def from_json(cls, text: str) -> Account:
        doc = json.loads(text)
        if doc.get("format") != FORMAT_VERSION:
            raise ValueError(f"unsupported account format {doc.get('format')!r}")
        acct = cls(
            name=doc.get("name", ""),
            notes=doc.get("notes", ""),
            identity=PanelIdentity(**doc.get("identity", {})),
            connection=Connection(**doc.get("connection", {})),
            rules_text=doc.get("rules_text", ""),
        )
        for name, table in doc.get("tables", {}).items():
            spec = specs.SPECS_BY_NAME[name]
            acct.tables[name] = {int(n): _from_jsonable(spec, rec) for n, rec in table.items()}
        return acct

    def save(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Account:
        return cls.from_json(path.read_text(encoding="utf-8"))


def _jsonable(rec: Record) -> dict[str, Any]:
    return {k: (v.hex() if isinstance(v, bytes) else v) for k, v in rec.items()}


def _from_jsonable(spec: specs.RecordSpec, rec: dict[str, Any]) -> Record:
    out: Record = {}
    for f in (*spec.fields, *spec.extra):
        v = rec.get(f.name)
        if v is None:
            continue
        out[f.name] = bytes.fromhex(v) if f.kind is specs.Kind.BYTES else v
    return out
