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
| Sweep order, fastest first: 115200, 38400, 19200, 14400, 9600, 4800, 2400, 1200, 300 (Global Programming G34) | rates verified in code; the G34 attribution and the "current guide describes 9600 to 115200, legacy rates last" claim are unverified |
| Probe reply timeout is 2.0 seconds because the manual notes multi-second command latency is normal for some commands | timeout verified in code; the manual statement is unverified |
| Panel traffic is asynchronous; the probe ignores valid broadcasts until the requested `VN` reply arrives | verified in code |

The serial stack is `serialx` (developer blog 2026-04-27). `elkm1-lib` 2.2.15 still
declares `pyserial-asyncio-fast`, which pip installs alongside; the integration itself
imports only `serialx`.

## Heartbeat and poll interval

`elkm1_lib.connection.Connection` uses a fixed 120 second network heartbeat window
(`Connection.HEARTBEAT_TIME`, mirrored by `DEFAULT_HEARTBEAT_TIMEOUT`). The assumption in
that constant is that some traffic, a broadcast or a poll reply, reaches the socket inside
it. That held while the poll fallback was fixed at 30 seconds. The options flow now allows
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
comment cited is unverified.

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
location is not in `REQUIRED_SETTINGS` and is unverified.

## Firmware floor

The minimum supported firmware is 4.6.8 on the 4.x branch, or 5.2.0 on 5.x and later. A
plain tuple comparison against `(4, 6, 8)` would also accept 5.0.0 and 5.1.x, which are
below the 5.2.0 floor, so the 4.x rule applies only when the major version is 4. Verified
in `helpers/panel_settings.py`.

## Reply codes missing from elkm1-lib 2.2.15

`RESPONSE_COMMAND_OVERRIDES` supplies `cw` to `CR`, `rw` to `RR`, `tr` to `TR`, and `ts`
to `TR`. That the library omits these documented replies from its encoder metadata is
carried over from the original comment and unverified against the library source.

## Trouble status (`SS`)

`TROUBLE_INDEX_NAMES` maps each character index of the SS reply to a machine name and a
human name; unlisted indices are reserved positions. Indices 1, 5, 18, 20, and 33 carry a
one-based zone or device number encoded as the ASCII value minus `'0'` rather than a
boolean; only on or off is reported for those, not the number. `parse_troubles` takes the
exact string `elkm1_lib`'s `ss_decode()` produces (`msg[4:-2]`): `'0'` means inactive and
any other character means active. The index mapping is verified against the library's
`Panel._ss_handler`; the manual reference "sections 4.29.2 to 4.30" for the number-encoded
positions is unverified.

## Alarm and arming states

Full alarm is exactly the documented alarm-state table `'3'` through `'B'`
(`protocol.ALARM_STATE_FULL_ALARM`, section 4.2.13). Alarm state 2 (abort delay) is a
cancellable pending interval, not full alarm. Arm-up state 5 (force armed) is stable; only
arm-up state 3 is the exit timer. Arm-up state 6 with a non-zero armed status maps to
`ARMED_CUSTOM_BYPASS`. Armed status 1 is armed away; 2 and 3 are armed home. In the
security summary, the AS arm-up state is authoritative: 1 is ready and 2 can be force
armed. Zones are 1-indexed to the user and 0-indexed in the lists. `alarm_state` keeps its
single-character wire value because valid values run from `':'` to `'B'`.

## Zone definitions and statuses

Zone definition values: 1 and 2 entry/exit (door), 3 perimeter instant (opening), 4 to 7
interior (motion), 10 and 11 fire, 17 CO, 19 freeze, 20 gas, 21 heat, 25 water, 33
temperature, 34 analog zone. `ZoneLogicalStatus` has four values: 0 normal, 1 trouble, 2
violated, 3 bypassed. There is no combined violated-and-bypassed value and no separate
bypassed attribute. Zone bypass (`zb`) is a toggle with no clear command.

## Lighting

In `PC` and `PS` messages, 0 is off, 1 is full on, and 2 through 99 are dim percentages.
