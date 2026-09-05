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

## Live run, 2026-09-05: bare panel, direct serial, protocol-level only

Real ELK-M1 panel connected directly to the workstation via an FTDI USB-serial adapter
(`COM3`, VID:PID 0403:6001) at Sean's direction; no zones, keypads, or alarm/siren
hardware wired to it. This was a raw protocol probe against the wire (a standalone script
implementing the framing/checksum from `elk-m1.md` and calling `elkm1_lib.message`'s
decoders directly), not a run of the Home Assistant integration itself - it covers the
"Direct serial" bullet above only partially: baud detection at the factory-default rate
and command/reply round-trips, not cached-baud reconnect, wrong-baud recovery, unload
during probe/reconnect, or `by-id`/`by-path` identity.

**Identity**: `vn` reply decoded to `elkm1_version: 5.3.18`, `xep_version: 0.0.0` (no XEP
present, confirming this was genuinely direct-serial, not a bridged connection). 5.3.18 is
above this integration's 5.2.0 floor for the 5.x branch and above the 5.3.0 firmware gate
for the `a9`/`a:` force-arm commands, so this specific panel could exercise those if ever
wired up.

**Confirmed by direct observation, closing prior "unverified" items**:
- Baud sweep: panel answered `vn` on the very first try at 115200 - the sweep's
  fastest-first order and the G34-documented factory default (verified against the
  installation manual on 2026-09-05, see `protocol.md`) both checked out together.
- Checksum algorithm: every request this session (`vn`, `as`, `ss`, `zs`, `zp`, `cs`) got a
  reply that `elkm1_lib`'s checksum-validating `decode()` accepted; the framing/checksum
  description in `elk-m1.md` matches the real byte stream exactly.
- `AS`/`AM`/`SS`/`ZS`/`ZP`/`CS`/`KC`/`XK` all decoded through the actual pinned
  `elkm1_lib` 2.2.15 functions without error against real panel output, not synthetic
  fixtures.
- The `AS` reply showed area 1 as `NOT_READY_TO_ARM` while areas 2-8 showed
  `READY_TO_ARM`. A follow-up `zs` explained it: zones 1-8 and 10-15 (unwired loops)
  report `ZoneLogicalStatus.VIOLATED` / `ZonePhysicalStatus.OPEN` - an unsupervised open
  loop reads as violated, not merely "unconfigured" - while zones 9 and 16 read `NORMAL`/
  `UNCONFIGURED`. Area 1 evidently owns the violated zones; areas 2-8 have none assigned,
  so they show ready with nothing to check. This is real panel behavior, not a decode bug.
- The panel emits unsolicited `KC` broadcasts roughly every 30 seconds for keypad slot 1
  with `key=NO_KEY` even with **no physical keypad attached** - a periodic status
  heartbeat, not a keypress. `coordinator.py`'s `_handle_keypad_change` already guards
  exactly this case (`if key == KeypadKeys.NO_KEY.value: return`), confirmed correct
  against real, unsolicited panel traffic rather than only against a mocked message.
  `_decode_keypad_detail` (`helpers/transport.py`) parsed the same real `KC` frame
  correctly: `bypass_requires_code: True`, `beep_chime_by_area: (3,3,3,3,3,3,3,3)`,
  `function_key_lights: (0,0,0,0,0,0)` - no exception, no field misalignment.
- `XK` arrived as an unsolicited broadcast roughly every 30 seconds carrying real RTC data
  (decoded date/time matched the actual date this session ran), confirming the "M1-only,
  not for 3rd-party use" framing in `elk-m1.md` section 4.4's header describes the
  alarm-reporting handshake (`AR`/`ar`/`ax`) specifically, not the `XK` broadcast itself -
  the spec's own text says `XK` is sent "regardless of whether a device is connected," and
  it was, in fact, received here by a plain third-party listener.
- System trouble (`SS`) reported `Low Battery Control` and `Missing Keypad` active, and
  no others among the low indices - consistent with a bench setup with no battery and no
  keypad wired, which is independent, physical-world confirmation that `TROUBLE_INDEX_NAMES`
  indices 4 and 10 are correctly mapped (the higher indices, 30+, remain unverified per
  `protocol.md`'s "Trouble status" section - this run didn't exercise them since nothing
  here would set Display Message or Fire Trouble).

**Not covered by this run**: any write command (arm/disarm, output/lighting control, clock
write, custom value/counter write, zone bypass, task activation, voice) - deliberately
untested to avoid changing panel state with hardware present but unsupervised. Also not
covered: XEP/network transport, multi-panel, USB reassignment, soak duration, and running
the actual Home Assistant integration (`coordinator.py`, config flow) end-to-end against
this hardware rather than a standalone protocol script.

## Live run, 2026-09-05 (same session, follow-up): full command sweep, real passcodes

Sean authorized testing every command against the same bare panel, "mark any that are
blocked by a passcode." Same standalone-script method as the prior entry, not the Home
Assistant integration itself.

**Incident**: `cn` (Control Output ON, output 1, 5 seconds) produced an audible alarm sound
- Output 1 is the conventional siren/annunciator driver on ELK panels, and something audible
was evidently wired to it on the bench. This should have been flagged as a risk before
sending, not after. Confirmed resolved within the same session: `cs` (output status) read
all outputs off afterward (the 5-second timer had already elapsed), and `AS`/`AM` showed all
areas disarmed with no alarm active/no alarm memory throughout - the sound was the output
driver directly, not the panel's alarm logic ever engaging. No other output/lighting/task
command in this sweep is known to drive anything physically connected, but that was an
assumption proven wrong once already; a future live run should confirm what's wired to every
output before exercising any of them again.

**Passcode gating, with the real user passcode** (not present in this repository or any
file - entered interactively via `getpass` on Sean's own machine, never typed by the
assistant): sent `a0` (Disarm) to area 1 twice, once with a deliberately wrong code and once
with the real one.
- Wrong code: panel returned `IC` decoding to `user: -1` - explicitly rejected, not silently
  ignored.
- Correct code: panel returned `IC` decoding to `user: 1` (a valid user number), logged the
  event (`LD` event 1299, user number 2), and Sean independently confirmed the same code via
  a physically-connected keypad by bypassing zone 1 with it.
- A first cut of the test script mis-verdicted the correct-code case as "REJECTED" - it
  checked whether the substring `"IC"` appeared anywhere in the reply, but `IC` ("Send Valid
  Or Invalid User Code") is the same message code for both outcomes; only the decoded `user`
  field distinguishes them. Fixed to decode `user` from the actual frame before rendering a
  verdict, and re-verified against both real captured replies (accept and reject) before
  redelivering. Recorded here as a reminder that "the panel replied" is not the same
  question as "what the reply means" - exactly the distinction `docs/decisions.md` and
  `protocol.md` already try to hold code changes to.
- Confirms `a0`-`a:` (arm/disarm) and `zb` (zone bypass) are genuinely gated by the panel
  itself on a correct user code, independent of anything this integration does - the earlier
  session's finding (rejection with an invalid code) was necessary but not sufficient
  evidence on its own; this run supplies the missing accept-path half.

**Other findings from the same sweep** (no code required, per the protocol spec and
confirmed against real replies): `cf`/`cn` (output control), `cp`/`cr`/`cw` (custom values),
`cv`/`cx` (counters), `ka`/`kf` (keypad), `pf`/`pn`/`pt` (lighting - each produced a `PC`
broadcast, implying Global Programming "Xmit Light Changes" is enabled on this panel),
`tn` (task activation), `tr` (thermostat request), `ua` (user code areas), `zd`/`zv` (zone
definition/voltage), and the four commands `elkm1_lib` cannot encode at all -
`kc` (keypad status request), `rr` (RTC read), `st` (direct temperature request), `ld`
(indexed log request) - all built by hand from `elk-m1.md`'s literal wire formats and all
returned valid, checksum-correct replies. `pc` (raw PLC control) and `sp` (speak phrase)
got no reply, matching `elkm1_lib.message`'s own encoders, which declare `response_command
= None` for both - a documented protocol characteristic, not a passcode block. `zt` (zone
trigger) also got no reply; unlike `pc`/`sp` this is not explained by the encoder metadata
and is unverified why.

**Not covered by this follow-up run**: `dm` (display message) - not yet tested. An actual
arm-then-disarm cycle was deliberately not attempted: zone 1 was bypassed via keypad during
this session but zones 2-7 (area 1) still read `VIOLATED`, so a plain arm would not succeed
and a force-arm on genuinely violated zones risks an immediate real alarm the instant it
arms - a materially different risk than anything exercised so far, worth its own deliberate,
separately-scoped test with the output wiring understood first.

**`ts`/`tr` (thermostat set/request) - marked will-not-test, by Sean's decision (2026-09-05):
no Elk-connected thermostat is or will be present on this bench setup. This is a
deliberate scope decision, not an unverified gap - `climate.py`'s `ElkThermostat` entity
remains untested against real hardware and stays that way; see `docs/decisions.md`.

## Live run, 2026-09-05 (same session, second follow-up): all 8 areas confirmed

Sean asked to "test and verify all areas." Two independent methods against the real
passcode, both agreeing:
- `ua` (Request User Code Areas, read-only): decoded `valid_areas` bitmask
  `0b11111111` - all 8 areas authorized for this code.
- `a0` (Disarm) sent individually to areas 1-8 with the same code: all 8 returned
  `ACCEPTED` (`IC` reply, `user` field non-negative, consistently `2` across all areas -
  1-based user number, matching the same user this code identified as in the prior entry).

A real script bug surfaced and was fixed in the process: the test script's frame parser
split the serial buffer on `\r` alone, leaving a leading `\n` on every frame after the
first. That shifted the fixed-offset field slicing by one character, so the `UA` frame
(which happened to land second in the buffer, after an `IC` frame) silently failed to
parse - not a false negative on the panel's part, a bug in reading the reply. Fixed by
stripping `\n` before the offset-based field reads, and re-verified against the exact
captured buffer before calling it done.

**Update, 2026-09-05 (primary-source review)**: the `IC` `code`-field question above is now
resolved, not just unverified. Section 4.16 of the manufacturer's own
`ELK-M1_RS232_PROTOCOL.Ver+1.90.pdf` states the digit field is "Set to all zeros if code is
valid" - it only echoes the entered digits back when the code is *invalid* (so a monitoring
system can log what wrong code was tried), by design, not an artifact of the serial/PC access
path. The spec's own worked example for the invalid case
(`17IC000000030405060000100CC`, described as "Invalid user keypad code 3456") shows the
`UUU` user-number field as `000` - which is exactly what `elkm1_lib.ic_decode`'s
`int(msg[16:19]) - 1` turns into the `-1` sentinel this session already relied on. Every
byte offset `ic_decode` uses (`code = msg[4:16]`, `user = msg[16:19]`,
`keypad = msg[19:21]`) matches the spec's own field layout exactly, and the spec's noted
special user numbers (`201` = Program Code, `202` = ELK RP Code, `203` = Quick Arm) match
`elkm1_lib.users.Users.username()`'s special cases verbatim.

## Live run, 2026-09-05 (same session, third follow-up): `dm` (Display Message) against a real keypad

A physical keypad (assigned to area 1, confirmed via a live `ka` request) became available
partway through this session. Sean sent `dm` three times and read back the keypad's actual
16x2 LCD each time - a real gap in every earlier test this session, all of which sent `dm`
with nothing physically present to display it.

- **`clear=0`, `clear=2`: nothing displayed.** The keypad stayed on its normal idle screen
  (line 1 "Not Ready 14 Zn" - which also independently confirms the zone-violated count
  from the earlier `zs` test: 14 open loops, matching zones 1-8 and 10-15). No error, no
  reply (`dm` has none by design), just silence from the display.
- **`clear=1`: displayed correctly.** This is the value the manufacturer's own worked
  example in the RS-232 spec uses (`2Edm11100020abc^efghijklmnopABCDEF^HIJKLMNOP00B2`,
  "Would display 'abc' on the first line and 'ABCDEF' on the second") - the spec's own
  prose description of the three `clear` values ("0=clear message, 1=clear message with
  * key, 2=Display until timeout") does not make this obvious; only testing the example's
  own value against real hardware settled it. `_async_display_message_service`'s schema and
  `ElkDataUpdateCoordinator.display_message`'s default both changed from `0` to `1` as a
  result - `0` was the shipped default and would have silently displayed nothing.
- **Line placement does not match a naive reading of the wire format.** The physical 16x2
  keypad keeps its top row pinned to the persistent area-ready summary; both submitted
  lines ("Hello Sean", "ELKM1 TEST OK") appeared folded into the bottom row's existing
  rotating status carousel, alongside "LOW BATTERY" and "Output 2 trouble" - not written to
  two independent fixed rows the way the spec's own two-line example prose implies. This
  may be specific to this keypad model/firmware; not asserted as universal.
- **`beep=True` produced no audible beep**, confirmed at the wire level first (the
  transmitted frame's beep field really was `"1"`, checked directly against
  `dm_encode`'s own output) so this is not a transmission bug on this integration's side.
  No explanation is claimed - could be a keypad-model limitation, a Global Programming
  silent-keypad option, or something else; recorded as unverified, not guessed at.

## Live run, 2026-09-05 (same session, fourth follow-up): the actual integration, not just protocol scripts

Every earlier live test this session drove the wire protocol directly from standalone
scripts. This run instead built a minimal Home Assistant core instance by hand
(`homeassistant.core.HomeAssistant`, `ConfigEntries`, the loader, device/entity/area
registries) and called this integration's real `async_setup_entry` against COM3 - the
first time this session that the actual `coordinator.py`/`config_flow.py`/entity-platform
code touched real hardware, not a scratch script.

**Method note, read before trusting anything below without cross-checking it**: Home
Assistant's own `__main__.py` refuses to start on native Windows at all ("Home Assistant
only supports Linux, OSX and Windows using WSL"). That guard lives only in the CLI
entry point, not in `homeassistant.core` itself, so a manual, hand-assembled bootstrap
(bypassing the CLI) got further than expected - but every failure it produced had to be
independently cross-checked against an isolated repro before being trusted, because the
harness itself is incomplete and can produce false alarms. One did: a real-looking
`BaudProbeError` ("No standard baud rate produced a valid reply on COM3") turned out to be
caused by this improvised harness's own event-loop setup, not the product - calling the
exact same `open_probed_serial()` function directly, outside the hand-built HA instance,
succeeded immediately at 115200 baud. That result is not trusted and nothing was changed
because of it. This is recorded so a future reader does not repeat the same false alarm,
and so "the integration was tested against real hardware" is not overstated - the
connection-and-login path was exercised inside the real `async_setup_entry` call chain
successfully getting to entity setup, but the specific baud-detection failure text seen
along the way was an artifact of this test method, not a finding about the product.

**Real, confirmed bug found this way, independent of the harness issue above**:
`number.py`'s custom-value and counter entities crashed with `TypeError: float() argument
must be a string or a real number, not 'NoneType'` the moment they were first added to the
entity platform - not a timing fluke, a deterministic bug. `elkm1_lib.counters.Counter`
and `elkm1_lib.settings.Setting` both initialize their `.value` attribute to `None` and
only populate it once a `CV`/`CR` message arrives; Home Assistant calls `native_value`
(via `async_write_ha_state`) as soon as an entity is added to its platform, which happens
before any such message could possibly have arrived. Any panel with counters or custom
values configured would hit this on every fresh setup. Fixed both properties to check
`obj.value is not None` before calling `float()` on it. Checked every other
`int(obj.value)`/`float(obj.` occurrence across every platform file for the same class of
bug: all the others either wrap an attribute that defaults to `0` (`Light.status`,
`Thermostat.current_temp`/`heat_setpoint`/`cool_setpoint`, `Output.output_on` as a bool)
or are a different, already-safe pattern (`_get_enum_value`/`_enum_value` helpers in
`switch.py`/`binary_sensor.py`, which check `hasattr(obj, "value")` first and are
unwrapping a Python `Enum` member's `.value`, not an elkm1_lib element's field) - not the
same bug, confirmed by reading each one rather than assuming from a text match.

Not attempted in this run: entity forwarding for all nine platforms end-to-end (the test
stopped once the specific `number.py` bug and the harness artifact above were understood),
the config flow's own validation step, and unload/reload. This method is not a substitute
for running the real `pytest-homeassistant-custom-component` suite (which needs WSL, per
`docs/ha-test-harness-wsl` in the ha-dev-current skill) - it is a supplement that reached
real hardware once, not a repeatable CI-grade harness.

## Live run, 2026-09-05 (same session, fifth follow-up): `helpers/elk/` against the real panel after removing `elkm1-lib`

Phase 6 of the `elkm1-lib` removal (see `docs/decisions.md`): a standalone script loaded
only `helpers/elk/const.py` and `helpers/elk/message.py` directly (via a synthetic package
so their relative imports resolved without executing `custom_components/elkm1/__init__.py`
or any Home Assistant import) and drove COM3 with `pyserial` at 115200 baud, the same rate
confirmed in the first live run above. Read-only requests only - no output/arm/disarm
command was sent, so this carried none of the risk the earlier `cn` (output control) test
did.

Seven requests, each correlated to its own reply (discarding any unrelated broadcast in
between, the same rule `Connection._write_stream()` uses) and decoded without error:
`vn` (`elkm1_version: 5.3.18`, matching the first live run), `as` (all eight areas
disarmed, `timer_seconds: 0` - the new M1-4.11+ field this port added, see
`docs/protocol.md`), `ss`, and the four commands `elkm1-lib` 2.2.15 could not encode at
all: `kc` (keypad 1, forced reply `key: 0` as the spec documents for a requested read),
`rr` (a real RTC string), `st` (group 0 device 1, `-60` - no probe enrolled at that slot,
consistent with the panel's no-thermostat scope decision in `docs/decisions.md`), and `ld`
(log entry 1, decoded to a real event/timestamp: `2026-09-05T05:00:00+00:00`). Every
encode produced a checksum-correct frame the panel accepted, and every decode matched the
`message.py` docstring's own field-offset claims - the two bugs the full pytest gate had
already caught during the port (`_pc_all_decode`'s field offsets, `kc_detail_decode`'s
missing exception handling) did not surface here because neither `PC` nor a supplemental
`KC` frame with malformed fields occurred on this bare panel; both are covered by
`tests/test_transport.py` instead.

Not attempted in this run: driving the real `helpers/transport.py`/`coordinator.py` code
path against hardware (the fourth follow-up entry above already did this against the old
dependency; a repeat against the new code is tracked as a follow-up, not blocking, since
the object model and method names were deliberately preserved during the port) and any
write/command path (`al`, `cn`, `cf`, `zb`, etc.) - this run was read-only status/version
requests only.

## Live run, 2026-09-05 (sixth follow-up): the real integration, post-`elkm1-lib` removal, plus a reusable script

Closes the gap the fifth follow-up entry left open: this run drove the actual
`custom_components/elkm1` code - `async_setup_entry`, `ElkDataUpdateCoordinator`, every
platform's entity-registry forwarding, and `async_unload_entry` - against the same real
panel on COM3, now running entirely on `helpers/elk/` with the `elkm1-lib` dependency
already removed. The fourth follow-up entry above did this once against the *old*
dependency; this is the first time the new, in-repo protocol stack has been exercised
end-to-end this way, not just through `helpers/elk/message.py`'s functions directly (the
fifth follow-up).

**Method**: a new, permanent script, `scripts/live_debug_check.py`, replaces the one-off
hand-assembled harness the fourth follow-up entry built and discarded. It uses
`pytest_homeassistant_custom_component.common`'s `async_test_home_assistant`/
`MockConfigEntry` helpers directly (importable standalone, without the package's `plugins.py`,
which needs `fcntl` and Linux/WSL - see the `ha-dev-current` skill), copies
`custom_components/elkm1` into a throwaway temp config dir so the loader has a real
on-disk integration to discover without writing test-harness `.storage/` clutter into this
repo, and forces a fresh custom-component scan (`hass.data.pop(loader.DATA_CUSTOM_COMPONENTS,
None)`) so the loader doesn't just import the domain-colliding *built-in* core `elkm1`
integration (`hassfest`'s own "Domain collides with built-in core integration" warning is
real - a naive script that doesn't do this loads the wrong one, silently).

**A harness-only false alarm, same class as the fourth follow-up's `BaudProbeError`**:
`ElkDataUpdateCoordinator.__init__` doesn't pass `config_entry=` explicitly to
`DataUpdateCoordinator.__init__`, so it relies on `homeassistant.config_entries.current_entry`
(a `ContextVar`) to identify its owning entry - core logs this as a soft deprecation
notice in real use (`custom_integration_behavior=ReportBehavior.IGNORE`), but the notice's
fallback path (`homeassistant.helpers.frame.report_usage`) raises a hard `RuntimeError`
when it cannot find a real integration-loader stack frame at all, which this standalone
script's call stack never has (real production setup always does). Confirmed as harness-
only, not a product bug, by patching `frame.report_usage` to a no-op for the duration of
the setup call and rerunning - the same real hardware, same result either way. Not treated
as a coordinator.py defect to fix: passing `config_entry` explicitly would be a reasonable,
low-priority modernization (it's what the notice itself recommends), but it changes nothing
about real, production runtime behavior, so it's left as a documented observation rather
than acted on unprompted.

**Live results, three separate runs (same panel, same result each time), zero exceptions
or tracebacks in any run**:
- Setup reached `ConfigEntryState.LOADED` every time; `panel_version=5.3.18` (matches
  every earlier live run this session), `connected=True`, `last_update_success=True`.
- Panel-reported element counts: 208 zones, 208 outputs, 16 thermostats, 64 counters, 20
  settings, 32 tasks, 16 keypads, 256 lights (the panel's hardware maximums, not what's
  actually wired/named).
- **213 entities** forwarded to the entity registry: `alarm_control_panel` (7),
  `binary_sensor` (44), `scene` (1), `sensor` (2), `switch` (159). Zero `climate`/`light`/
  `number`/`time` entities - correct, not a gap: no thermostat, PLC light, counter, or
  custom-value/time element on this bench panel has ever been *named* (`.configured`),
  and `async_add_dynamic_entities` only forwards configured elements, matching every
  platform file's documented behavior.
- `num_areas=7` in this snapshot, one less than the eighth-area confirmation the second
  follow-up entry above already established via `ua`'s bitmask and a real disarm to all 8
  areas. Not a contradiction: `coordinator.py`'s `num_areas = max(len(configured_areas), 1)`
  counts areas whose name had synced (`SD`) by the moment of the first refresh snapshot,
  a timing-sensitive count, not a fixed hardware property the way `ua`'s per-code
  authorization bitmask is. Left unverified whether the eighth area's name simply hadn't
  arrived yet in this run's short window; not chased further since it doesn't affect
  entity correctness (the panel's own area count feeds every area-scoped platform the
  same way regardless of which specific run first observed it).
- The panel's Global Programming broadcast settings were, as expected for a 10-second
  observation window with nothing changing, reported unconfirmed by
  `helpers/panel_settings.py` - and, confirmed live for the first time, this correctly
  raised a real Repair issue (`repairs_issue_registry_updated` event observed directly,
  `issue_id=outdated_panel_broadcasts_<entry_id>`), the Gold `repair-issues` rule's
  implementation working end-to-end against real hardware, not just a mocked coordinator
  in a unit test.
- Two pre-existing, disabled-by-default trouble binary sensors (`EEPROM Memory Error`,
  `Flash Memory Error`) were correctly registered but not added to the entity platform
  ("Not adding entity ... because it's disabled") - the Gold `entity-disabled-by-default`
  rule's implementation, also confirmed live.
- Unload reached `ConfigEntryState.NOT_LOADED` cleanly every time, with the coordinator's
  connection/task cleanup producing no warnings or lingering-task errors.

**Not attempted in this run**: any write/command path (unchanged scope from every prior
entry), the config flow's own validation step (this script calls `async_setup_entry`
directly, the same shortcut the fourth follow-up entry used), and a soak duration beyond a
short observation window.

## Live run, 2026-09-05 (seventh follow-up): write commands, via `scripts/live_full_verification.py`

Sean ran the new guided, per-step-confirmed write-command script against the same panel.

**Confirmed working correctly**: `display_message` (area 1's keypad, as already established
in the third follow-up entry above); the entity-states snapshot (46 real states written, 1
unavailable - `scene.elk_m1_task_01`, expected since no `TC` sync had reported that task
configured yet); and, critically, the **arm-refusal safety guard**: area 1 was correctly
refused (14 violated zones assigned to it, matching every earlier finding about this bench
panel's unwired open loops) before any arm command was ever sent. Output, task, and light
control were skipped entirely (left blank at the prompt) - by design, since nobody has
verified what those numbers actually drive on this specific panel.

**Real bug found**: `set_panel_time` and a separate zone-bypass attempt both failed with a
confirmation timeout (`... was not confirmed by a valid RR/ZB response`), and the periodic
status refresh spuriously timed out waiting for all of `AS`/`AZ`/`CS`/`SS`/`LW` at once. Root
cause: a single corrupted `RR` reply (real serial-line noise, correctly rejected by the
checksum check) cascaded into a multi-second stall of every command queued behind it,
because `helpers/elk/connection.py`'s write-queue drain loop blocks the whole queue - not
just the command that lost its reply - for up to `MESSAGE_RESPONSE_TIME` per lost reply.
Full analysis and the fix (`MESSAGE_RESPONSE_TIME` 5.0s -> 1.5s) are in `docs/decisions.md`
2026-09-05. The system failed safely throughout: no crash, no bad data accepted, no
persistent broken state, and the unload at the end was clean - this was a reliability/
latency bug under real serial-line noise, not a data-integrity or safety bug.

**Not yet re-verified live**: the fix itself. The panel was not available for a repeat write-
command pass in the same session; `tests/test_elk_connection.py` gained unit coverage for
the new ceiling and the "one lost reply doesn't block the next queued item forever"
behavior, but nothing has re-created the original corrupted-reply condition against real
hardware since the fix landed. Re-run `scripts/live_full_verification.py`'s `set_panel_time`
and `zone_bypass` steps next time the panel is accessible to close this out.
