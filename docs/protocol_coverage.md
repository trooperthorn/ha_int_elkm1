# ELK-M1 RS-232 ASCII Protocol v1.90 coverage

This matrix distinguishes the M1 wire protocol from the Home Assistant feature surface.
“Implemented” means the integration or pinned `elkm1-lib 2.2.15` can encode/decode the
message and this repository has a defined consumer. It does not mean a physical panel has
been qualified; see `live_qualification.md`.

| Family | Commands | Status |
|---|---|---|
| Area arm/disarm | `a0`-`a6`, `as`/`AS` | Implemented; arm/disarm requires matching validated `AS` |
| Advanced arm stepping/force | `a7`-`a:` | Encodable via `elkm1-lib` (`ArmLevel.ARM_TO_NEXT_AWAY_MODE`/`ARM_TO_NEXT_STAY_MODE`/`FORCE_ARM_TO_AWAY_MODE`/`FORCE_ARM_TO_STAY_MODE`, all accepted by `al_encode`); the coordinator's `_execute_arm_cmd` never calls it with these levels, so no HA action reaches them - a scope choice, not a library limitation |
| Alarm by zone | `az`/`AZ` | Implemented; used in initial and bounded status refresh |
| Area alarm memory/timers | `AM`, `EE` | Implemented, including symbolic alarms and timer type |
| Output control/status | `cf`, `cn`, `cs`/`CS`, `ct`, `CC` | Implemented for outputs 1-208; 65-208 disabled by default |
| Custom values | `cp`, `cr`/`CR`, `cw` | Implemented; writes require matching `CR` |
| Counters | `cv`/`CV`, `cx` | Implemented; reads/writes require matching `CV` |
| Keypads | `ka`/`KA`, `kf`/`KF` | Receive/control implemented |
| Keypad status update | `kc`/`KC` | Receive-only: `elkm1-lib` 2.2.15 has no `kc` encoder, so the request (v1.90's "Request Keypad Status Update", covering illumination and the "Bypass Key Requires User Code" bit) is never sent. Unsolicited `KC` broadcasts are still decoded with all v1.90 fields preserved, but only arrive if Global Programming G40 ("Keypad Changes") is enabled on the panel |
| Log | `LD` | Receive implemented; indexed `ld` and write `le` not exposed |
| Temperatures | `lw`/`LW`, `ST` | Implemented; direct `st` request not exposed |
| PLC lighting | `pc`/`PC`, `pf`, `pn`, `ps`/`PS`, `pt` | Implemented, including unit `00` aggregate broadcasts |
| ELKRP coexistence | `RP` | Implemented; paused writes fail closed |
| Real-time clock | `rw`/`RR`, `XK`/`xk` | Clock write and responses implemented; direct `rr` not exposed |
| Text descriptions | `sd`/`SD` | Implemented, including high-bit Show-on-Keypad flag |
| System trouble | `ss`/`SS` | Implemented, including embedded zone/device numbers |
| Voice | `sw`, `sp` | Implemented as queued/unconfirmed commands; protocol has no ack |
| Tasks | `TC`, `tn` | Implemented; activation is queued/unconfirmed by protocol design |
| Thermostats | `tr`/`TR`, `ts` | Implemented; operations require matching `TR` |
| User-code area validation | `ua`/`UA`, `IC` | Decode/sync implemented; user-code modification is not exposed |
| Version | `vn`/`VN` | Implemented and used for identity/baud validation |
| Zone status/control | `zb`/`ZB`, `ZC`, `zd`/`ZD`, `zp`/`ZP`, `zs`/`ZS`, `zv`/`ZV`, `zt` | Implemented; `ZS` is initial-sync only except library-required area-bypass reconciliation |
| Audio/touchscreen | `ca`/`CA`, `cd`/`CD` | Intentionally unsupported; no current HA feature contract |
| Thermostat (Omnistat 2) | `t2`/`T2` | Not implemented: no encoder/decoder anywhere in `elkm1-lib` 2.2.15, and no handler in this repository. Distinct from "intentionally unsupported" above - this family has simply never been wired up, not evaluated and declined |
| Touchscreen information routing | `ti` | Not implemented: `elkm1-lib` 2.2.15 predates ELK-M1 protocol Rev 1.90 (Jul 8, 2026), which added this command in section 4.43 as its only functional change from Rev 1.88. The pinned library's `const.py` `MESSAGE_MAP` has no `ti`/`TI` entry at all |
| Insteon programming | `ir`/`IR`, `ip`/`IP` | Intentionally unsupported; programming belongs in installer tooling |
| User-code modification | `cu`/`CU` | Intentionally unsupported pending a separate security design and live qualification |
| Manufacturer-internal | `AP`, `AR`/`ar`/`ax`, `DS`/`ds`, `EM`, `RE`, `XB` | Prohibited or reserved by the manufacturer; must not be emitted |
| Installer mode exit | `IE` | Consumed internally by `elkm1-lib` (`elk.py` attaches `IE` to a full resync trigger) so a config or user-code change made from a keypad in installer mode is picked up promptly; not exposed as a distinct HA-visible fact |
| Undocumented library codes | `AT`, `NS`, `NZ`, `DK` | `elkm1-lib`'s `MESSAGE_MAP` carries these four codes ("Ethernet Test Acknowledge", "Reply Source Name", "Reply Zone Name", "Display KP LCD Data, not used") with no matching entry anywhere in the ELK-M1 RS-232 ASCII Protocol Rev 1.90 spec. Unverified whether they are legacy/undocumented panel behavior or dead code in the library; `DK` is labeled "not used" by the library itself |

Unknown checksum-valid frames are logged/ignored for forward compatibility. Malformed,
bad-length, bad-checksum, overlength, or unterminated frames are rejected and cannot satisfy
an awaited response.
