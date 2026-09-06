# Backlog

Dated open items.

- 2026-09-06, live qualification against a bench panel: login, keepalive,
  read Area 1 and compare with ElkRP's copy, read Zone 1, read Globals, read
  the group CRC table, disconnect. Nothing is written until reads match.
- 2026-09-06, reply header bytes 1 to 3 for record reads are unverified; the
  session accepts any values.
- 2026-09-06, keypad page 1 (function key task and light bindings, key names,
  120 bytes under opcode 0x04 sub 1) is not modelled; the database stores the
  key names as text columns, not per-byte columns, so it needs its own spec.
- 2026-09-06, voice messages: opcode 0x0D paging not traced.
- 2026-09-06, report codes: system, keypad panic, per zone, per user, per
  area (opcodes 0x09 to 0x0C and 0x10). The database columns exist in the
  zone, user, and area tables; the wire records are separate.
- 2026-09-06, tasks form also carries counters, thermostats, custom settings,
  and cutoff timers under opcode 0x02 sub-codes 2 and 0; not modelled.
- 2026-09-06, wireless zones: three 260-byte blocks under opcode 0x0F.
- 2026-09-06, rules and text packets: opcode 0x79, 528 packets; the
  WHENEVER/AND/THEN vocabulary is catalogued in the ElkRP feature catalog and
  needs a decoder before an editor.
- 2026-09-06, the globals record bytes 36 to 46 (database columns S16 to
  SDF) are carried opaquely; their meanings are in `Globals_Data.cs` but
  not yet traced.
- 2026-09-06, the decrypted serial number of ElkRP's "Sample Account" comes
  back with one non-ASCII character; the ANSI code page round trip of
  `CryptString` output through Jet is probably wrong for bytes 0x80 to 0x9F.
  Check against a real account once one exists.
- 2026-09-06, the telephone number digit encoding for pause and special
  characters is unverified.
- 2026-09-06, keypad flag byte 3 maps enum names A to F onto F1 to F6 by
  assumption; verify against the form's control bindings.
- 2026-09-06, the integration should raise a Repair issue when its entry is disabled
  with no programming claim active, and the claim services should note that on serial
  the entry is disabled rather than paused.
- 2026-09-06, the integration side of the session claim: `elkm1.programming_session_start`
  and `_end` services, the `remote_programming` binary sensor, the two events, and the
  Repair issues, as specified in `app.md`; then the app's calls to them through the core
  API proxy.
- 2026-09-06, the app Dockerfile installs the service from `main`; once a release
  that contains the service exists, install from the release tag (`v${BUILD_VERSION}`)
  so the app version and the service version are the same commit.
- 2026-09-06, publish the app image (the Dockerfile installs the service from the
  GitHub repository, which does not exist yet) and add the release baseline to both
  repositories.
- 2026-09-06, confirm on a real Supervisor whether a non-admin user who knows the
  ingress URL is refused; the allow-list does not depend on it but the docs say unverified.
- 2026-09-06, the ASCII automation protocol (from `ha_int_elkm1`'s
  `helpers/elk`) could give this tool a live status view like ElkRP's
  Control Status screen; not started.
- 2026-09-06, M1XEP configuration, firmware programming, dial-up, ElkLink,
  and M1Cloud are out of scope until the core is qualified.
