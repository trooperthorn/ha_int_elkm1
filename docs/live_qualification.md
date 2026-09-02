# ELK-M1 live release qualification

CI verifies Home Assistant contracts and simulated lifecycle behavior. It does not prove
that a physical panel, XEP, credential set, USB adapter, or site network works. Record the
panel/XEP firmware, adapter identity, Core version, Python version, topology, and elapsed
time for every live run. Never include credentials or PINs in evidence.

## Required release matrix

- Secure XEP: accepted credentials, rejected credentials, corrected credentials via
  reauth, timeout classification, reconnect after XEP reboot, and address change.
- Non-secure XEP: discovery, manual entry, push updates, the bounded AS/AZ/CS/SS/LW
  status refresh, panel power
  cycle, and Home Assistant reload/unload during reconnect.
- Direct serial: every claimed panel baud (including 14400), cached-baud reconnect,
  unrelated valid traffic arriving before the VN probe reply, wrong-baud recovery,
  unload during probe/reconnect, and persistent `by-id`/`by-path` identity.
- USB reassignment: reboot/replug with the adapter assigned a different transient tty;
  confirm the persistent endpoint and duplicate policy still identify the same panel.
- Multi-panel: configure two real panels, verify distinct identities/prefix routing, and
  unload/reload either entry without affecting the other.
- Soak: 24 hours with push traffic and bounded status refresh enabled; record reconnect count,
  last failure category, task/timer/socket cleanup, and missed or duplicated events.

## Release decision

A release is qualified only when hassfest, HACS validation, Ruff, strict mypy, and the
full pytest suite pass on exact Core 2026.8.3/Python 3.14, and every applicable live item
above has current evidence. Mocked config-flow success is configuration-contract evidence
only, never proof of a live alarm-panel connection.

The periodic refresh deliberately does not issue `zs`; protocol v1.90 says that request
should be used for initial connection. Zone logical state is initialized by `ZS` during the
library sync and maintained by checksum-valid `ZC` push messages. A release qualification
must verify Global G36 zone-change transmission and explicitly record this dependency.
