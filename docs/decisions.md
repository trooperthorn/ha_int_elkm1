# Decisions

Dated decisions with the alternative rejected and why. Entries marked "recorded" were
carried out of code comments on 2026-09-03; the decision itself predates that date.

## 2026-09-05, zone bypass moved off `switch` entirely; unconfigured outputs past 64 no longer get entities

Two findings from reviewing the switch platform after live-hardware testing, both raised
by Sean directly.

**Outputs 65-208 were registered unconditionally.** `switch.py`'s `async_setup_entry` added
every output past index 64 as a disabled-by-default entity regardless of whether the panel
had ever named it, unlike every other element (zones, thermostats, tasks, outputs 1-64
themselves), which only get an entity once `.configured` is true. That range is rare
hardware - almost no real panel populates it - so on a typical install this created 144
disabled, meaningless entities. `helpers/elk/outputs.py`'s `Outputs.sync()` already runs
the same `get_descriptions()`/`.configured` machinery for the full 1-208 range, so there was
no technical reason for the special case. Fixed by routing the full `outputs` list through
`async_add_dynamic_entities`, the same as every other element; the disabled-by-default flag
for index >= 64 stays, since that range is still unusual hardware worth extra caution even
when genuinely configured.

**The zone-bypass switch was a real security gap, not just a style question.**
`ElkZoneBypassSwitch.async_turn_on`/`async_turn_off` called `coordinator.bypass_zone(zone)`
with no code, which falls back to the PIN stored in the config entry. Home Assistant's
`switch` entity model has no way to require a code before `turn_on`/`turn_off` runs -
unlike `alarm_control_panel`, whose Lovelace card can prompt a human for one before
arm/disarm even reaches the entity. That meant any user with dashboard access, any
automation, or a compromised Home Assistant instance could silently bypass a zone's alarm
supervision with a single, unconfirmed toggle - a materially weaker boundary than every
other security-relevant action this integration exposes, all of which require a real code
threaded from the caller (`alarm_control_panel.*`, `elkm1.alarm_bypass`/
`alarm_clear_bypass`, the existing `elkm1.sensor_zone_bypass` service on `sensor` zones).

Considered and rejected: leaving it as a switch and just documenting the risk. A
dashboard toggle with no prompt is exactly the failure mode - documentation does not
change what a compromised automation or a careless tap can do.

Fix: removed `ElkZoneBypassSwitch` entirely. Added `ElkZoneBypassBinarySensor`
(`binary_sensor.py`) as a read-only replacement showing the same bypass status with no
write capability at all, and extended the existing code-required `elkm1.sensor_zone_bypass`
service (already registered on `sensor` for temperature/analog zones, schema already
requires `code`) to also register on `binary_sensor`, via a new `async_zone_bypass` method
on `ElkBinarySensor`. Bypassing or clearing a zone's bypass now requires that service call
on every zone type, with no switch-based path at all. This is a breaking change for any
existing automation or dashboard referencing `switch.elk_m1_*_bypass` - the entity domain
changes to `binary_sensor` and it can no longer be toggled directly, only observed; the
replacement action is the service call with an explicit `code`.

## 2026-09-05, `MESSAGE_RESPONSE_TIME` lowered from 5.0s to 1.5s after a live-hardware incident

`scripts/live_full_verification.py`'s guided write-command pass against the real panel hit
two real command-confirmation failures in one run: `set_panel_time` timed out waiting for
`RR`, and moments later the periodic status refresh timed out waiting for all of
`AS`/`AZ`/`CS`/`SS`/`LW` at once (`coordinator.py`'s `POLL_RESPONSE_TIMEOUT`, 12s). The wire
log showed the actual cause: one `RR` reply arrived corrupted (`Invalid ELK-M1 message ...:
Bad checksum`) - genuine, occasional real-world serial noise on the bench USB-serial link,
correctly detected and rejected by `helpers/framing.py`'s checksum check rather than
accepted as valid data.

The bug was in the blast radius of that one lost reply, not the corruption itself.
`helpers/elk/connection.py`'s `Connection._write_stream()` drains its outbound queue one
item at a time, and for any item expecting a reply, blocks the *entire* queue - not just
that one command - for up to `MESSAGE_RESPONSE_TIME` before giving up and moving to the
next queued item. With `set_time`'s `rw` write queued directly ahead of the periodic poll's
five status requests, one lost `RR` reply could stall the send of `AS`/`AZ`/`CS`/`SS`/`LW`
long enough to blow through their own 12-second aggregate timeout, even though most or all
of them would likely have succeeded if sent promptly. At the old 5.0s ceiling, a queue with
six items ahead of each other (one write plus a five-command poll burst) had a worst case of
30 seconds of pure per-item stalling from lost replies alone - comfortably capable of
producing exactly the spurious "timed out waiting for: AS, AZ, CS, LW, SS" this run hit.

Considered and rejected: removing the per-item wait entirely. The panel is documented
elsewhere in this repo as having "one serialized command buffer with no flow control;
writes must not overlap" - some pacing gap between writes is a real, physical constraint,
not just defensive caution, and the coordinator's own `async_confirm_command`/
`async_queue_command` already do their own separate, type-and-predicate-matched
confirmation independently of this connection-level gate, so removing the gate risks
reintroducing whatever overlap problem it was added to prevent, for no benefit this
incident's root cause actually required.

Fix: lowered `MESSAGE_RESPONSE_TIME` to 1.5s - real round trips measured across every live
run this session were 50-350ms (a full five-command poll cycle completed in 1.74s per
`docs/live_qualification.md`'s sixth entry), so 1.5s leaves several times that margin for
jitter on a single command while capping the worst-case pileup from repeated lost replies to
a fraction of what the 5.0s default produced. `coordinator.py`'s `POLL_RESPONSE_TIMEOUT`
(12s) was left unchanged - it now has more comfortable headroom under the new ceiling, not
less. Not yet re-verified live (the panel is not readily available for repeated bench
testing); `tests/test_elk_connection.py` gained a direct assertion pinning the ceiling to a
low value and a regression test confirming the drain loop still sends a second queued item
after an earlier one's reply never arrives, rather than stalling indefinitely.

## 2026-09-05, Gold quality-scale: `translation_key` naming stops at entities whose name embeds live panel data

Working through the Gold-tier `entity-translations` rule, most fixed-English entity names
(the panel sensor, active-zones summary, per-area alarm partitions, the arm-request proxy
switch, per-area openings sensors, and all 23 named trouble binary sensors) converted
cleanly to `_attr_translation_key` plus `strings.json`'s new `entity` section, including two
that need a per-entity placeholder (`Area {area_num}`, `Area {area_num} Openings}`) filled
in once at `__init__` time via `self._attr_translation_placeholders = {...}`.

Two entities - `ElkZoneBypassSwitch` and `ElkThermostatEMHeat` - were rejected for this
treatment after hitting a real constraint verified against HA core
(`homeassistant/helpers/entity.py`): `Entity.translation_placeholders` is `@final` and a
`@cached_property`, computed once and then frozen in the instance's `__dict__` for the
entity's lifetime. Both of these entities embed a panel-reported name mid-string ("Front
Door Bypass", "Upstairs Emergency Heat") that is documented elsewhere in this repo as
arriving *after* entity creation (the panel sends zone/thermostat names asynchronously).
Setting `_attr_translation_placeholders` once at `__init__` would freeze the name at
whatever placeholder was available at construction time (almost always the "Zone N" /
"Thermostat N" index fallback), permanently hiding the real panel name once it arrives -
a real regression from the existing live `name` property override these two entities
already had. Kept the live `name` override for these two instead of forcing a mechanism
that cannot represent dynamically-arriving data; `_attr_icon` also had to stay literal on
`ElkZoneBypassSwitch` for the same reason (icon-translations keys by `translation_key`,
which this entity intentionally does not set).

For `repair-issues`, `helpers/panel_settings.py`'s `verify_panel_configuration()` (Global
Programming broadcast-category confirmation) now raises a Repair issue via
`ir.async_create_issue` (deleted via `ir.async_delete_issue` once every required category is
confirmed) instead of only logging a warning, since it is user-actionable (enable the
setting on the panel) and was already the kind of thing a user could miss in the log.
Scoped `issue_id` per config entry (`outdated_panel_broadcasts_<entry_id>`) to keep the
already-supported multi-panel case from colliding on one shared issue.

## 2026-09-05, `vocabulary.py` and a new `event_log.py` sourced from Elk's own ElkRP tool

Sean provided a copy of ElkRP (Elk's own Windows programming application) for analysis.
Decompiling its managed .NET assemblies (via `ilspycmd`) and reading the static reference
database it ships with (`Controls2.mdb`) turned up two authoritative data sources this
repository previously had to guess at or leave incomplete:

- `WordLists` (PanelType='M1G', WordListVer='0.8', 478 rows) is Elk's own voice-vocabulary
  table - the same data ElkRP itself uses to build `sw`/`sp` word lists. It confirmed IDs
  21-473 in the existing `ELK_VOICE_VOCABULARY` table already matched word-for-word, but
  found the "say toggle" phrase IDs were wrong: this repo had them as positive
  495/496/505-512, sourced from a reading of the installation manual's ambiguous Appendix C;
  the real IDs are negative (-503 through -512), and four more (-2/-3/-4/-5, the "insert
  condition"/"insert time"/"inverted condition"/"say number" template tokens) were missing
  entirely. Fixed by replacing the wrong entries and adding the missing ones, sourced
  directly from ElkRP's own table rather than the manual. This also resolved a real
  ambiguity this repo's earlier docstring speculated about: IDs 2/3/4 ("custom 2/3/4") and
  -2/-3/-4 (the template tokens) are genuinely different, non-overlapping IDs in the real
  table, not one ID space the manual failed to disambiguate.
- `EventLists` (PanelType='M1G', ListVer='5.3.0', the newest available, 1358 rows) maps
  every numeric event code the `LD` (system log) message's `event` field can carry (e.g.
  `1001 = FIRE ALARM`, `4176 = ZONE 176 STATE`, `7208 = OUTPUT 208 STATE`) to the
  description ElkRP itself shows. `ld_decode` previously left this field a bare,
  undescribed integer, and nothing in `coordinator.py` consumed the `LD` broadcast's
  content at all (only counted it for diagnostics). Added `event_log.py` with the full
  table plus `describe_elk_event()`, and a new `_handle_log_event` coordinator handler
  (mirroring the existing pattern used by `_handle_timer_event`/`_handle_alarm_memory`)
  that fires a new `elkm1.log_event` HA bus event with the area, raw event code,
  human-readable description, log number/index, and timestamp - the same shape those
  existing handlers already use. New `EVENT_ELKM1_LOG_EVENT` constant in `const.py`.

Both tables were extracted read-only via a local Access connection (using ElkRP's own
hardcoded, shared - not per-install secret - database-open credential, embedded in every
shipped copy of the app) and are not runtime dependencies; they're compiled once into
Python source the same way `ELK_VOICE_VOCABULARY` already was. See the full survey (every
managed assembly decompiled, every form's purpose cataloged, compared against this
repository's coverage) delivered to Sean separately as `ElkRP_Feature_Catalog.md` - most of
ElkRP's functionality (full EEPROM panel programming, the panel's own WhenThen rules
engine, M1XEP/central-station/M1Cloud provisioning) rides on a separate, undocumented
binary protocol this repository correctly does not attempt to speak; these two data tables
were the only pieces that meaningfully improved data this repo already surfaces over the
documented ASCII protocol.

## 2026-09-05, removed the `elkm1-lib` PyPI dependency; own the protocol directly

`manifest.json` no longer requires `elkm1-lib` (was pinned 2.2.15); the ELK-M1 RS-232
ASCII protocol implementation it used to provide (message encode/decode, the `Elk` hub
and its typed element collections, the connection/write-queue state, UDP discovery) now
lives in this repository's own `helpers/elk/` sub-package. The only remaining runtime
dependency is `serialx==1.9.0`.

Sean's call, made after this session had already found and worked around several real
gaps in the pinned version: no encoder for `kc` (Request Keypad Status), `rr` (RTC read),
`st` (direct temperature request), or indexed `ld` (log request); `cw`/`rw`/`tr`/`ts`
encoders that declared no reply code even though the spec documents one for each,
patched at the transport layer with a `RESPONSE_COMMAND_OVERRIDES` table; no native
handling of the `PC` "all lights" aggregate form or the full v1.90 `KC` field set, both
already reimplemented as post-hoc patches in `helpers/transport.py`; the `AS` reply's
M1-4.11+ exit/entrance-timer sub-field silently dropped; and `helpers/transport.py`
already reaching into five-plus private (`_`-prefixed) attributes of `Connection` and
monkey-patching three of its bound methods via `MethodType` - in practice, the library
was already only half in control of its own connection lifecycle. Rejected: continuing
to patch around a dependency this integration had already outgrown. Every gap above was
fixed natively during the port rather than carried forward as another workaround:
`kc`/`rr`/`st`/indexed-`ld` encoders now exist and are verified against both the
primary-source PDF and real hardware; `cw_encode`/`rw_encode`/`tr_encode`/`ts_encode`
declare their real reply codes directly, retiring `RESPONSE_COMMAND_OVERRIDES`;
`decode()` handles the `PC` aggregate form and the full `KC` field set natively (the
latter still split into a separate `kc_detail_decode()` to avoid a `Notifier.notify()`
keyword-argument mismatch crash - see the file's own docstring); `as_decode` now parses
the M1-4.11+ trailing field into `timer_seconds`; and `Connection` is `helpers/transport.py`'s
own class with public state, so there is no more monkey-patching or reaching into another
package's private attributes.

Verification: every encode/decode function ported was checked against the manufacturer's
own `ELK-M1_RS232_PROTOCOL.Ver+1.90.pdf` worked examples and, for `vn`/`as`/`ss`/`kc`/
`rr`/`st`/`ld`/`ic`/`xk`/`ua`/`zs`, against real captured hardware data from this same
session (see `docs/live_qualification.md`). The port itself surfaced two further bugs
that a byte-for-byte comparison against the old dependency's actual behavior would not
have caught, because they were never exercised until the full test gate ran against the
new code: `_pc_all_decode` had its house/unit/aggregate-code field offsets wrong (fixed
by re-deriving them from the same wire example used by
`tests/test_transport.py::test_read_stream_decodes_all_lights_and_complete_keypad_status`),
and `kc_detail_decode` did not catch its own `ValueError` on a malformed supplemental
keypad field, which would have taken down the entire read loop on one corrupt frame
instead of just discarding that frame's supplemental detail (fixed by wrapping it in its
own `try`/`except`). Full `ruff`/`mypy`/`pytest` gate green (211 tests) after the fix.

## 2026-09-05, `Users.username()`'s reserved-code special names were unreachable dead code

Found while adding `tests/test_elk_users.py` during the elkm1-lib removal's test-coverage
follow-up (see the earlier 2026-09-05 removal entry). `username()` checked
`0 <= user_number < self.max_elements` (203) *before* its special-case branches for the
reserved raw codes 201 ("Program Code"), 202 ("ELK RP Code"), and 203 ("Quick Arm", no code
- spec section 4.16, M1 Ver. 4.4.2+): since the `Users` collection is sized to
`Max.USERS.value` (203) elements, that range check alone already covers every 0-based index
from 0 to 202, so the special-case comparisons (written against the raw 1-based values
201/202/203) could only ever be reached by an out-of-range input that does not correspond
to any code the panel actually sends - `coordinator.py`'s only caller passes
`ic_decode`'s already-0-based `user` field (`int(msg[16:19]) - 1`), so a real Program/ElkRP/
Quick-arm event would report `changed_by` as a generic `User-201`/`User-202`/`User-203`
placeholder instead of the intended label. Fixed by checking the special cases first,
using their 0-based equivalents (200/201/202) to match how every other index in this
codebase is already 0-based. Regression tests:
`tests/test_elk_users.py::test_username_returns_special_names_for_the_reserved_range` and
`test_username_does_not_return_a_placeholder_name_for_the_reserved_indices`.

## 2026-09-05, `number.py` guards `.value is None` for counters and custom values

Found by actually running this integration's real `async_setup_entry` against real
hardware (see `docs/live_qualification.md`'s fourth follow-up entry) rather than a
standalone protocol script: `elkm1_lib.counters.Counter.value` and
`elkm1_lib.settings.Setting.value` both default to `None` until a `CV`/`CR` message
populates them, but `native_value` called `float(obj.value)` unconditionally whenever the
object existed, crashing on every fresh setup with a `TypeError`. Fixed both properties to
check for `None` explicitly. Checked every other `int(obj.value)`/`float(obj.` call in
every platform file for the same mistake before stopping - the rest either wrap a
default-`0` attribute or are an unrelated, already-guarded enum-unwrapping helper, not
the same bug.

## 2026-09-05, `vocabulary.py` replaced from a document now known to be stale; unresolved

`ELK_VOICE_VOCABULARY` was rewritten from `ELK_M1_Installation&Programming_Manual.pdf`
Appendix C ("Voice Message Vocabulary *RP only*") after finding the previous table did not
match that document at all (different words at nearly every ID, e.g. ID 108 was
`"alarm"` there vs. `"center"` in Appendix C). That manual's own title page states it is
"Current with Firmware 5.3.10"; Sean's live panel is 5.3.18. Sean had previously tested
real word playback against the *old* table and reports numbers and room names sounded
correct - which conflicts with Appendix C's numbering (old table: `1`-`9` = one-nine
directly; Appendix C: `22`-`30` = one-nine, offset by 21). The two cannot both be right for
the same panel.

Rejected for now: reverting to the old table (it was independently confirmed fabricated,
not sourced from any document found this session, so "sounded right" for simple low-number
IDs doesn't establish it's correct for the other ~460 entries) and re-deriving a third
table without live evidence (guessing again would repeat the same mistake this entry is
about). Decision: leave `vocabulary.py` as the Appendix-C-derived table for now: Sean will
re-test actual word/phrase playback against the real panel after the current release and
report back exactly which IDs produced which spoken words, so the table can be corrected
from first-hand evidence rather than a manual already 8 patch versions stale. Recorded in
`docs/backlog.md` as an open item - do not treat this table as verified until that
retest happens.

See also the `_handle_voice_message` finding in `docs/backlog.md`: even a fully correct
vocabulary table would not make the inbound voice-translation feature reachable, because
that is a separate, deeper problem (the callback can never receive word data at all).

## 2026-09-05, thermostat (`ts`/`tr`) live qualification is will-not-test

Sean's bench setup has no Elk-connected thermostat and will not get one. Rejected: leaving
this open as a pending/unverified live-qualification item indefinitely, which would read as
an oversight rather than a scope decision. `climate.py`'s `ElkThermostat` entity stays
covered by simulated tests only; see `docs/live_qualification.md`'s 2026-09-05 follow-up
entry.

## 2026-09-05, `hacs.json`'s `hacs` minimum-version key is kept

Verified against `~/repos/hacs-documentation/source/docs/publish/start.md`, which lists
`hacs` (string, optional) as "The minimum required HACS version" - still a documented,
valid key as of HACS 2.0.5. The scanner's `hacs-min-version-key` finding is a review
prompt ("confirm it is still documented"), not a removal instruction; this closes that
review. The pinned floor (`1.32.0`) stays: nothing this integration ships (no local
`brand/icon.png`, no HACS-2.x-only feature) requires a newer minimum, and lowering the
floor's precision would only add a maintenance burden with no functional benefit.

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

## Recorded, baud detection reuses the shared encoder and decoder

Rejected: a hand-written `vn` frame, which would re-derive checksum and framing that
`helpers/elk/message.py` already implements correctly (originally `elkm1_lib.message`;
see the 2026-09-05 entry above on removing that dependency).

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
