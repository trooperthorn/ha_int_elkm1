"""Importer tests against a fake row source; no Access driver needed."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from elk_programmer.model import specs
from elk_programmer.model.records import blank_record, record_to_columns
from elk_programmer.storage.mdb_import import import_account, list_accounts


class FakeSource:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "Accounts": [
                {
                    "Account": "Sample",
                    "Name": "Example",
                    "Notes": "",
                    "ControlType": "M1G",
                    "ControlSoftwareVersion": "5.3.18",
                    "ControlHardwareVersion": "",
                    "ControlBootVersion": "",
                    "ControlVoiceListVersion": "",
                    "ControlSerialNumber": "000000",
                    "IPAddress": "192.0.2.10",
                    "IPPort": 2601,
                    "NetNonSecure": 0,
                    "HasC1M1": 0,
                }
            ]
        }
        zone = blank_record(specs.ZONE)
        zone["ZnZoneName"] = "Garage"
        zone["ZnFunction"] = 4
        zone["ZnRCAlarm"] = 0x13
        row = {"Account": "Sample", "ZoneNum": 5, **record_to_columns(specs.ZONE, zone)}
        self.tables["ZoneDefinitions"] = [row]
        for spec in specs.ALL_SPECS:
            self.tables.setdefault(spec.table, [])

    def rows(
        self, table: str, columns: Iterable[str], where: str, params: tuple[Any, ...]
    ) -> list[Mapping[str, Any]]:
        cols = list(columns)
        out = []
        for row in self.tables[table]:
            if where and row.get("Account") != params[0]:
                continue
            out.append({c: row.get(c) for c in cols})
        return out


def test_list_and_import() -> None:
    src = FakeSource()
    assert list_accounts(src)[0]["Name"] == "Example"
    acct = import_account(src, "Sample")
    assert acct.connection.host == "192.0.2.10"
    assert acct.connection.port == 2601
    assert acct.connection.secure is True
    assert acct.identity.software_version == "5.3.18"
    assert acct.numbers("zone") == [5]
    zone = acct.record("zone", 5)
    assert zone["ZnZoneName"] == "Garage"
    assert zone["ZnFunction"] == 4
    assert zone["ZnRCAlarm"] == 0x13
