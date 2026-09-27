# ElkRP Feature Catalog

Comprehensive functional catalog of ElkRP 2.0.41 (Elk Products' Windows
programming tool for Elk-M1/M1G security and automation panels), built by
decompiling the shipped application and reading the reference/example
databases it ships with (`C:\ProgramData\RP\Controls2.mdb`,
`ElkAccts2.mdb`, `Ops2.mdb`).

The decompiled tree this was built from is **not retained** - it was vendor
binaries plus decompiler output, reproducible from a ElkRP install if ever
needed again. This catalog is the durable artifact of that work.

**Purpose**: (1) a complete inventory to compare against `ha_int_elkm1`'s
coverage of the panel; (2) a functional specification for a future modern
replacement application, since ElkRP's .NET Framework/VB6-COM runtime
targets Windows XP/Vista-era environments.

**Method note**: ElkRP is ~85 files and tens of thousands of lines of
decompiler-reconstructed VB.NET (goto-heavy from `On Error Resume Next`
patterns). This catalog is a structural/functional survey - what each
screen does, what data it owns, what's programming-time vs. runtime - not a
byte-level trace of every code path. Byte-level EEPROM layout is separately
captured in `M1CtlHdr.cs` (not reproduced here) for whoever eventually needs
to build the binary programming protocol from scratch.

## 1. Protocol architecture (confirmed, not inferred)

ElkRP speaks **two unrelated protocols** to the panel, and never the public
ASCII automation protocol our Home Assistant integration uses:

- **Transport** (`ElkComm2.dll`, the one native/non-.NET file in the whole
  app): a generic byte-pipe - serial, modem/TAPI dialing, USB, TCP/IP, TLS,
  AES - with a CRC helper (`AddByteToCRC`) and a raw send/receive API
  (`SendByte`/`SendMessage`/`GetMessage`). No protocol semantics live here.
  Its COM interface (`IElkSerialComm`, GUID
  `EB4FA41D-05DC-11D6-B70B-000103E7BDEC`) is fully documented via its
  managed interop wrapper, `Interop.ELKCOMMLib2.dll`.
- **Programming protocol** (`M1G2.dll`/`M12.dll`, the panel-logic modules):
  a proprietary, undocumented **binary EEPROM protocol** -
  `ElkCommConsts.cs` defines `PROTOCOL_M1` (CRC/ACK/NAK framed, distinct
  from `PROTOCOL_ELKLINK`, the cellular/ethernet relay path) and
  `M1CtlHdr.cs` (2445 lines) defines the raw struct layout for every EEPROM
  record type (`typ_AREAS`, `typ_ZONECFGRAM`, `typ_KEYPADS`, `typ_RFCaddx`,
  `typ_GLOBAL1/2`, etc.). This is what an Installer/RP-code programming
  session actually uses. A full-text search of every decompiled file for
  the known ASCII command literals (`"vn"`, `"as"`, `"zs"`, ...) returns
  zero hits anywhere in ElkRP.

**Implication for a replacement app**: full panel programming (as opposed
to runtime status/automation, which `ha_int_elkm1` already covers) requires
reverse-engineering this second, undocumented binary protocol from
`M1CtlHdr.cs`'s struct layouts and the ~70 form files' send/receive logic -
a materially different and larger effort than anything the ASCII protocol
work this session did.

## 2. Connection methods

From `ElkCommConsts.cs`'s `CONNECT*` constants and `Account_Details`/
`C1M1_Config`/`XEPConfig`:

| Method | Constant | Notes |
|---|---|---|
| Direct serial | `CONNECTDIRECT` | RS-232 direct to panel |
| USB (via C1M1) | `CONNECTUSBC1M1` | USB cable to the C1M1 cellular/USB expander |
| Dial-up (auto/prompt/custom/established/local/hangup variants) | `CONNECTDIALAUTO` etc. (7 variants) | Modem/TAPI dialing to a panel's phone line |
| Wait for call / auto-answer | `CONNECTWAITFORCALL`, `CONNECTAUTOANSWER` | RP waits for the panel to call back |
| Network (plain) | `CONNECTNETWORK` | Non-secure TCP to M1XEP |
| Network secure | `CONNECTNETWORKSECURE`, `CONNECTNETWORKSECURETLS`, `CONNECTNETWORKSECUREAES` | Matches our `elks`/`elksv1_x` schemes, plus an AES-specific secure mode we don't distinguish |
| ElkLink proxy (cellular) | `CONNECTNETWORKELKLINKCEL` | Relay through Elk's own cellular gateway service |
| ElkLink proxy (ethernet) | `CONNECTNETWORKELKLINKETH` | Relay through Elk's own ethernet gateway service |
| M1Cloud | `CONNECTNETWORKM1CLOUD` | Elk's own cloud relay (`M1CloudProxy.cs`) |

`ha_int_elkm1` covers direct serial and plain/secure network (TLS
1.0/1.2/1.3) - the practical subset for a locally-connected HA setup. Modem
dial-up, ElkLink cellular/ethernet proxy, and M1Cloud are Elk's own hosted
relay/legacy-telephony paths, not applicable to local automation.

## 3. Reference data extracted (`C:\ProgramData\RP\Controls2.mdb`)

Static, panel-model-keyed lookup tables ElkRP ships with, independent of
any specific account:

| Table | Rows (M1G, latest ver) | What it is | Exported to |
|---|---|---|---|
| `WordLists` | 478 (ver 0.8) | Voice vocabulary: word ID → text, used by `sw`/`sp` and per-entity voice-announcement slots | `_extracted/WordLists_M1G.csv` |
| `EventLists` | 1358 (ver 5.3.0) | Numeric event-code → description for the `LD` log message's `event` field (`1001 = FIRE ALARM`, `4176 = ZONE 176 STATE`, `7208 = OUTPUT 208 STATE`, ...) | `_extracted/EventLists_M1G_5.3.0.csv` |
| `OutputLists` | (per version) | Named default output-control descriptions (e.g. "Control Voice/Siren Output 1") | not exported (low value - defaults only) |
| `AutoArmDefinitionLists` | 5+ | Scheduled auto-arm/disarm rule types: Auto Disarm, Auto Arm Away, Auto Arm Stay, Auto Arm Stay Instant, Auto Arm Night | not exported |
| `AudioModels` | 4 | Supported whole-house audio matrix brands for the Audio/zone-paging feature: Russound, NuVo, Proficient (plus None) | not exported |
| `VoiceLists` | (per version) | Higher-level "vm" (voice message template) catalog - pre-built spoken-announcement templates like `vm209 = Keypad Panic Alarm`, grouped by category (System Alarms, System Troubles, System Arm/Disarm, ...); references the `sd`/word-ID vocabulary underneath | not exported |
| `CountryModemVals` / `...ToBeAdded` | (per country) | Country-specific modem/dialing parameters for the dial-up connection path | not exported, low relevance |
| `Cities` | (large) | City catalog for `DawnAndDusk.cs`'s sunrise/sunset location picker | not exported, low relevance |
| `ListVers` | maps `PanelVersion` → `ListVer` | Version-selection table (which `WordLists`/`EventLists`/etc. row-set applies to a given firmware) | reference only |

Two of these (`WordLists`, `EventLists`) are directly actionable
improvements for `ha_int_elkm1` (see the prior session summary) - deferred
per your instruction, to be applied after this catalog and the full
comparison are done.

## 4. Account (EEPROM-backed) data model

From opening the example `ElkAccts2.mdb` (24 tables) with ElkRP's own
hardcoded connection credentials (baked into every shipped copy of the
app - not a real per-install secret):

| Table | Records | Programming-only or runtime-relevant |
|---|---|---|
| `Accounts` | 1 per panel | Connection method, `HasC1M1`/`IPPortC1`, `CloudID`, `MacAddress`, `Passphrase`, `NetNonSecure`, firmware/hardware versions - **mixed**: connection config is what our `config_flow.py` already owns |
| `AreaDefinitions` | 1 per area (8) | Report-code programming (open/close/duress/etc per area) - **programming-only** |
| `ZoneDefinitions` | 1 per zone (208) | Zone function/flags/name/voice-words/report-codes - **programming-only** (our integration reads the *resulting* zone state, doesn't program zone type) |
| `KeypadDefinitions` | 1 per keypad (16) | F-key definitions, LED state defaults, areas, HW version - **programming-only** |
| `POutputs` | 1 per output (208) | Name + 6 voice-word slots per output - **programming-only** |
| `Tasks` | 1 per task (32) | Name + voice-words - **programming-only** |
| `TelephoneNumbers` | 1 per dialer entry (16) | 20 numbers × 8 central-station account-routing groups - **programming-only**, central-station reporting |
| `UserCodes` | 1 per user (203) | PIN digits, partition, name, open/close report codes - **programming-only** (contains real PIN data structurally - never queried row content for real installs, only schema) |
| `SystemReportCodes`, `KPReportCodes` | 1 row | Central-station report codes for AC fail/low battery/etc - **programming-only** |
| `Globals` | 1 row | System-wide EEPROM flags: DST dates, cross-zone verify time, country code, program codes, anti-takeover - **programming-only** |
| `RulePackets`, `RuleComments`, `Constants`, `Variables`, `TextPackets` | many | The panel's own built-in WhenThen automation engine (see §6) - **functionally redundant with HA's own automation** |
| `SunriseSunset1`, `SunriseSunset2` | 1 row + precomputed table | Panel's own dawn/dusk calculation per programmed lat/long, used by Rules - **redundant with HA's `sun` integration** |
| `WirelessZones`, `ElkRFGroups` | per wireless zone/group | Caddx RF receiver/transmitter serials, keyfob button-event mappings - **programming-only** (pairing-time) |
| `X10Outputs` | 1 per X10 device (up to 256) | Name + voice-words for PLC/X10 lighting - **programming-only** |
| `VoiceMessages` | per custom message | 6-word-ID phrase slots - **programming-only** |
| `EmailDefinitions` | per email rule | SMTP address + message text - the panel/XEP can send its **own outbound alert email**, independent of any automation platform. Not in our `docs/protocol_coverage.md` at all. |
| `XEPConfig` | 1 row | Raw opaque blobs: `XEPBytes` (network setup), `AudioBytes` (zone-paging audio routing), `SurgardBytes` (SurGard IP central-station reporting) - **programming-only**, not individually addressable over the ASCII protocol |

`Ops2.mdb` (`Operators`, `Administration`) is ElkRP's own software
login/permission-level management - has nothing to do with the panel.

## 5. Form-by-form catalog

*(Populated from parallel exploration of the ~70 UI/logic form files.
Sections below fill in as each survey completes.)*

### 5.1 Account/UI infrastructure

**`Account_Details.cs`** (8700+ lines) — the master per-panel record:
customer name/address/contact, panel identity (type, serial number, HW/FW/
boot version, RP Access Code, date installed), **connection settings
(System URL/IP, Port, MAC Address, secure-port/passphrase for C1M1,
non-secure fallback)** - effectively ElkRP's own "device registry" entry,
the same connection info our `config_flow.py` collects. Also tracks Voice
List Version and Last Connected / Changed-and-Saved timestamps.

**`AccountMaster.cs`/`CachedAccountMaster.cs`/`PreviewAcctRpt.cs`** — a
Crystal Reports-based "print my full account programming" feature (30+
report bands, filtered per account, with `NESS`/`EZ8` variant flags). A
"generate a documentation/config-summary report" feature worth having in a
replacement's UX, not a runtime capability itself.

**`BrowseGroups.cs`** — hierarchical dot-path folder organization for the
account list (`Region.Branch.Site`). Setup-only, no panel meaning.

**`Conflicts.cs`/`ConflictsItemType.cs`/`ConflictsNag.cs`/
`Item_Differences.cs`** — ElkRP keeps a **full local shadow copy of panel
programming** that can drift from the panel's actual state; these screens
detect and resolve that drift per-item (choose panel-wins or DB-wins,
never a bulk merge), and block further programming until resolved. Real
quirk: **conflict detection is skipped by default over a cellular
connection** (must be triggered manually). Confirms the local-DB-as-cache
architecture a replacement would need to decide whether to keep.

**`Default_Or_Copy_Dlg.cs`/`GetNewItemID.cs`/`ImportOptions.cs`** — generic,
reused "create new item" workflow dialogs (custom vs. copy-from-existing;
new item ID/range; account-clone field exclusions). One non-obvious detail:
**keypad-wired zones use a fixed/reserved zone-type code of 13** in
ElkRP's data model (GetNewItemID's help text: "enter '13' in the second
box" for keypad-wired zones).

**`M1MsgBox.cs`/`PleaseWait.cs`/`ComboBoxValDesc.cs`/`MfgDlg.cs`** - pure
UI infrastructure/utility, except `MfgDlg.cs` which is Elk's own hidden
factory/production test menu (serial number programming, voice EEPROM
flash, current calibration) - confirms **panel voice prompts live in a
separately-flashable EEPROM image**. Out of scope for an installer/end-user
replacement app.

**Runtime-relevant connection-management behavior found in this batch**
(the most valuable findings here for a replacement app's connection layer,
regardless of which protocol it speaks):

- **`MiscStuff.cs`** drives a **15-second keepalive timer** while connected
  (`RestartKeepAliveTimer`/`SendKeepAliveMsg`) and a configurable
  **idle-disconnect timer** (minutes), paired with **`DisconnectWarning.cs`**'s
  hardcoded **20-second final countdown** before actually dropping the
  connection ("The connection will be terminated in 20 seconds..."). A
  modern client needs an equivalent heartbeat/idle strategy even over the
  documented ASCII protocol.
- **`ElkLinkLogin.cs`/`NoElkLinkConnect.cs`** — the live C1M1 cellular/
  ethernet **cloud-proxy authentication and connection-establishment flow**
  ("ElkLink"), letting ElkRP reach a panel with no static IP/port-forwarding
  by having the panel phone home through Elk's own relay. Explicitly warns
  that caching the password locally is a security tradeoff. This is a
  genuinely distinct remote-access path our integration doesn't support at
  all (we assume direct IP/serial reachability) - worth flagging as a real
  gap if remote access without port-forwarding matters to a replacement.
- **`NextCommTest.cs`** — live-pushes "days until next communicator test"
  to the panel, with a non-obvious midnight-relative day-counting
  convention (0 = later today, 1 = tomorrow, relative to the test's
  time-of-day). A maintenance feature with **no ASCII-protocol equivalent**.
- **`SystemVers.cs`** ("Enroll/Update Control and Devices") — bus-device
  enrollment (scan-and-enroll expanders/keypads, same action as keypad
  Installer Menu 01) plus per-device firmware/bootware version inventory
  and OTA-style firmware push. Real constraint: **firmware updates are
  disallowed over a cellular connection** (must use local or Ethernet-via-
  ElkLink). Also warns live if an area is armed during enrollment. Detected
  firmware variants hint at third-party integrations built into some panel
  builds: Z-Wave (ViziaRF, ELK-XZW), Centralite JetStream, Carrier
  Infinity, Insteon, Advantage Air, HAI Omnistat, Uplink Anynet/AES. No
  ASCII-protocol equivalent for enrollment/firmware inventory.
- **`OutdatedRP.cs`** — refuses to operate when the connected panel's
  firmware is newer than what the installed ElkRP understands. The
  **pattern** (explicit version-compatibility gating rather than silently
  misbehaving on unknown features) is worth adopting even without reusing
  the dialog.

### 5.2 Panel-programming screens

**`Area_Definitions.cs`** — Area/partition programming: name, Entry 1/2 and
Exit 1/2 delay timers, arming options, STAY-key scrolling. Per-area
Form_Send/Form_Receive (push/pull one area, not only bulk). One-time/
rare-change programming.

**`Keypad_Definitions.cs`** — Keypad programming (including the P212S
power supply, treated as a pseudo-keypad): name, area, backlight, key-beep
tone/volume, F1-F6 function-key → task bindings with optional illumination
event, "require code" per key. Feature availability is model-gated (P212S
shows a stripped-down panel). Auto-assigned zone number for a keypad's
wired input = `192 + item index` (confirms the 193-208 "keypad zones"
range used elsewhere). The F-key→task binding is a useful reference for
interpreting keypad function-key press events.

**`Outputs.cs`** — Output naming/voice-description assignment. Firmware
gated: pre-4.4.2, only outputs 1-32 can be named; outputs 65-208 are fixed
and cannot be renamed (matches our own `entity-disabled-by-default`
handling of that range). M1TWA listen-in module reserves outputs 7-10.

**`Tasks.cs`** — Task naming/voice-description assignment (word-
construction grid). Notable spec detail: **thermostat names are cosmetic
only** ("the M1 does not require thermostats to be named except to access
them via an app") - not required for functional control.

**`Telephone_Numbers.cs`** — Central-station dialer programming: per-number
name, phone number, dial attempts, reporting format, per-area (8) account
number routing (000000 = disabled for that number/area), a Type field
controlling backup-number chaining. Real workflow gotcha: **a number can't
be edited while the next number in the list is flagged as its backup** -
must flip the next number's type to 0 first. M1XEP IP central-station
config lives in a *different* form (XEPConfig). Voice Dialer can only be
triggered by Rules, never manually from this screen.

**`User_Codes.cs`** — PIN/user-code programming: PIN digits, name, per-area
authorization checkboxes (**at least one area must be selected** - no
unscoped codes allowed), plus a proximity/RF-card branch (Facility Code +
Card/PIN Number, with a random-code generator button) - confirms card-based
credential support alongside keypad PINs.

**`Report_Codes.cs`** — the single largest form (27k lines): Contact-ID/SIA
report-code programming across every reportable category (area open/close/
duress, zone alarm/trouble/bypass, user codes, keypad panic keys, system
events), tabbed per-area, with New/Restore code columns following Contact-ID
convention (new=prefix "1", restoral=prefix "3"). Rich bulk-edit UX
(right-click a column header to set/clear an entire column). Selective
send/receive per-area/per-keypad/whole-system, not only full-account
transfer. Programming-only; central-station config, not runtime status.

**`Globals_Data.cs`** — the catch-all system-wide settings form (labeled
G01-G42, tabbed): telephone/DST/country config, cross-zone verify timing,
loop response times, user-code length/lockout, common-area behavior,
siren/voice volume, burglary lockout, serial-port baud, two-way voice
timing, local programming code, auto-answer ring count. Heavy
firmware/hardware gating throughout (e.g. "not available in the EZ8",
"requires firmware 4.5.14+") - a real feature-availability matrix any
replacement needs to replicate per panel model. Entirely one-time setup.

**`DSTDates.cs`** — manual DST start/end override (vs. the panel's built-in
US rule); explicitly PC-software-only, not settable via keypad.

**`DawnAndDusk.cs`** — sunrise/sunset astronomical clock: lat/long/timezone
→ daily computed times, editable per-day, city picker. Real data-loss trap:
changing location/timezone invalidates manual per-day overrides with only
a warning, no undo. All displayed times are Standard Time; DST compensation
is applied panel-side. Feeds the Rules engine's sunrise/sunset triggers.
Redundant with HA's own `sun` integration for a replacement app.

**`DawnAndDuskCities.cs`** — static city → lat/long/timezone lookup table
(988 lines of data), no panel communication.

**`RPCodeChange.cs`** — changes the RP (Remote Programming) access code,
the master programming-session credential (distinct from user PINs).
Two-step confirm workflow with a real-world warning ("factory charge for
defaulting a control" if lost). Validates non-blank, non-all-zero, 6
digits, zero-padded. **Treat as a distinct secret with its own
change/audit workflow in a replacement**, separate from user codes.

**`SetTime.cs`** — pushes date/time to the panel's clock; shows current
system time for comparison. The one genuinely **operational** (not
one-time-setup) action in this batch - clock drift/power-loss recovery is
an ongoing maintenance need, though the ASCII protocol's own `rw`/`rr`
already covers this for our integration.

**`GetNewZones.cs`** — wizard to add zone records in 16-zone blocks (Group
1 = zones 1-16 hardwired; Groups 2-12 = expander/wireless 17-192; Group 13
= zones 193-208, "wired to keypads" - confirms the keypad-zone numbering
convention). Grays out groups that already exist. One-time setup.

**`Zone_Definitions.cs`** (13,705 lines, the largest and most central
per-item form) — zone type/function, hookup, name, voice words, and **two
bitfield flag bytes** whose exact bit layout is now documented:
`ZnFlag1Bits` = Bypassable / ActivityMon / FastResp / ForceArm / Chime /
CrossZoned / Abort / ListenIn; `ZnFlag2Bits` = HookUp / SwingerShutdown
(bit 3) / Partition-i.e.-area-assignment (bit 4) / SilentAlarm (bit 7).
Fixed 32-byte record (`ZNBytes`/`ZoneLen=32`) with its own CRC-based
dirty-tracking. **This bit layout is the single most valuable low-level
artifact in this batch** - it's the Rosetta Stone for what a live zone's
configuration flags mean, complementing (not duplicating) the ASCII
protocol's live zone-status bits our integration already decodes.

**`SearchRules.cs`** — generic reusable find/find-next dialog, no panel
communication, developer-UX only.

**`SelectCustomItem.cs`** — "Set To Custom" picker used by Report_Codes;
confirms custom report items are actually references back to a specific
zone record (reusing its name/function), not a free-standing custom-value
table.

**Cross-cutting takeaways from this batch**: nothing here is a live
runtime/status feature in the sense our integration cares about (zone
open/closed, area armed, output on) - it's all EEPROM programming for
names, thresholds, routing, and behavior flags. The two most reusable
artifacts for a replacement spec are Zone_Definitions' flag-bit layout and
the recurring **per-item selective Send/Receive pattern** (push/pull one
area/zone/keypad's report codes independently, not only full-account
transfer) used across Report_Codes/Outputs/Tasks/Zone_Definitions.

### 5.3 WhenThen rules engine

The panel's own built-in automation engine (like a self-contained HA
automations system running *inside* the panel's EEPROM/firmware,
independent of any external controller). Source: `WhenThen.cs` (14,440
lines - rule list/editor/packet marshalling), `WhenSelect.cs` (30,812
lines - the WHENEVER/AND/THEN vocabulary tree), the three operand-detail
dialogs, `WhenTextInput.cs`, `dsRules.cs`.

**Shape**: one Rule = one **WHENEVER** trigger + zero-or-more **AND**
conditions + one-or-more **THEN** results + an optional comment, stored as
a chain of up to 8 linked packets in a **528-slot EEPROM pool shared with
free-text messages** (8 chars of text = 1 packet slot; text fields capped
at 79 chars). The editor shows a live "% of packet memory used" gauge.
There is **no OR operator or grouping** - the AND chain is the only logic;
OR semantics require separate rules. Comparators (`Equal/NotEqual/Less/
Greater`) are uniform across counter/temperature/lighting-level/date/time/
zone-voltage conditions, each comparing against a fixed value, a named
custom setting/"Variable", or (for temperature) a counter.

**WHENEVER (triggers)**: Time Occurrence (time-of-day, sunrise/sunset
±offset, hour/minute equals, every N hours/minutes/seconds), Zone Change,
Output Change, Keypad F-key press (any/F1-F6, any/specific keypad), Keyfob
button press, Lighting change (individual or all, with command-source
filter: M1 vs. another device), Automation Task activation,
Security/Alarms (disarmed, armed-to-N-modes, ready-to-arm, day alert,
entry/exit delay start/end, exit error, closing report ring-back, key
switch tamper, alarm on/off by type [fire/fire-supervisory/burglar/
medical/police/aux1/aux2/CO/emergency/freeze/gas/heat/water/any], access,
chime state, zone-bypass state), Misc System (~20 trouble types + their
restorals, audio amp, dialer abort/cancel/autotest/kissoff, keypad
beep/lockout, log 80% full, local/remote programming begin/end, phone-line
ring/seize/hook/access, system startup), incoming ASCII text match,
counter change/expiry, thermostat setting change.

**AND (conditions)**: largely mirrors the trigger vocabulary as state
tests, plus Time/Date conditions (day-of-week, day-of-month, month, year,
each with the same comparator set), Light/Dark (astronomical), Last User
Was, Counter Is, Temperature Is, Thermostat state. Zone-status vocabulary
has a "basic" set (Violated/Normal/Troubled/Bypassed) and an "advanced" set
adding EOLR high/low states and analog-voltage comparisons.

**THEN (results)**: activate a Task, arm/disarm (immediate or delayed, per
area or all, plus "Set Expected Arm/Disarm Time Window"), output
on/off/toggle (timed or until a custom-setting time), lighting control
(individual: on/off/toggle/dim/bright/level/scene with fade rate; all:
all-on/all-off/off-by-housecode), Speak a voice message, send text out a
serial port, display text on a keypad (with beep/duration/clear options),
enable/disable chime, beep keypad(s), chirp the siren N times, set/add/
subtract/toggle a counter (or set it to a sensor's temperature), dial a
phone number (optionally speaking a message), send a pre-configured email,
set thermostat mode/setpoint, enable/disable a user code, enable/disable
voice, bypass/unbypass a zone (or all zones in an area), reset smoke
detector power, control a third-party whole-house audio system (brand-gated
- options grey out based on the configured audio model), show the arming
menu on a keypad. Free-text fields support insertion tokens: CR, CR/LF,
cutoff-timer value, custom-setting value, counter value, temperature
reading, and a dynamic zone-name variable.

**Hard limits**: 528 total packet slots (rules + text combined); 8 chained
packets per rule; 79-char text fields; 255-char rule display string; 8
areas; F1-F6 only.

**Notable engineering details**: rules/comments support copy-paste and
drag-drop reordering with manual packet-chain pointer re-threading; a
single-level undo; the in-memory grid model infers rule boundaries by
scanning for a literal `"WHENEVER"`-prefixed row rather than tracking them
structurally; Rules and Texts transmit as two distinct logical blocks
despite sharing one physical packet-address space; result options are
brand/model-capability-gated (audio, presumably thermostat too) rather than
a flat always-available menu.

**Relationship to `ha_int_elkm1`**: entirely separate from the ASCII
automation protocol. HA can only observe the *effects* of these rules
(zone/output/area state changes broadcast over the ASCII protocol) - it has
no visibility into or control over the rules themselves, since they aren't
exposed over that protocol at all. A replacement app wanting rules-engine
parity would need the undocumented binary programming protocol, not
anything `ha_int_elkm1` already speaks.

### 5.4 Wireless / X10 / lighting / voice

**`Wireless_Zones.cs`** — main "Wireless Zones" grid editor for one
Caddx-protocol RF receiver and all zones/transmitters on it: Zone, Name,
Enabled, Supervision, Opt1/Opt2, PIR, hardware loop, Fob ID, Tx ID,
Definition, plus receiver-level normal/fire supervision windows. Fire
supervision is bounded 4-255. The RF Rx/Tx identifiers are set once at
expander creation and cannot be changed afterward (delete/recreate only).
**Programming-only** - no live battery/signal polling here.

**`Wireless_Popup.cs`** — per-zone "Change Wireless Zone" detail dialog:
serial number/DL entry, Keyfob User ID, a supervision dropdown (0=Not
Supervised, 1=Normal, 3=Fire), a PIR checkbox, and a **parallel
Honeywell-compatible ID/loop entry format** alongside the native Caddx
serial number - meaning wireless transmitter identity can be entered in
either vendor's format for cross-compatible sensors. **Programming-only.**

**`GetNewWirelessExp.cs`** — "New Wireless Expander" creation wizard: pick
a starting zone block (17, 33, 49, ... in 16-zone blocks) and capacity
(8/16/48 zones). Enforces **only one wireless expander per system** - a
hard limit worth preserving in a replacement. One-time setup only.

**`X10_Import.cs`** — bulk lighting-device import, broader than the
changelog's "Lutron and C-Bus" hint: **Lutron XML, Universal Devices ISY
export (Insteon), UpStart UPB export (*.upe), and C-Bus Toolkit XML**, each
with keep/clear policy for name, Opt flag, Show flag, and voice
description, plus a replace-by-address vs. clear-all-first merge policy.
One-time setup only.

**`X10_Import_CBusNetNames.cs`** — companion picker for C-Bus imports (a
project can contain multiple networks; user picks one per import run).

**`X10_Outputs.cs`** — the main lighting/output programming grid (up to
256 devices, X10 house/unit addressing "1 (A1)" through 256). Confirms the
"PLC/output" table is **not X10-only**: a UI label explicitly lists **UPB,
ALC, CentraLite, EDT, Z-Wave, and Insteon** as protocols bridged through
this same table via a "Serial Expander" format option, alongside Standard/
Extended/Preset Dim/Compose. Each device gets a 6-word voice slot (shared
layout with Voice_Messages.cs). A "Two-Way" flag on some devices implies
on/off status readback for certain device types - **worth checking against
panel docs for potential runtime relevance**, though this file itself only
edits programming data.

**`Voice_Messages.cs`** — assigns up to 6 vocabulary words (packed as 6
high/low byte pairs referencing `WordLists` indices) to zones/outputs/
tasks/X10 devices, each auto-named e.g. `"Zone 5 (vm5)"`. Has a **local
"Say" preview** (PC-side, via the `ElkWords.VoiceWords` control) distinct
from "Send" (uploads the word-index bytes to the panel) - local audition
and panel programming are separate actions. **Programming-only** for the
Send path.

**Typed DataSets** (`dsWireless1`/`dsWireless2`/`dsLighting`/
`dsVoiceMessages`) confirm the field-level shape already known from the
account DB schema - no new information beyond what §4 already captures.

### 5.5 Network / M1XEP / C1M1 / M1Cloud / diagnostics

Everything here sits **above** what `ha_int_elkm1` does today (TCP/serial
connect with auto-baud, TLS 1.0/1.2/1.3, basic connection validation) - it's
ElkRP acting as the **installer/technician provisioning tool** for hardware
that's not yet configured, not a runtime automation client. Only a few
items (marked below) have plausible ongoing runtime value.

**`XEPConfig.cs`** (~21,000 lines, the M1XEP Setup dialog) has **9 tabs**:
TCP/IP (static/DHCP, ports, DNS, AMXB beacon, network-discovery "Find"),
**Passwords** (up to 8 username/password pairs with a live strength meter),
**Email/SMTP relay** (server/auth/POP-before-SMTP, plus a per-rule
recipient/message grid), **Central Station** (up to 8 independent IP
alarm-monitoring report destinations, each a full `XEPCS` sub-form),
**Dynamic DNS**, **Time Server (SNTP)**, **Audio System** (whole-house
audio/paging matrix - brand/model dropdown, IP/port, TCP/UDP, an 18-zone
and 12-source name grid; a genuinely separate feature domain, third-party
hardware control, not panel automation), and **M1Cloud** (enable +
installer contact + Account ID provisioning). All 9 tabs push/pull as one
block over the same low-level framed message protocol runtime commands use,
with per-section CRC-based dirty tracking. Reboot and Trace buttons have
marginal ongoing-diagnostic value; everything else is one-time/occasional
installer configuration.

**`XEPCS.cs`** — one central-station IP-receiver config (embedded 8× in
XEPConfig): receiver type (**GE OH2000E**, **DSC Sur-Gard**, **DSC Sur-Gard
(MAC)**, each with different required fields), IP/port, account/CID line
numbers, a 32-hex-char encryption key, heartbeat supervision interval,
DNIS. Pure alarm-monitoring-company provisioning - out of scope entirely
for a homeowner automation client.

**`XEPFind.cs`/`C1M1_Config.cs`** — near-identical UDP broadcast discovery
dialogs (`"XEPID"`/`"C1M1"` magic-byte probes to `255.255.255.255:2362`),
parsing MAC/IP/name/port(s) from a fixed-offset raw datagram. Notably,
`XEPFind` can also trigger a **TFTP-based firmware recovery flash**
directly from the discovery screen when a device shows in bootloader mode
(`*NAME*` wrapping). Installer-only, used at first setup or IP recovery.

**M1Cloud relay** (`M1CloudProxy.cs` + the M1Cloud tab) is the single
most significant "beyond automation" finding:
- A **full UDP NAT-traversal relay protocol** to `m1cloud.elkproducts.com:2001`
  - handshake `REQ_NAT`→`ACK_NAT` (server hands back both endpoints' public/
  private IP:port plus a session nonce) → the client races a hello to both
  endpoints to punch through NAT → `SrvrHello`/`ClntWelcm`/`SrvrWelcm`
  completes the session. Ongoing traffic wraps the same DLE/STX-framed M1
  bytes + CRC16 inside an `"{accountID}//0//ClientMsg/{nonce}/"` envelope
  over UDP. **This is a real, additional connection method** our
  integration doesn't support (we assume direct IP/serial reachability) -
  genuinely useful if remote access without port-forwarding matters to a
  replacement, but it's a nontrivial state machine to reimplement, not just
  "TLS to a different host."
- **Account provisioning** calls a live SOAP web service
  (`M1AccountsSoapClient.CreateAccountExt`/`DisableAccount`) using
  **hardcoded service credentials found directly in the decompiled source**
  (`OrganizationID`, a fixed `Username`, a fixed `Password`) - a shared
  secret baked into every shipped copy of ElkRP, the same category as the
  Jet-DB connection credential found earlier (not a personal/live security
  secret, but a real security smell worth flagging: **don't replicate this
  pattern** - a modern replacement would need its own, non-shared
  provisioning auth).

**Connection transports beyond HA's TLS/serial** (§7 of the agent's
report):
- **`TLS.cs`** - functionally like our TLS support, but adds a **fallback
  ladder** (retries a different TLS version if the preferred one fails,
  persisting the working version) and a second **"ElkLink" mode** - a
  JSON/brace-framed protocol (distinct from the DLE/STX binary M1 protocol)
  for cloud-hosted dealer remote access, with **certificate pinning**
  against a hardcoded Elk-issued cert DN in addition to normal chain
  validation.
- **`NetAES.cs`** - a legacy pre-TLS AES-encrypted transport for older
  M1XEP/C1M1 firmware and specifically C1M1 cellular sessions. Only
  relevant for legacy/cellular deployments.
- **`USBCom.cs`** - direct USB/serial to the panel with **fixed 115200
  baud and no auto-detection** (unlike our baud-sweep approach), wrapping
  each message in a **JSON envelope** (`{"RP":[16,2,...,16,3,crcHi,crcLo]}`)
  written as text rather than raw bytes - a materially different serial
  encoding than our raw-byte approach.
- **`FTP.cs`** - a minimal hand-rolled passive-mode FTP client used only to
  push firmware files to the M1XEP during updates. No automation relevance.

**`PgmFlash.cs`** (~7,250 lines) — firmware/bootloader update wizard
covering both the panel and the M1XEP, hardware/bootloader-version-gated
combo boxes (refuses incompatible firmware for the detected hardware
revision), separate Firmware vs. Bootloader flows, panel programming over
the direct link vs. XEP updates via FTP/TFTP. A legitimate but rare,
high-risk (bricking on interruption) maintenance feature - worth scoping
as its own isolated module in a replacement, exactly as ElkRP does, not
folded into day-to-day automation.

**Diagnostics**: `XEPTrace.cs` (a live UDP debug-log console streaming
internal M1XEP subsystem logs, technician-facing), `XEPTestDNS.cs`
(one-shot DNS resolution test via the XEP itself, with per-error-code
guidance), `TLSLineMonitor.cs` (a reusable hex/string packet-sniffer
window shared by TLS/AES/M1Cloud/USB/Trace, redacting passwords in
ElkLink traffic). **`ReceiveLog.cs`** — a panel-history/event-log viewer
(receive-all, receive-next-20, save/print/clear) - **the one item in this
whole batch with plausible ongoing end-user automation value**: our
integration doesn't currently expose panel history/log retrieval as a
feature (only the raw `LD` decode primitive), and this confirms it's a
real, user-facing capability worth having.

**Data model** (`dsM1XEPSetup1`/`dsM1XEPSetup2`) confirms the scope:
network/DHCP/DNS/routing, 8 credential pairs, SMTP relay admin, DDNS client
config, NTP client config, and 8-way central-station integration, all in
one device's provisioning record - genuinely an order of magnitude richer
than "connect and poll a panel."

## 6. Full comparison against `ha_int_elkm1`

### 6.1 What `ha_int_elkm1` already covers well

Everything ElkRP's `RemoteControl.cs` (the live "Control Status" screen)
and the panel's runtime broadcasts expose - arm/disarm, zone/output/task/
light/thermostat/counter/custom-value status and control, keypad status,
trouble conditions, system log entries, text descriptions, voice output -
our integration implements via the documented ASCII protocol, verified
this session against real hardware and now with 99% test coverage on the
protocol layer. Connection-wise, we cover direct serial (with auto-baud
sweep, which ElkRP's own `USBCom.cs` notably lacks), plain and secure
(TLS 1.0/1.2/1.3) network to the M1XEP - the practical subset for a
locally-reachable panel.

### 6.2 Confirmed out of scope (full EEPROM programming)

Everything in §5.2 (panel-programming screens), §5.3 (rules engine), most
of §5.4 (wireless/X10/voice programming), and the provisioning parts of
§5.5 (M1XEP network/password/email/DDNS/NTP/central-station/audio setup,
firmware flashing, cellular/cloud account provisioning) all ride on the
**separate, undocumented binary EEPROM protocol** (§1), not the ASCII
protocol. Reimplementing any of this means reverse-engineering
`M1CtlHdr.cs`'s struct layouts and the corresponding Form_Send/Form_Receive
logic from scratch, with real risk of corrupting panel configuration on a
wrong byte offset. **This should stay out of `ha_int_elkm1`** - a Home
Assistant integration operates a configured system, it doesn't reprogram
one. It's squarely in scope for the replacement-app project instead (see
§7).

### 6.3 Concrete, low-risk gaps in `ha_int_elkm1` worth closing

Ranked by value-to-effort:

1. **`vocabulary.py` correctness** (already found, deferred per your
   instruction) - the "say toggle" phrase IDs are wrong sign/value. Fix
   data is ready in `_extracted/WordLists_M1G.csv`.
2. **Event-ID descriptions for the `LD` log message** - `ld_decode`
   currently returns a bare `event` integer with zero semantic meaning.
   `_extracted/EventLists_M1G_5.3.0.csv` (1358 rows) is the authoritative
   mapping, ready to use.
3. **Panel history/log retrieval as a first-class feature**
   (`ReceiveLog.cs`, §5.5) - we have the `ld`/`LD` decode primitive but no
   "browse the panel's event history" feature built on top of it. Combined
   with #2 above, this could become a genuinely useful Log/History
   sensor or service, something ElkRP treats as a core feature, not
   installer tooling.
4. **Connection keepalive/idle-disconnect pattern** (`MiscStuff.cs`/
   `DisconnectWarning.cs`, §5.1) - ElkRP sends an explicit keepalive every
   15 seconds while connected, plus a configurable idle-disconnect timer.
   Our heartbeat-timeout logic in `helpers/transport.py` is a related but
   different mechanism (we detect a *dead* connection via inbound traffic
   timeout; ElkRP proactively keeps the session alive). Worth a closer
   look at whether the panel's own connection-supervision expects periodic
   client-side traffic beyond what our poll/push cadence already provides -
   if it does, this could explain any as-yet-unexplained reconnects.

### 6.4 Real capabilities ElkRP has that `ha_int_elkm1` deliberately doesn't need

These aren't "gaps" - they're different tools for different jobs, listed
here so the distinction is explicit rather than assumed:

- **M1Cloud relay connectivity** (§5.5) - a genuine alternate connection
  method (UDP NAT-traversal relay) for panels behind NAT without port
  forwarding. Not needed for a locally-networked HA setup, but worth
  knowing it exists if a user ever asks "can I connect without opening a
  port."
- **ElkLink cellular/ethernet proxy** (§5.1) - same category, via the C1M1
  module.
- **Whole-house audio/paging integration** (§5.5 Audio tab) - controls
  third-party audio hardware (Russound/NuVo/Proficient), not the panel
  itself; the `ca`/`cd` ASCII commands are already correctly marked
  "intentionally unsupported" in `docs/protocol_coverage.md` for this
  exact reason.
- **Central-station (Contact-ID/SIA/Sur-Gard) reporting configuration** -
  purely alarm-monitoring-company provisioning, never relevant to a
  homeowner automation client.
- **Firmware/bootloader updates** - high-risk, rare, and architecturally
  distinct; ElkRP itself keeps this as a separate wizard, not part of
  day-to-day control.

## 7. Notes for the future replacement application

Since you mentioned wanting to eventually replace ElkRP itself (its
.NET Framework/VB6-COM-interop runtime targets Windows XP/Vista, and
`ElkComm2.dll`'s native COM component is a real long-term liability), a few
observations from this catalog that would shape that project - **distinct
from and much larger in scope than `ha_int_elkm1`**:

- **It needs the binary programming protocol**, which is genuinely
  undocumented publicly. The only source of truth is `M1CtlHdr.cs`'s
  struct layouts plus each form's Form_Send/Form_Receive logic - a real
  reverse-engineering project, not a decode-and-port exercise like this
  session's ASCII protocol work. Budget for it accordingly; a wrong struct
  offset can corrupt a real panel's configuration, so it needs the same
  "verify against real hardware, cross-check against a second source"
  discipline this session applied to the ASCII protocol, just at
  materially higher stakes.
- **Zone_Definitions.cs's `ZnFlag1Bits`/`ZnFlag2Bits` bit layout** (§5.2)
  is the most immediately reusable low-level artifact found - it's the
  exact bit-level meaning of zone configuration flags, something that
  would otherwise require its own reverse-engineering pass.
- **The WhenThen rules engine's full WHENEVER/AND/THEN vocabulary** (§5.3)
  is fully cataloged and could be a genuinely compelling feature to
  support programming, since it's a real capability of the hardware with
  no other modern client.
- **Architecture decision to make early**: ElkRP keeps a full local
  database shadow-copy of panel programming with manual conflict
  detection/resolution (§5.1, `Conflicts.cs`). A modern replacement could
  choose differently (always read-through to the panel, or a
  git-like versioned local store with proper 3-way merge) - worth deciding
  deliberately rather than inheriting the old design by default.
- **Security notes worth NOT replicating**: the hardcoded shared
  `ElkRP`/`hA93olXMefi3c5` database-open credential, and the hardcoded
  M1Cloud SOAP provisioning credentials found in the decompiled source.
  Both are "secrets" baked into every shipped copy of the app - fine for
  gating a legacy Jet database against casual tools, not an acceptable
  pattern for anything a replacement app provisions against a live
  service.
- **Firmware/bootloader update and central-station reporting config**
  should probably be separate, clearly-labeled modules (as ElkRP itself
  treats them) given their risk profile and narrow audience (installers/
  dealers, not homeowners), rather than folded into a general control UI.
- **Scope call to make explicitly**: does the replacement target
  homeowners (day-to-day control + light programming, closer to what
  `ha_int_elkm1` already does well) or installers/dealers (full
  programming parity with ElkRP, central-station config, firmware
  updates)? The two audiences want very different feature surfaces and
  risk tolerances, and ElkRP itself is built for the latter. Worth an
  explicit decision before scoping further, rather than assuming "replace
  ElkRP" means full parity with all ~85 files cataloged here.

## 8. Artifacts

The decompiled tree and the data extracted from it are **not retained** and
are deliberately not committed here: they are decompiler output and data
files belonging to a proprietary vendor application. Everything below is
re-derivable from an ElkRP 2.0.41 install if it is ever needed again.

- Full decompiled C# source for every managed assembly.
- `WordLists_M1G.csv` - voice vocabulary (478 rows).
- `EventLists_M1G_5.3.0.csv` - log event-ID catalog (1358 rows), filtered
  from a larger `EventLists.csv`.
- `ElkAccts2_schema.txt` - column schema for every table in the example
  accounts database.
- `ElkComm2_strings.txt` - extracted strings from the one native DLL.
