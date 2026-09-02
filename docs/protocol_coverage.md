# ELK-M1 RS-232 ASCII Protocol v1.90 coverage

This matrix distinguishes the M1 wire protocol from the Home Assistant feature surface.
“Implemented” means the integration or pinned `elkm1-lib 2.2.15` can encode/decode the
message and this repository has a defined consumer. It does not mean a physical panel has
been qualified; see `live_qualification.md`.

| Family | Commands | Status |
|---|---|---|
| Area arm/disarm | `a0`-`a6`, `as`/`AS` | Implemented; arm/disarm requires matching validated `AS` |
| Advanced arm stepping/force | `a7`-`a:` | Decodable state; intentionally not exposed as HA actions |
| Alarm by zone | `az`/`AZ` | Implemented; used in initial and bounded status refresh |
| Area alarm memory/timers | `AM`, `EE` | Implemented, including symbolic alarms and timer type |
| Output control/status | `cf`, `cn`, `cs`/`CS`, `ct`, `CC` | Implemented for outputs 1-208; 65-208 disabled by default |
| Custom values | `cp`, `cr`/`CR`, `cw` | Implemented; writes require matching `CR` |
| Counters | `cv`/`CV`, `cx` | Implemented; reads/writes require matching `CV` |
| Keypads | `ka`/`KA`, `kc`/`KC`, `kf`/`KF` | Receive/control implemented; all v1.90 `KC` fields preserved |
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
| Audio/touchscreen | `ca`/`CA`, `cd`/`CD`, `t2`/`T2`, `ti` | Intentionally unsupported; no current HA feature contract |
| Insteon programming | `ir`/`IR`, `ip`/`IP` | Intentionally unsupported; programming belongs in installer tooling |
| User-code modification | `cu`/`CU` | Intentionally unsupported pending a separate security design and live qualification |
| Manufacturer-internal | `AP`, `AR`/`ar`/`ax`, `DS`/`ds`, `EM`, `RE`, `XB` | Prohibited or reserved by the manufacturer; must not be emitted |

Unknown checksum-valid frames are logged/ignored for forward compatibility. Malformed,
bad-length, bad-checksum, overlength, or unterminated frames are rejected and cannot satisfy
an awaited response.
