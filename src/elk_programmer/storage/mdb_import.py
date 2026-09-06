"""Import an ElkRP account database (ElkAccts2.mdb) into an Account.

ElkRP keeps each EEPROM record as one database row with one column per byte,
so the import is a column-to-field mapping driven by the record specs. It
needs the Microsoft Access ODBC driver (present on Windows) and pyodbc; the
database password is the one ElkRP itself embeds and is supplied by the
caller, never stored here. See docs/operations.md for how to run this.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol

from ..model import specs
from ..model.account import Account, Connection, PanelIdentity
from ..model.records import record_from_columns
from .elksafe import crypt_columns, crypt_string, derive_key

ACCOUNT_COLUMNS = (
    "Account",
    "Name",
    "Notes",
    "ControlType",
    "ControlSoftwareVersion",
    "ControlHardwareVersion",
    "ControlBootVersion",
    "ControlVoiceListVersion",
    "ControlSerialNumber",
    "IPAddress",
    "IPPort",
    "NetNonSecure",
    "HasC1M1",
)


class RowSource(Protocol):
    """The subset of a database connection the importer needs; mockable."""

    def rows(
        self, table: str, columns: Iterable[str], where: str, params: tuple[Any, ...]
    ) -> list[Mapping[str, Any]]: ...


WORKGROUP_FILE = "SOps2.mdw"
WORKGROUP_USER = "ElkRP"


def connection_string(path: str, password: str, workgroup: str | None = None) -> str:
    """ODBC string for an ElkRP database.

    ElkRP secures its databases with Jet user-level security: a workgroup file
    next to the database and a fixed user name (Module1.cs 1583, 2754), so a
    plain database password is refused with a permissions error.
    """
    if workgroup is None:
        workgroup = str(Path(path).with_name(WORKGROUP_FILE))
    return (
        f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={path};"
        f"SystemDB={workgroup};UID={WORKGROUP_USER};PWD={password};"
    )


class OdbcSource:
    """RowSource over pyodbc. Imported lazily so the package works without it."""

    def __init__(self, path: str, password: str) -> None:
        import pyodbc

        self._conn = pyodbc.connect(connection_string(path, password), readonly=True)

    def rows(
        self, table: str, columns: Iterable[str], where: str, params: tuple[Any, ...]
    ) -> list[Mapping[str, Any]]:
        cols = ", ".join(f"[{c}]" for c in columns)
        sql = f"SELECT {cols} FROM [{table}]" + (f" WHERE {where}" if where else "")
        cur = self._conn.cursor()
        cur.execute(sql, params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()


def _version(value: Any) -> str:
    """ElkRP packs versions as an integer 0x00MMmmpp (5.2.6 is 0x050206)."""
    if value in (None, ""):
        return ""
    try:
        n = int(value)
    except TypeError, ValueError:
        return str(value)
    return f"{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


def list_accounts(source: RowSource) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in source.rows(
            "Accounts", ("Account", "Name", "ControlType", "ControlSerialNumber"), "", ()
        )
    ]


def import_account(source: RowSource, account_id: str) -> Account:
    """Read every programming table for one account id into a new Account."""
    head = source.rows("Accounts", ACCOUNT_COLUMNS, "[Account] = ?", (account_id,))
    if not head:
        raise KeyError(f"account {account_id} not found")
    h = head[0]
    acct = Account(
        name=str(h.get("Name") or account_id),
        notes=str(h.get("Notes") or ""),
        identity=PanelIdentity(
            control_type=str(h.get("ControlType") or ""),
            serial_number=str(h.get("ControlSerialNumber") or ""),
            software_version=_version(h.get("ControlSoftwareVersion")),
            hardware_version=_version(h.get("ControlHardwareVersion")),
            boot_version=_version(h.get("ControlBootVersion")),
            voice_list_version=_version(h.get("ControlVoiceListVersion")),
        ),
        connection=Connection(
            method="network" if h.get("IPAddress") else "serial",
            host=str(h.get("IPAddress") or ""),
            port=int(h.get("IPPort") or 2101),
            secure=not bool(h.get("NetNonSecure")),
        ),
    )
    acct.identity.serial_number = _decrypt_text(account_id, h.get("ControlSerialNumber"))
    for spec in specs.ALL_SPECS:
        columns: list[str] = []
        if spec.key:
            columns.append(spec.key)
        for f in (*spec.fields, *spec.extra):
            columns.extend(f.column_names())
        rows = source.rows(spec.table, columns, "[Account] = ?", (account_id,))
        table: dict[int, Any] = {}
        for row in rows:
            number = int(row[spec.key]) if spec.key else 1
            table[number] = record_from_columns(spec, _decrypt_row(spec, account_id, dict(row)))
        acct.tables[spec.name] = table
    return acct


def _decrypt_row(spec: specs.RecordSpec, account_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """Undo ElkRP's RC4 on the rows it encrypts; other rows pass through.

    User code rows: all 28 record columns, key mixed with the code number
    (User_Codes.cs 2419-2427). Globals: the 48 record columns followed by
    AntiTakeover as a 49th byte, key from the account id only (Globals_Data.cs
    2666, 5023-5107).
    """
    if spec.name == specs.USER.name:
        key = derive_key(account_id, str(row[spec.key]))
        cols = [c for f in spec.fields for c in f.column_names()]
    elif spec.name == specs.GLOBAL.name:
        key = derive_key(account_id)
        cols = [c for f in spec.fields for c in f.column_names()] + ["AntiTakeover"]
    else:
        return row
    values = crypt_columns(key, [int(row.get(c) or 0) for c in cols])
    return {**row, **dict(zip(cols, values, strict=True))}


def _decrypt_text(account_id: str, value: Any) -> str:
    """``CryptString`` columns: serial number and MAC address (Account_Details.cs 3756-3764)."""
    if not value:
        return ""
    text = str(value)
    # Jet returns the stored ANSI characters as Unicode; map them back to the bytes
    # ElkRP wrote before applying the keystream.
    raw = text.encode("cp1252", errors="replace").decode("latin-1")
    return crypt_string(derive_key(account_id), raw).strip()
