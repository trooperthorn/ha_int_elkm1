# ELK-M1 RS-232 ASCII Protocol v1.90 coverage

This matrix distinguishes the M1 wire protocol from the Home Assistant feature surface.
“Implemented” means `helpers/elk/message.py` (this repository's own protocol
implementation since the `elkm1-lib` dependency was removed 2026-09-05 - see
`docs/decisions.md`) can encode/decode the message and this repository has a defined
consumer. It does not mean a physical panel has been qualified; see `live_qualification.md`.

| Family | Commands | Status |
|---|---|---|
| Area arm/disarm | `a0`-`a6`, `as`/`AS` | Implemented; arm/disarm requires matching validated `AS` |
| Advanced arm stepping/force | `a7`-`a:` | Encodable via `helpers/elk/message.py`'s `al_encode` (`ArmLevel.ARM_TO_NEXT_AWAY_MODE`/`ARM_TO_NEXT_STAY_MODE`/`FORCE_ARM_TO_AWAY_MODE`/`FORCE_ARM_TO_STAY_MODE` all accepted); the coordinator's `_execute_arm_cmd` never calls it with these levels, so no HA action reaches them - a scope choice, not an implementation gap |
| Alarm by zone | `az`/`AZ` | Implemented; used in initial and bounded status refresh |
| Area alarm memory/timers | `AM`, `EE` | Implemented, including symbolic alarms and timer type |
| Output control/status | `cf`, `cn`, `cs`/`CS`, `ct`, `CC` | Implemented for outputs 1-208; 65-208 disabled by default |
| Custom values | `cp`, `cr`/`CR`, `cw` | Implemented; writes require matching `CR` |
| Counters | `cv`/`CV`, `cx` | Implemented; reads/writes require matching `CV` |
| Keypads | `ka`/`KA`, `kf`/`KF` | Receive/control implemented |
| Keypad status update | `kc`/`KC` | `kc_encode` exists (v1.90's "Request Keypad Status Update", covering illumination and the "Bypass Key Requires User Code" bit) and is verified against real hardware (`docs/live_qualification.md`), but nothing in this repository calls it yet - `Keypads.sync()` sends `ka`/`sd`/`kf(0)` only. Unsolicited `KC` broadcasts are still decoded with all v1.90 fields preserved, but only arrive if Global Programming G40 ("Keypad Changes") is enabled on the panel |
| Log | `LD`, `ld` | Both directions implemented: `ld_encode` (indexed log request, 1=newest/511=oldest/0=next write slot) is verified against real hardware, but nothing in this repository calls it yet. `LD` broadcasts now fire an `elkm1.log_event` HA event with a human-readable description (`event_log.py`, sourced from Elk's own ElkRP tool - see docs/decisions.md 2026-09-05), not just the bare numeric event code. Write `le` remains not exposed |
| Temperatures | `lw`/`LW`, `ST`, `st` | `st_encode` (direct request for one probe/keypad/thermostat) is implemented and verified against real hardware, but nothing in this repository calls it yet - `Panel.sync()`/`Keypads.sync()` rely on the broadcast `lw`/`ST` path only |
| PLC lighting | `pc`/`PC`, `pf`, `pn`, `ps`/`PS`, `pt` | Implemented, including unit `00` aggregate broadcasts |
| ELKRP coexistence | `RP` | Implemented; paused writes fail closed |
| Real-time clock | `rw`/`RR`, `rr`, `XK` | Clock write and responses implemented. `rr_encode` (direct RTC read) exists and is verified against real hardware, but nothing in this repository calls it yet - `Panel`'s only RTC-related send is `rw` (set time). `XK` (the unsolicited every-30-seconds broadcast) is received and decoded; the acknowledgment reply `xk` has no encoder in `helpers/elk/message.py` and is never sent - deliberately, since sending it would claim to be a working M1XEP/C1M1 IP communicator, which this integration is not. Per the RS-232 spec section 4.4.4, a real XEP's missing `xk` reply only becomes an "Ethernet Trouble" condition if that Ethernet module was enrolled via Bus Module Enrollment in the first place, so a direct-serial-only setup (nothing enrolled) does not get a spurious trouble from this |
| Text descriptions | `sd`/`SD` | Implemented, including high-bit Show-on-Keypad flag |
| System trouble | `ss`/`SS` | Implemented, including embedded zone/device numbers |
| Voice | `sw`, `sp` | Implemented as queued/unconfirmed commands; protocol has no ack |
| Tasks | `TC`, `tn` | Implemented; activation is queued/unconfirmed by protocol design |
| Thermostats | `tr`/`TR`, `ts` | Implemented; operations require matching `TR` |
| User-code area validation | `ua`/`UA`, `IC` | Decode/sync implemented; user-code modification is not exposed |
| Version | `vn`/`VN` | Implemented and used for identity/baud validation |
| Zone status/control | `zb`/`ZB`, `ZC`, `zd`/`ZD`, `zp`/`ZP`, `zs`/`ZS`, `zv`/`ZV`, `zt` | Implemented; `ZS` is initial-sync only except area-bypass reconciliation, which `helpers/elk/zones.py`/`areas.py` still requires |
| Audio/touchscreen | `ca`/`CA`, `cd`/`CD` | Intentionally unsupported; no current HA feature contract |
| Thermostat (Omnistat 2) | `t2`/`T2` | Not implemented: no encoder/decoder in `helpers/elk/message.py`, and no handler in this repository. Distinct from "intentionally unsupported" above - this family has simply never been wired up, not evaluated and declined |
| Touchscreen information routing | `ti` | Decode only: `ti_decode` exists (Rev 1.90's only functional addition over Rev 1.88, section 4.43) and passes the routed string through verbatim; no `ti_encode` since no Elk Touchscreen consumer is in scope for this integration - see `message.py`'s own module docstring |
| Insteon programming | `ir`/`IR`, `ip`/`IP` | Intentionally unsupported; programming belongs in installer tooling |
| User-code modification | `cu`/`CU` | Intentionally unsupported pending a separate security design and live qualification |
| Manufacturer-internal | `AP`, `AR`/`ar`/`ax`, `DS`/`ds`, `EM`, `RE`, `XB` | Prohibited or reserved by the manufacturer; must not be emitted |
| Installer mode exit | `IE` | Consumed internally by `helpers/elk/hub.py` (`Elk.__init__` attaches `IE` to `_call_sync_handlers`, a full resync trigger) so a config or user-code change made from a keypad in installer mode is picked up promptly; not exposed as a distinct HA-visible fact |
| Undocumented codes | `AT`, `NS`, `NZ`, `DK` | The now-removed `elkm1-lib` dependency's `MESSAGE_MAP` used to carry these four codes ("Ethernet Test Acknowledge", "Reply Source Name", "Reply Zone Name", "Display KP LCD Data, not used") with no matching entry anywhere in the ELK-M1 RS-232 ASCII Protocol Rev 1.90 spec. This repository's own `helpers/elk/message.py` deliberately does not carry them forward - they were never verified against the primary source, so a checksum-valid frame for any of them now falls through `decode()`'s generic `("unknown", {...})` path instead of being specially interpreted |

Unknown checksum-valid frames are logged/ignored for forward compatibility. Malformed,
bad-length, bad-checksum, overlength, or unterminated frames are rejected and cannot satisfy
an awaited response.
