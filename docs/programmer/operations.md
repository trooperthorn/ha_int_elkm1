# Operations

## Running the service

```bash
.venv/Scripts/python -m uvicorn elk_programmer.web.app:app --port 8765
```

The service binds to 127.0.0.1 only. Open `http://127.0.0.1:8765` in a
browser on the same machine. One account is open at a time; the account is
held in memory until saved.

## Account files

Account files are JSON under `~/workspace/elk-programmer-accounts/`. They
hold the panel's programming, the connection settings (host, port, serial
port, baud), and the panel identity as last read. They never hold the RP
access code, the database password, or user PINs beyond what the panel
record itself carries (user codes are panel programming and are stored the
way ElkRP stores them; treat the files accordingly).

## Importing from ElkRP

ElkRP keeps every account in `C:\ProgramData\RP\ElkAccts2.mdb`, a Jet
database under user-level security: the workgroup file `SOps2.mdw` in the
same folder, user name `ElkRP`, and a password that is the same in every
copy of ElkRP. The importer supplies the workgroup file and user name itself
and asks only for the password; it opens the file read only through the
Microsoft Access ODBC driver, present on 64-bit Windows as "Microsoft Access
Driver (*.mdb, *.accdb)". A plain database password without the workgroup
file fails with a permissions error.

A fresh ElkRP install ships ten template accounts (Custom, Defaults, and
Disabled for the EZ8, M1 Standard, and M1G, plus "Sample Account"). Importing
"M1G Defaults" gives the factory programming of an M1 Gold, a good starting
point for a new account and the reference this application's decoding was
checked against.

1. Close ElkRP; Jet does not like a second reader while ElkRP has the file
   open for writing.
2. In the GUI choose Import from ElkRP, keep the default path, enter the
   database password, and choose List accounts.
3. Pick the account and choose Import. The account name, panel identity,
   connection settings, and every modelled table are loaded. Save to a file.

Tables the model does not cover yet (report codes, wireless, rules, M1XEP
configuration) are not imported; see `backlog.md`.

## Connecting to a panel

Network: the M1XEP's non-secure port (2101 by default) on a trusted segment.
Serial: the panel's RS-232 port through a USB adapter, 115200 8N1 by
default; the panel's own baud is Global option G35 and must match.

Choose Connect, enter the RP access code, and log in. The code is sent once
and not retained. A successful login shows the firmware version and serial
number the panel reported. The session sends a keepalive every 15 seconds of
silence because the panel drops an idle programming session.

Live panel tools has Receive all from panel: it reads every mapped table
item by item into the open account, replacing the local copies, and reports
which records changed and which items the panel did not answer (a zone that
has no expander simply goes unanswered). Progress streams into the same pane
as the trace. Save the account afterwards; the receive does not write to
disk by itself.

Reading a record asks the panel for its current copy and shows the
difference from the account. Verify CRC asks the panel for the 16-bit CRC
it holds for that record and compares it with the CRC of the local bytes,
which is how ElkRP detects drift without reading the whole record. Sending a record first shows the exact frame
and asks for confirmation. Until the protocol has been qualified on a bench
panel, do not send to a production panel; see `live_qualification.md`.

## Serial port names

Windows: `COM3`. Linux: prefer the persistent `/dev/serial/by-id/...` path
over `/dev/ttyUSB0`.

## App mode

The same service runs inside the Home Assistant app in `elk_programmer_app/`.
It is selected with environment variables, none of which is a secret:

| Variable | Meaning |
| --- | --- |
| `ELK_PROGRAMMER_MODE` | `app` enables the allow-list, passphrase, sessions, audit log, and idle stop; anything else is standalone |
| `ELK_PROGRAMMER_DATA` | Directory for the passphrase hash, the audit log, and the `accounts/` folder; `/data` in the app |
| `ELK_PROGRAMMER_ALLOWED_USERS` | Comma-separated Home Assistant user ids permitted to use the programmer |
| `ELK_PROGRAMMER_IDLE_MINUTES` | Minutes without a request before the service stops the app through the Supervisor; 0 disables |
| `ELK_PROGRAMMER_READ_ONLY` | `true` refuses every write regardless of session state |
| `ELK_PROGRAMMER_HOST`, `ELK_PROGRAMMER_PORT` | Default panel address used when the connect request leaves them blank |

In app mode the service binds to all interfaces on port 8099 because only
the Supervisor's ingress proxy can reach the container; in standalone mode it
binds to 127.0.0.1:8765. The first visit in app mode asks for the app
passphrase; later visits ask for it to open a session, and again to enable
writes. The audit log is `audit.jsonl` under the data directory and the
`/api/audit` endpoint reports whether its hash chain is intact.
