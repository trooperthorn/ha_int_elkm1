# Protocol and device facts

Wire-level and panel behavior the code depends on. Coverage of the protocol as a whole is
in `protocol_coverage.md`; this file holds the specific numbers and quirks that a reader of
the code needs to trust it. Each table row says whether the fact was verified against the
manual or the library, or only carried over from a code comment.

## Serial link and baud detection

| Fact | Status |
| --- | --- |
| The RS-232 ASCII protocol (manual v1.90, section 2) has no command to query or set the baud rate; it is a panel-side Global Programming setting with no handshake and no RTS/CTS honored by the panel | verified against the manual section cited in the original code |
| Detection therefore sweeps the manufacturer-documented rates on the host and confirms each with a real `vn` reply | verified in `helpers/baud_probe.py` |
| Sweep order, fastest first: 115200, 38400, 19200, 14400, 9600, 4800, 2400, 1200, 300 (Global Programming G34) | verified: `ELK_M1_Installation&Programming_Manual.pdf` page 36 (Menu 07, option 34, "Baud Rate Port 0") lists exactly these nine selections ("0 or 1=300 baud, 2=1200, 3=2400, 4=4800, 5=9600, 6=14400, 7=19200, 8=38400, and 9=115200") with factory default 115200. That manual calls this the "revert back to" rate for Port 0, meaning the panel can be driven at a different rate mid-session (e.g. by a keypad or ElkRP) and returns to this configured value afterward. The RS-232 protocol spec's own overview line ("baud rate: configurable ... range 9600 to 115200 baud") only describes a narrower range than G34 actually allows; that line is this integration's separate primary source and was not corrected to match, since both are manufacturer documents and the discrepancy is the vendor's, not this code's |
| Probe reply timeout is 2.0 seconds because the manual notes multi-second command latency is normal for some commands | timeout verified in code; no specific "2.0 seconds" or comparable figure was found in either manual - the statement that multi-second latency is normal remains unverified, distinct from the now-verified baud list above |
| Panel traffic is asynchronous; the probe ignores valid broadcasts until the requested `VN` reply arrives | verified in code |

The serial stack is `serialx` (developer blog 2026-04-27); it is the only runtime
dependency `manifest.json` declares (see `docs/decisions.md` 2026-09-05 for the removal of
the `elkm1-lib` dependency that used to also pull in `pyserial-asyncio-fast`).

## Heartbeat and poll interval

`helpers/transport.py`'s `DEFAULT_HEARTBEAT_TIMEOUT` fixes a 120 second network heartbeat
window on `helpers/elk/connection.py`'s `Connection`. The assumption in that constant is
that some traffic, a broadcast or a poll reply, reaches the socket inside it. That held
while the poll fallback was fixed at 30 seconds. The options flow now allows
up to `MAX_POLL_INTERVAL` (300 seconds); a panel with "Xmit ... Changes" disabled and a
poll interval past the window would otherwise reconnect roughly every 120 seconds no matter
what interval the user chose. `ElkConnectionManager` therefore scales the heartbeat window
to the poll interval plus `HEARTBEAT_MARGIN` (30 seconds), capped at `MAX_POLL_INTERVAL`.
Regression tests: `tests/test_coordinator.py::test_async_setup_scales_heartbeat_timeout_with_poll_interval`
and `tests/test_transport.py::test_manager_accepts_a_scaled_heartbeat_timeout`.

## Command buffer

The panel has a single serialized command buffer with no hardware flow control, so every
platform that writes sets `PARALLEL_UPDATES = 1`. The zone bypass and trigger entity
services write to the same buffer. The buffer size of 250 characters that an earlier
comment cited is now verified: the RS-232 protocol spec's "Buffering caveat" states "the
M1's incoming message buffer holds up to 250 characters."

## Global Programming broadcast bits

The protocol cannot read back the "Xmit ... Changes" bits that gate proactive broadcasts;
they are set only from a keypad or ElkRP. `helpers/panel_settings.py` maps each location
to the broadcast type it gates and infers the bit from broadcast counts the coordinator
keeps since connecting:

| Location | Setting | Broadcast |
| --- | --- | --- |
| G35 | Transmit Event Log | LD |
| G36 | Zone Changes | ZC |
| G37 | Output Changes | CC |
| G38 | Automation Task Changes | TC |
| G39 | Light Changes | PC |
| G40 | Keypad Changes | KC |

All six rows are verified in code. The original docstring also named location 30; that
location is real but broader than this table: the RS-232 protocol spec's section 4.39
header states the panel "can also be programmed (Global Programming Location 30/33-37) to
auto-send zone/system status on change" - a parent/umbrella toggle for status auto-send in
general, distinct from the six specific per-broadcast-type locations (G35-G40) this
integration tracks individually. It is correctly absent from `REQUIRED_SETTINGS`: nothing
here depends on the umbrella setting once the specific ones are confirmed.

G40 gates whether the panel proactively broadcasts keypad function-key/bypass-code status:
`helpers/elk/message.py`'s `kc_encode` can now actively request it (fixed 2026-09-05,
`elkm1-lib` 2.2.15 had no encoder for the `kc` request at all - "Request Keypad Status
Update"), but the coordinator does not poll it on the periodic refresh path (see
`docs/protocol_coverage.md`), so in practice the integration still only receives it via the
unsolicited `KC` broadcast, and only while G40 is enabled. If G40 is off, keypad
key-illumination and bypass-code status are simply unavailable, not stale.

## Firmware floor

The minimum supported firmware is 4.6.8 on the 4.x branch, or 5.2.0 on 5.x and later. A
plain tuple comparison against `(4, 6, 8)` would also accept 5.0.0 and 5.1.x, which are
below the 5.2.0 floor, so the 4.x rule applies only when the major version is 4. Verified
in `helpers/panel_settings.py`.

## Reply codes fixed relative to elkm1-lib 2.2.15

`helpers/elk/message.py`'s `cw_encode`, `rw_encode`, `tr_encode`, and `ts_encode` now
declare their real reply (`CR`, `RR`, `TR`, `TR`) directly. The now-removed `elkm1-lib`
2.2.15 dependency's equivalents each returned `MessageEncode(..., None)` for all four, even
though the protocol documents a reply for each - `helpers/transport.py` used to patch this
with a `RESPONSE_COMMAND_OVERRIDES` table, now retired since the encoders carry the correct
value themselves (see `docs/decisions.md` 2026-09-05). Contrast `cv_encode`/`cx_encode`,
which correctly declared `"CV"`, and `ua_encode`, which correctly declared `"UA"` even in
the old library - so this was specific to these four functions, not a library-wide gap.

## Trouble status (`SS`)

`TROUBLE_INDEX_NAMES` maps each character index of the SS reply to a machine name and a
human name; unlisted indices are reserved positions. Indices 1, 5, 18, 20, and 33 carry a
one-based zone or device number encoded as the ASCII value minus `'0'` rather than a
boolean; only on or off is reported for those, not the number. `parse_troubles` takes the
exact string `helpers/elk/message.py`'s `ss_decode()` produces (`msg[4:-2]`): `'0'` means
inactive and any other character means active. The index mapping is verified against
`helpers/elk/panel.py`'s `Panel._ss_handler` and, as of 2026-09-05, directly against the manufacturer's primary
source PDF (`ELK-M1_RS232_PROTOCOL.Ver+1.90.pdf`, section 4.29.2, not the
`vendor-docs-reference` markdown derived from it): its own worked example
`28SS1000000000000000000000000000000000002F` parses to a 34-character field with the
non-zero byte at index 0 ("AC Failure Trouble"), confirming both the field width and that
`AC Fail` is index 0. Counting the section's field list in order (`AC Fail`, `*Box Tamper`,
`Fail To Communicate`, `EEPROM Memory Error`, `Low Battery Control`,
`*Transmitter Low Battery`, `Over Current`, `Telephone Fault`, `Not Used`, `Output 2`,
`Missing Keypad`, `Zone Expander`, `Output Expander`, `Not Used`, `ELKRP Remote Access`,
`Not Used`, `Common Area Not Armed`, `Flash Memory Error`, `*Security Alert`,
`Serial Port Expander`, `*Lost Transmitter`, `GE Smoke CleanMe`, `Ethernet`, then **eight**
consecutive `Not Used` lines, then `Display Message In Keypad Line 1`, `Display Message In
Keypad Line 2`, `*Fire Trouble`) lands exactly on this repository's mapping: 31/32/33 for
the last three fields, not 30/31/32. The previous "unverified" note in this file undercounted
that run as seven `Not Used` positions rather than eight, because it was counting a
paraphrased summary in `vendor-docs-reference/docs/elk-m1.md` ("7 unused"), not the primary
source's own line-by-line list - that markdown has a real transcription error worth fixing
in that separate repository. `TROUBLE_INDEX_NAMES` is now verified correct with high
confidence, against the manufacturer's own worked example, not just a library parser.

## Alarm and arming states

Full alarm is exactly the documented alarm-state table `'3'` through `'B'`
(`protocol.ALARM_STATE_FULL_ALARM`, section 4.2.13). Alarm state 2 (abort delay) is a
cancellable pending interval, not full alarm. Arm-up state 5 (force armed) is stable; only
arm-up state 3 is the exit timer. Arm-up state 6 with a non-zero armed status maps to
`ARMED_CUSTOM_BYPASS`. Armed status 1 is armed away; 2 and 3 are armed home. In the
security summary, the AS arm-up state is authoritative: 1 is ready and 2 can be force
armed. Zones are 1-indexed to the user and 0-indexed in the lists. `alarm_state` keeps its
single-character wire value because valid values run from `':'` to `'B'`.

The `AS` reply's trailing `00` field is M1 4.11+ only: per area, it carries the exit-time
remaining (in seconds, 2 hex digits) when that area's arm-up state is `3`, or the
entrance-time remaining when its alarm state is `1`. `helpers/elk/message.py`'s `as_decode`
now parses it into a `timer_seconds` field (fixed relative to the removed `elkm1-lib`
2.2.15 dependency, whose equivalent only read `msg[4:28]` and silently dropped it - see
docs/decisions.md 2026-09-05), but `Areas._as_handler` deliberately discards the value: the
separate `EE` (Entry/Exit Time Data) message carries the same countdown as `timer1`/`timer2`
and is what `coordinator.py` actually surfaces (`_handle_timer_event`). This is not a
functional gap - a reader verifying `AS` decode coverage against the manual should know this
sub-field is now decoded but intentionally unused here, not missing by omission.

## Zone definitions and statuses

Zone definition values: 1 and 2 entry/exit (door), 3 perimeter instant (opening), 4 to 7
interior (motion), 10 and 11 fire, 17 CO, 19 freeze, 20 gas, 21 heat, 25 water, 33
temperature, 34 analog zone. `ZoneLogicalStatus` has four values: 0 normal, 1 trouble, 2
violated, 3 bypassed. There is no combined violated-and-bypassed value and no separate
bypassed attribute. Zone bypass (`zb`) is a toggle with no clear command.

## Lighting

In `PC` and `PS` messages, 0 is off, 1 is full on, and 2 through 99 are dim percentages.
