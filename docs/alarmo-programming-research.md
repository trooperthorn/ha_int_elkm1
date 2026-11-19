# What Alarmo can lend ha_int_elkm1 for panel configuration with the Installer Program Code

Research note, 2026-09-06. Repository: `~/repos/ha_int_elkm1` (version 2026.09.06.1,
floor core 2026.9.0, harness 0.13.362, Platinum). Alarmo reference: `~/repos/alarmo-reference`
at v1.10.19 (commit 169e134, 2026-08-09). Protocol reference:
`~/repos/vendor-docs-reference/docs/elk-m1.md` (RS-232 ASCII Protocol Rev 1.90). Manual:
`ELK_M1_Installation&Programming_Manual.pdf` in the repository (firmware 5.3.10 era). ElkRP
decompile: `~/workspace/ElkRP_Feature_Catalog.md`.

## 1. The answer in one paragraph

The ELK-M1 cannot be programmed over the RS-232 ASCII protocol this integration speaks. Zone
definitions, area timers, keypad function keys, global options, report codes, rules, and the
Installer Program Code itself are all written either from a keypad in Installer Programming
mode (menu 9, protected by the Installer Program Code, factory default 172839) or from ElkRP over
a separate, undocumented binary EEPROM protocol authenticated by the RP Access Code (factory
default 246801). The ASCII protocol has exactly one configuration-writing command family that
touches credentials, `cu`/`CU` (Change User Code), and three read-only or advisory ones
(`ua`/`UA` code validation, `IC` code-entry broadcast, `IE` installer-mode-exited broadcast).
So "bring Alarmo in to configure the panel with the Programming Passcode" cannot be done as
stated: nothing in Alarmo, and nothing in the wire protocol, reaches the panel's programming.
What can be done is narrower and still useful: adopt Alarmo's user, code, and permission
model on the Home Assistant side, back it with the panel's real `cu`/`ua`/`IC` primitives, and
use the Installer Program Code only where the panel itself accepts it over the wire, which is
as an authorization code for `cu` (unverified) and as a validation target for `ua` (verified
in spec).

## 2. What the Installer Program Code can and cannot do over the wire

| Capability | Wire path | Status | Source |
| --- | --- | --- | --- |
| Enter Installer Programming (menu 9) and edit any panel setting | None. Keypad only. | Not possible over ASCII | Manual p13, p22, section 3.2 p21 |
| Program from a computer | ElkRP binary EEPROM protocol, authenticated by the RP Access Code, not the Installer Program Code | Not the ASCII protocol; not in scope for this integration | ElkRP catalog section 1; manual section 3.3 p21 |
| Validate that a code is the Installer code | `ua` request, `UA` reply field `L` = `3` (Installer), `4` = ELKRP | Encoder and decoder exist (`ua_encode`, `ua_decode`); the hub sends `ua` with code 0 only as a sync sentinel | Spec section 4.36; `helpers/elk/hub.py` line 105 |
| Know that the installer code was just used at a keypad | `IC` broadcast, `UUU` = `201` (Program code) on firmware 4.4.2+ | Decoded; `users.username()` returns `*Program*` for it; surfaced through `changed_by` and `last_user_name` | Spec section 4.16; `helpers/elk/users.py` |
| Know that someone finished keypad programming | `IE` broadcast | Consumed internally as a full resync trigger, not exposed | Spec section 4.17; `helpers/elk/hub.py` |
| Change a user's PIN, area mask, or restriction flag | `cu` request, `CU` reply; needs a Master code or the user's current code; firmware 4.3.9+ | No encoder or decoder; marked "intentionally unsupported pending a separate security design and live qualification" | Spec section 4.10; `docs/protocol_coverage.md` |
| Arm or disarm using the installer code | `a0`-`a6` with the installer code as the six-digit code | Works today through the existing arm path (manual: installer may arm any area, disarm only areas it armed) | Manual section 2.4 p14 |

Whether the panel accepts the Installer Program Code as the authorization field of `cu` is
unverified. The spec says "Master code or the current code of the user being changed"; the
manual says the installer code can access keypad menu 6 (Change User Codes), which is the same
operation from the keypad side. That is suggestive, not proof, and needs a live test.

## 3. Alarmo's feature surface, mapped to what the panel offers

Alarmo is a software alarm: its store (`custom_components/alarmo/store.py`) holds areas, modes
with exit, entry and trigger times, sensors with per-mode membership and delay flags, users
with bcrypt-hashed codes and permissions, automations (notifications and actions), sensor
groups, MQTT bridging, and a master area. The table says, for each Alarmo area, whether the
ELK-M1 already implements it in hardware, whether the ASCII protocol lets Home Assistant
read or write it, and what borrowing it would mean.

| Alarmo area | Alarmo data | ELK-M1 equivalent | Readable over ASCII | Writable over ASCII | Verdict |
| --- | --- | --- | --- | --- | --- |
| Users and codes (`UserEntry`) | name, bcrypt code, enabled, can_arm, can_disarm, is_override_code, area_limit, code length and format | User 1-199 PIN, name, per-area mask, arm and disarm privileges, bypass privilege, access privilege, temporary code, Master flag (keypad menu 2 and menu 6) | Names via `sd` type USER (done). Area mask, code length, and code type for a known code via `ua` (decoder exists). Privileges (arm, disarm, bypass, temporary) are not readable at all. | PIN, area mask, and restriction flag via `cu`. Arm, disarm, bypass, access, temporary, and Master privileges are keypad or ElkRP only. | Partial borrow. The most concrete opportunity in this list. See section 4. |
| Code enforcement policy (`Config`) | code_arm_required, code_disarm_required, code_mode_change_required, code_format | The panel always requires a code for disarm; arming without a code is a global option ("Quick Arm", `IC` code 203); code length 4 or 6 is Global option | No direct read; `UA` reports code length | Not writable | Do not borrow. The panel enforces this; the integration's `_attr_code_arm_required = True` already mirrors the safe side. |
| Areas and modes (`AreaEntry`, `ModeEntry`) | per-area enabled modes, exit_time, entry_time, trigger_time | Area definitions: Entry 1/2 and Exit 1/2 timers, arm levels Away, Stay, Stay Instant, Night, Night Instant, Vacation; siren cutoff timers | Timer countdowns arrive live in `EE` (entry/exit) and `AS`; programmed values are not readable | Not writable | Do not borrow as configuration. Already surfaced as state (the alarm entity reports pending timers from `EE`). |
| Sensors (`SensorEntry`) | type, modes, use_exit_delay, use_entry_delay, always_on, arm_on_close, allow_open, trigger_unavailable, auto_bypass, area | Zone definition (37 types, `ZoneType`), zone flags (bypassable, force-arm, chime, cross-zoned, swinger shutdown, silent, per ElkRP `ZnFlag1Bits`/`ZnFlag2Bits`), zone area | Definition via `zd`/`ZD` (done), area via `zp`/`ZP` (done), flags not readable | Not writable | Do not borrow as configuration. Worth borrowing as a read-only "zone role" presentation (section 5). |
| Sensor groups | count-of-events cross-zoning with a timeout | Cross-zoned flag plus Global cross-zone verify time | Not readable | Not writable | Do not borrow. |
| Automations and notifications | triggers on arm, disarm, trigger, failed_to_arm, invalid code; actions and push notifications with actionable buttons | Panel rules engine (WhenThen) is invisible over ASCII; the integration already fires `elkm1.log_event` from `LD` | Effects only | Not writable | Borrow the event vocabulary, not the engine. See section 5. |
| MQTT bridge | state and command topics per area | None | n/a | n/a | Not relevant. |
| Master area | one virtual entity that arms and disarms every area | Not in the panel; "arm all areas" is a keypad or rules operation | n/a | Per-area `a0`-`a6` can be issued in sequence | Optional small borrow: a master `alarm_control_panel` that fans out per-area commands. Unrelated to programming. |
| Ready-to-arm reporting | `ready_to_arm_modes` websocket and attribute | Area "ready to arm" is in `AS` arm-up state | Done | n/a | Already covered. |
| Custom frontend panel | a `panel_custom` settings UI with Sensors, Codes, General, Actions tabs | ElkRP | n/a | n/a | The pattern is borrowable; the 2026.4 blog post says custom panels using `ha-*` components are unsupported and break per release. A panel would only have real content for section 4's user store and for read-only zone roles. |

## 4. The one real opportunity: a user and code manager backed by `cu` and `ua`

This is the part of Alarmo that maps onto something the panel will actually accept over the
wire. It is also the part the repository has explicitly deferred: `docs/protocol_coverage.md`
lists `cu`/`CU` as "intentionally unsupported pending a separate security design and live
qualification". That design is what a follow-up task would produce. The pieces:

**Panel-side facts to build on.**

- `cu` (spec 4.10): request `23cu ccc [12 hex auth code] [12 hex new code] NN R CC`. `ccc` is the
  user number, `NN` an area bitmask (`00` = leave areas unchanged), `R` the restriction flag
  (`0` normal write, `1` set restriction so the code is unusable and cannot be reprogrammed,
  `2` clear). Reply `CU` returns the user changed, `000` for a bad authorization code, `255`
  for a duplicate code. Firmware 4.3.9+.
- `ua` (spec 4.36): request with a six-digit code, reply carries the area mask, code length,
  and code type (User, Master, Installer, ELKRP). This is a code validator with no side effect
  and no risk of lockout; the repository already sends it on every sync.
- `IC` (spec 4.16): for an invalid keypad entry the panel echoes the digits typed so "3rd party
  systems with their own user database can react". This is the panel's own hook for a Home
  Assistant-side user database, exactly Alarmo's model.
- The panel cannot report a user's privileges (arm, disarm, bypass, temporary, master). Those
  stay in keypad menu 2 or ElkRP. A Home Assistant user store would therefore hold a
  Home Assistant-side view of privileges that the panel does not know about, and vice versa.

**What to borrow from Alarmo.**

- The `UserEntry` shape: name, enabled, can_arm, can_disarm, area_limit, code length. Drop
  `is_override_code` and bcrypt storage in favour of never storing the PIN at all: the panel is
  the credential store, `ua` is the verifier, and `cu` is the writer. Home Assistant would keep
  user number, name, and a Home Assistant-side privilege overlay only.
- The `_validate_code` flow in `alarm_control_panel.py` (lines 323 to 410): resolve the user
  from the code, check area permission, check can_arm or can_disarm for the requested state,
  set `changed_by`. In the ELK version the "resolve user" step is a `ua` round trip rather
  than a bcrypt scan, and the panel's own `AS` confirmation remains the final arbiter.
- The `enable_user` and `disable_user` services (Alarmo `services.yaml`): map directly onto
  the `cu` restriction flag (`1` set, `2` clear). This is the cleanest single feature: it is
  reversible, it does not change any PIN, and it is the operation a homeowner actually wants
  from an automation ("disable the cleaner's code outside Tuesday 9 to 12").
- The events `invalid_code_provided`, `no_code_provided`, `command_not_allowed`,
  `failed_to_arm`: fire the same vocabulary from the `IC` handler and from arm failures, so
  Alarmo-style notification blueprints work against the ELK entity unchanged.

**Where the Installer Program Code fits.**

- As the `cu` authorization code, if live testing shows the panel accepts it (unverified). If it
  does not, the Master code (factory default 3456) is the documented authorizer, and it must
  be entered per call, not stored, following the repository's existing rule that the stored
  PIN must never silently authorize a security-relevant write (`binary_sensor.py` line 192).
- As a `ua` validation target: a diagnostic that reports "the code you entered is the
  Installer code" (type 3) without exposing it, useful for a config-flow step that checks a
  code's type before offering privileged operations.
- Nowhere else. It cannot enter programming mode over the wire, and the RP Access Code is a
  different secret that the ASCII protocol never carries.

**Security constraints the design must state before any code is written.**

- `cu` is a credential write to a life-safety panel. It needs the same two-source rule the
  ASCII port had: spec plus live qualification, with a duplicate-code and bad-auth test.
- The restriction flag with `1` makes a code unusable and "no reprogram"; the spec wording is
  ambiguous about whether `2` always reverses it. Test on a throwaway user number first.
- Never log the auth or new code fields; the existing `IC` handling already redacts valid codes
  because the panel zeroes them, but `cu` frames carry both codes in clear ASCII.
- Codes must be entered per call through a service field with a password selector, or through
  a config-flow step, never persisted in the entry.
- Keep `_attr_code_arm_required = True`; do not import Alarmo's "code not required" toggles.

## 5. Smaller borrowings that need no new protocol work

- **Zone role presentation.** Alarmo's sensor editor shows each sensor's type and which modes
  include it. The ELK equivalent is already readable: `ZoneType` from `zd` and the area from
  `zp`. A read-only attribute set or diagnostics section that renders "Zone 3, Burglar
  Perimeter Instant, Area 1, bypassable unknown" gives the homeowner Alarmo's overview without
  pretending to edit it. The zone flag byte layout from ElkRP (`ZnFlag1Bits`) is documented but
  not readable over ASCII, so the flags column stays "unknown", said out loud.
- **Event vocabulary.** Alarmo's `EVENT_*` names are a good, stable contract for blueprints.
  Fire `elkm1` events with the same names from existing handlers (`IC` invalid entry, arm
  failure, `EE` entry delay start, `AM` alarm memory).
- **Master entity.** One `alarm_control_panel` that fans out to every configured area. Alarmo's
  `MasterConfig` is the model. Needs a decision on the state merge (Alarmo shows the lowest
  common state).
- **Programming-mode awareness.** Expose `IE` as an `elkm1.installer_programming_exited` event
  and, from the `LD` log codes 1354/1355 (local programming begin and end) and 1363/1364 (remote
  programming), a binary sensor "panel in programming mode". This is the only programming
  fact the wire exposes, and it is the right trigger for the existing full resync.
- **Existing `alarmo_auto_setup` service.** It only posts a notification listing zones. If the
  user store above is built, this service becomes redundant and should be retired rather than
  extended.

## 6. What must not be attempted in this repository

- Any zone, area, keypad, global, or rules programming. That is the ElkRP binary protocol,
  reverse-engineerable from `M1CtlHdr.cs`, and the ElkRP catalog already recorded the decision:
  "a Home Assistant integration operates a configured system, it does not reprogram one". A
  wrong EEPROM offset corrupts a real panel.
- Changing the Installer Program Code or the RP Access Code. Neither is reachable over ASCII,
  and the manual warns that a lost installer code makes local programming impossible.
- Replicating Alarmo's code-optional arming.

## 7. Suggested next steps, in order

1. Live qualification of `ua` with a real code of each type (user, master, installer), recorded
   in `docs/live_qualification.md`. Zero risk, confirms the type field on firmware 5.3.18.
2. Write `docs/security.md` section "User code management over cu" covering the constraints in
   section 4, then add `cu_encode` and `cu_decode` with tests, still uncalled.
3. Live test `cu` restriction set and clear on a spare user number with the Master code, then
   with the Installer code, to settle the unverified authorization question.
4. Implement `elkm1.disable_user` and `elkm1.enable_user` (code entered per call), then a
   `set_user_code` service if step 3 passes.
5. Add the programming-mode binary sensor and the `IE` event; add the Alarmo-named events.
6. Only then decide whether a custom panel is worth its per-release `ha-*` liability.

## 7b. What a user would newly get

The suggestions restated as Home Assistant surface. Nothing here programs the panel.

| Surface | Today | After | Backed by | Step |
| --- | --- | --- | --- | --- |
| Service `elkm1.validate_code` | None | Enter a code once (password field); response gives valid areas, length, and type (user, master, installer, ELKRP). No side effect, nothing stored. | `ua`/`UA` | 1 |
| Services `elkm1.disable_user`, `elkm1.enable_user` | None | Restrict or restore a user number so its PIN stops or resumes working at every keypad; authorizing code entered per call. Automatable. | `cu` restriction flag 1 and 2 | 4 |
| Service `elkm1.set_user_code` | PINs change only at a keypad or in ElkRP | Set a user's PIN and optionally its area list, authorized by the Master code or possibly the Installer code; duplicates and bad authorization reported. | `cu`/`CU` | 4, after step 3 |
| Event `elkm1.code_entered` | Only the `changed_by` attribute | Per keypad entry: user number, name, keypad, type (including installer 201). | `IC` | 5 |
| Event `elkm1.invalid_code_entered` | Logged only | Keypad number and digit count per rejected entry; digits withheld by default, optional for installs with their own user database. | `IC` user 000 | 5 |
| Alarmo-named events | None | `failed_to_arm`, `command_not_allowed`, `no_code_provided`, `invalid_code_provided`, so Alarmo notification blueprints work unchanged. | arm path, `IC` | 5 |
| Binary sensor `elk_m1_programming_mode` | Nothing visible | On during keypad or ElkRP programming, `mode` attribute local or remote. | `LD` 1354/1355, 1363/1364, `IE`, `RP` | 5 |
| Event `elkm1.installer_programming_exited` | Internal only | Fires when programming ends. | `IE` | 5 |
| Attribute `last_user_type` | `*Program*` name only | Enum: user, master, installer, elkrp, quick_arm. | `IC`, `UA` | 1, 5 |
| Zone attributes `zone_role`, `zone_area` | Raw definition number | Readable text on every zone entity plus a diagnostics table; flags shown as unknown. | `zd`, `zp` | 5 |
| Diagnostics user table | None | Number and name for 199 slots; no PINs, no privileges. | `sd` USER | 5 |
| Master alarm entity | One per area | One entity that arms or disarms all areas, lowest common state. | `a0`-`a6` per area | optional |
| Blueprints | Zone listing, state sync | Scheduled user enable/disable; invalid-code notify with keypad; unexpected remote programming notify. | services and events above | 5 |
| Documentation | `cu` intentionally unsupported | docs/security.md section; protocol_coverage.md rows move to implemented; live_qualification.md entries. | | 1 to 4 |

Still not supported afterward, deliberately: zone definitions, area timers, keypad keys, global
options, report codes, rules, the Installer Program Code, and the RP Access Code.

## 8. Unverified

- Installer Program Code accepted as the `cu` authorization field.
- Restriction flag `2` fully reverses flag `1` on firmware 5.3.18.
- `UA` type field values on 5.3.18 (spec says firmware 4.3.6+; not yet exercised live with a
  non-zero code).
- Whether `IC` code `201` is emitted for installer-code arm and disarm on 5.3.18 (spec says
  4.4.2+; `users.username()` handles it but no live log has shown it).
