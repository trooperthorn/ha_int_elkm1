# Decisions

## 2026-09-06, reconstruct the RP protocol from the decompile rather than capture it

ElkRP still runs on the workstation and could in principle be captured on a
serial line, but a capture shows only the exchanges one session happens to
make. The decompiled source gives the complete opcode set, the retry rules,
the login layout, and the keepalive, with line citations. Rejected: building
the GUI first against a stubbed protocol, because the value of the tool is the
live path and a stub would have hidden the unverified parts.

## 2026-09-06, database column order is the record layout

`M1CtlHdr.cs` has no layout attributes, so struct sizes there are estimates.
The database columns are what ElkRP round-trips, and the forms copy the same
byte arrays to the wire. Cross-checks that hold: the globals DST bytes at
offsets 31 to 34 in both the column order and `Globals_Data.cs`; user code,
area, zone, keypad page 0, and telephone sizes match the copy loops exactly.
Rejected: deriving offsets from the structs.

## 2026-09-06, plain TCP and serial only

The secure network login and the AES transport rely on keys embedded in
ElkRP; see `security.md`. Rejected until there is a reason to believe those
modes add protection rather than the appearance of it.

## 2026-09-06, the record layouts are validated against ElkRP's shipped data

Importing the "M1G Defaults" template from ElkRP's own database, after
reproducing its RC4 obfuscation, decoded the Installer Program Code as
172839 and user 1 as 123456 with Master, Arm, Disarm, and Bypass set, the
code lockout as 99 (the form labels 99 as disabled), zones 1 and 2 as
Entry/Exit 1 with sequential voice word ids, area exit and entry delays as
60 and 30 seconds, and every name column as readable text. Those are the
factory values the installation manual documents, so the zone, area, keypad
page 0, user, output, task, globals, and lighting layouts in `specs.py` are
now verified against ElkRP's data. The wire layouts remain unverified until
a live read. Rejected: treating the decompiled struct sizes as authoritative;
they disagree with the copy loops for outputs, tasks, and lighting.

## 2026-09-06, RP access codes are not imported

`Account_Details.cs` decrypts `RPAccCode1` to `RPAccCode3` into memory for
the login. This importer reads the serial number and leaves the RP code
columns untouched, so the account file never carries the credential; the
operator enters it at login. Rejected: importing it for convenience.

## 2026-09-06, no commit of the RP code, database password, or user PINs

Accepted per request and discarded. The trace is the one place the login
digits appear, and it stays in memory.
