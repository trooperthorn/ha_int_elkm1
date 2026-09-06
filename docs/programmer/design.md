# Design

## Why a local web service

ElkRP is a Windows Forms application with about seventy forms. Reproducing
each as native desktop UI would tie the replacement to one toolkit and one
platform. A Python service with a browser front end runs wherever Python and
a serial or network path to the panel exist, including a laptop at the
install, a Home Assistant host, or a container. The browser is the toolkit,
and the same service can later back a Home Assistant app.

## Why record specs drive everything

Every ElkRP form is, underneath, an editor for one fixed-size EEPROM record.
ElkRP stores those records in its database one column per byte, and that
column order is the byte order on the wire. A single specification per
record therefore serves the database importer, the JSON account file, the
wire encoder, the diff against the panel, and the generated editor form. Adding
a table means adding a spec, not a form.

Flag bytes stay bytes. Named bits are read and written through accessors so
that bits ElkRP never named are preserved through every round trip, which
matters when the panel firmware uses a bit the decompile did not label.

## Why the account is JSON

ElkRP keeps a Jet database with a shared password and its own conflict
resolution against the panel. A JSON file per account can be diffed, kept in
git, reviewed before a send, and read by any tool. Drift detection against the
panel uses the panel's own per-record CRC command, the same mechanism ElkRP
uses, without a local shadow database.

## Why every write is previewed

The protocol is reconstructed, not specified. Showing the operator the exact
frame, and refusing tables whose mapping is not traced, turns an unverified
reconstruction into something that can be checked one record at a time
against a bench panel and an ElkRP capture.

## Structure

- `model/specs.py`: the record specifications.
- `model/records.py`: encoding, decoding, bit access.
- `model/account.py`: the account container and JSON file.
- `storage/mdb_import.py`: the ElkRP database importer.
- `protocol/framing.py`: DLE framing and CRC.
- `protocol/messages.py`: request bodies and reply parsing.
- `protocol/session.py`: transports, retries, keepalive, trace.
- `protocol/panel.py`: which spec travels under which opcode.
- `web/app.py` and `web/static/index.html`: the service and the GUI.
- `data/`: Elk's own voice vocabulary and event tables, extracted from
  ElkRP's reference database.
