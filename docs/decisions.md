# Decisions

Dated decisions with the alternative rejected and why. Entries marked "recorded" were
carried out of code comments on 2026-09-03; the decision itself predates that date.

## 2026-09-04, `IC` wired for `changed_by`; Alarmo sync is one-way

`coordinator.py` now attaches an `IC` handler and resolves the reporting user's name via
`elk.users.username()` (already synced by the library through `sd`/`TextDescriptions.USER`,
previously never read by this repository), feeding the standard `changed_by` attribute and a
new `last_user_time`. `const.py`'s `ATTR_CHANGED_BY_KEYPAD`/`ATTR_CHANGED_BY_ID`/
`ATTR_CHANGED_BY_TIME` were removed rather than reused: they were unused scaffolding for the
same feature, and every other key in `extra_state_attributes` is already a bare string
literal, not an `ATTR_*` import. Rejected: leaving `last_user`/`last_user_name` hardcoded to
`None`/`"Unknown"` on every snapshot, which is what the code did before this change - accurate
data was available from the library and simply never read.

`blueprints/automation/alarmo_state_sync.yaml` mirrors ELK-M1's alarm state into Alarmo
one-way (ELK-M1 -> Alarmo) using `skip_delay: true` and `force: true` on the Alarmo side.
Rejected: a bidirectional sync (Alarmo arming the physical panel back), which would need a
loop-prevention design this session did not verify is safe against Alarmo's own independent
sensor-driven arming logic; rejected forwarding the transient `arming`/`pending` states, since
ELK-M1's exit/entry delay has already completed in hardware by the time a stable armed state
is reported, and letting Alarmo run its own delay on top of that would desync the mirror from
the panel's actual state, which matters more on a security system than a forced/instant arm.

## 2026-09-03, entity services registered from `async_setup`

All nine entity services are registered in `services.py` through
`service.async_register_platform_entity_service`, following the 2025-09-25 developer blog.
Rejected: keeping `platform.async_register_entity_service` in each platform's
`async_setup_entry`, which is deprecated and makes a service's existence depend on that
platform having loaded.

## 2026-09-03, serial stack is serialx

`helpers/baud_probe.py` opens ports with `serialx.open_serial_connection` and the manifest
requires `serialx==1.9.0` (developer blog 2026-04-27). Rejected: keeping `pyserial` and
`pyserial-asyncio-fast` pinned in the manifest next to a library that already drags one of
them in. `elkm1-lib` still declares `pyserial-asyncio-fast`; that is upstream's to change.

## 2026-09-03, release path is the shared baseline

The bot-commits-to-main release flow was replaced by the trooperthorn baseline: `Release`
publishes the version already on `main`, and `Prepare release` opens a bump PR through a
GitHub App that auto-merges after the full gate. Rejected: the previous flow, where the
release job pushed a `[skip release]` commit straight to `main`, which cannot coexist with
branch protection and let unreviewed bytes reach the default branch. The tag prefix stays
`v` to match every existing tag.

## Recorded, perimeter-instant zones map to `opening`, not `window`

The protocol carries the arming response, not the sensor type; claiming `window` would
overstate what the panel says. Rejected: mapping definition 3 to `window`.

## Recorded, emergency heat is a switch, not an hvac mode

Rejected: an `EMERGENCY_HEAT` hvac mode, which would put two competing controls on one
setting.

## Recorded, baud detection reuses the library's encoder and decoder

Rejected: a hand-written `vn` frame, which would re-derive checksum and framing that
`elkm1_lib.message` already implements correctly.

## Recorded, a winning baud probe hands back its open connection

Rejected: closing and reopening the port before use, which wastes a round trip and, on some
USB-serial adapters, trips DTR-reset or settling quirks (unverified, from field experience).

## Recorded, failed alarm panel commands raise

Rejected: logging and swallowing failures, which made Home Assistant traces report success
on commands the panel rejected.

## Recorded, Alarmo auto-setup matches zones by unique_id

Rejected: matching the substring "zone" in the entity_id, which real installs never have
because entity ids come from panel zone names. The service also stopped using
`hass.components`, which core removed and which crashed every call path.

## Recorded, outputs 65 to 208 are created disabled

Rejected: creating them enabled, which adds 144 generically named entities to every panel.

## Recorded, unnamed counters and custom values are not created

Rejected: creating all 64 counter and 20 custom-value slots on every install.
