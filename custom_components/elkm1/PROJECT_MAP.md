# Project Map: Elk-M1 Integration

Structural map of this integration for contributors - file organization, the connection
architecture, and protocol/library quirks worth knowing before changing coordinator or
entity code.

## 1. Connection architecture

`elkm1-lib` (pinned in `manifest.json`) owns the Elk-M1 ASCII protocol: message
encode/decode (`message.py`), checksum/framing, and the `Elk` class's typed subsystem
objects (`Area`, `Zone`, `Output`, `Task`, `Thermostat`, `Light`, `Counter`, `Setting`,
`Keypad`, `Panel`) with their own command helpers (`Area.arm()`, `Zone.bypass()`,
`Output.turn_on()`, etc.). This integration reuses all of that rather than
reimplementing the protocol.

The one thing replaced is each entry's bound
`elkm1_lib.connection.Connection.connect()` method. `helpers/transport.py` installs the
replacement on that connection instance only; it never changes the process-global
class. The entry-owned manager supervises open, streams, bounded reconnect backoff,
cancellation, and awaited close while adding host-side baud-rate auto-detection
(`helpers/baud_probe.py`: sweep the standard rates, confirm with a real `vn`
version-request round-trip, cache the winning rate on the config entry). Network
connections are unaffected - TCP has no baud rate to detect.

`coordinator.py`'s `ElkDataUpdateCoordinator` owns the one `Elk` instance per config
entry. Its `_async_setup()` waits for the panel's own `"login"` notifier event (not
`"connected"`, which only means the socket/serial link opened - for secure network
schemes, credentials are sent *after* `"connected"` fires, and only the panel's actual
reply proves them accepted or rejected) before considering setup complete, raising
`ConfigEntryAuthFailed` on a rejected login so Home Assistant's reauth flow triggers
correctly.

## 2. File manifest

### Core
* `__init__.py` - config entry lifecycle: builds the connection URL, constructs the
  coordinator, runs `verify_panel_configuration` as a background diagnostic task,
  forwards platform setup, and registers the options-reload listener.
* `config_flow.py` - connection-method/network/manual-network/serial config steps, DHCP
  and upstream ELK network discovery,
  and the options/reconfigure/reauth flows.
* `coordinator.py` - connection setup, push-callback registration per message type,
  the normalized `ElkPanelData` snapshot builder, and command methods (arm/disarm,
  bypass, display_message, speak_word/phrase, set_time) that entities/services call
  into rather than talking to `elkm1_lib` objects directly.
* `const.py` - domain constants, config keys, and `ELK_ELEMENTS` (the M1 Gold's
  hardware-maximum element counts, since `elkm1_lib` always allocates that many
  `Zone`/`Output`/etc. objects regardless of what's actually configured on the panel -
  every platform's `async_setup_entry` filters on `.configured` before creating
  entities).
* `models.py` - `ElkPanelData` (the coordinator's typed snapshot; `zones`/`outputs`/
  `tasks`/`thermostats`/`panel` are references to `elkm1_lib`'s own live objects, not a
  second parallel copy) and `ElkRuntimeData` (`entry.runtime_data`).
* `entity.py` - `ElkEntity` base class (`CoordinatorEntity` + `_attr_has_entity_name`),
  the shared device-info factory, and `async_add_dynamic_entities()` (see the
  name-sync timing note in section 3 - every platform that filters on `.configured`
  uses this instead of a single one-shot `async_add_entities` pass).

### Helpers (`helpers/`)
* `transport.py` - the entry-owned connection manager, plus `validate_serial_port()`/
  `validate_network_connection()` used by the config flow to verify a connection before
  creating an entry.
* `baud_probe.py` - the baud-rate sweep itself.
* Linux persistent-path normalization lives in `config_flow.py` and prefers `by-id`,
  then `by-path`. Generic USB bridge VID/PID discovery is intentionally absent because
  it cannot identify an adapter as an ELK product.
* `panel_settings.py` - `verify_panel_configuration()`: since the protocol has no way
  to read back Global Programming's "Xmit ... Changes" broadcast-enable bits, this
  empirically infers whether they're on by watching for broadcasts after connecting,
  and logs a warning (not yet a Repair issue - see `quality_scale.yaml`'s
  `repair-issues` entry) if they appear to be off.
* `troublestatus.py` - parses the `SS` trouble-status bitfield into named booleans.

### Platforms
One file per Home Assistant platform (`alarm_control_panel.py`, `binary_sensor.py`,
`sensor.py`, `switch.py`, `climate.py`, `light.py`, `number.py`, `time.py`,
`scene.py`), each with its own `async_setup_entry()` that filters `coordinator.data`'s
element lists on `.configured` (and, for counters/custom values, a real panel-assigned
name) before creating entities, and registers any entity services that platform owns.

### Cross-integration
* `alarmo_integration.py` - the `elkm1.alarmo_auto_setup` service.
* `docs/cross_integration.md` - the honest breakdown of what's real integration code
  vs. blueprint-only support, per product.
* `blueprints/automation/` - ready-made automations, including
  `pause_climate_on_opening.yaml` (the primary Better Thermostat integration path -
  see the doc above).

### Services & diagnostics
* `services.py` - domain-level services (`speak_word`, `speak_phrase`, `set_time`,
  `display_message`, `get_security_summary`), routed to a coordinator by an optional
  `prefix` field for multi-panel setups.
* `device_action.py` - device-level automation actions (speak_phrase, display_message)
  for the automation editor UI.
* `diagnostics.py` - redacted config entry + panel state export.
* `vocabulary.py` - Elk voice vocabulary ID -> word/phrase text.

## 3. Protocol & library notes worth knowing

**`.configured` depends on a slow, sequential per-index name sync - never gate entity
creation on it with a single one-shot pass.** `elkm1_lib`'s `Elements._sd_handler` only
sets an element's `._configured = True` once the panel's reply to an `SD` (text
description) request for that specific index has arrived, and the request loop asks for
index N+1 only after receiving the reply for index N - a fully sequential exchange
(208 round-trips for zones alone) that routinely outlasts `coordinator._async_setup()`,
which only waits for the panel's `"login"` reply, not for this per-index name sync to
finish. A platform that creates entities once, synchronously, in its `async_setup_entry`
(the original bug this was found from: zero zone `binary_sensor` entities ever appeared,
because none of them were `.configured` yet at that single pass) will silently drop
every element whose name hadn't synced yet - `async_setup_entry` never runs again, so
they're gone for good until a manual reload. Every platform that filters on
`.configured` uses `entity.async_add_dynamic_entities()` instead: it does the initial
pass, then keeps listening (`coordinator.async_add_listener`, woken by the coordinator's
`"SD"` handler on every description reply) and adds entities for elements as they
individually become configured.

**Enum/string/int casting.** `elkm1_lib` fields like `logical_status`/`definition`/
`alarm_state` are typed enums, but code that reads them needs a raw int to compare
against protocol values - `bool(SomeEnum.MEMBER)` is always `True` regardless of the
member's value, so truthiness checks on the enum itself are a bug magnet. Every
platform has its own small `_get_enum_value()`/`_enum_value()` helper
(`obj.value if hasattr(obj, "value") else obj`, coerced to `int`) for this; there's no
shared one because the platforms predate a shared `helpers/` module for it, not because
the duplication is intentional.

**`ZoneLogicalStatus` only has 4 members**: `0=NORMAL, 1=TROUBLE, 2=VIOLATED,
3=BYPASSED`. There's no separate "violated-and-bypassed" value - bypass is its own
status, not a flag layered on top of violated.

**Zone definitions encode arming response, not physical sensor type.** The `ZoneType`
enum (`BURGLAR_ENTRY_EXIT_1/2`, `BURGLAR_PERIMETER_INSTANT`, `BURGLAR_INTERIOR*`, etc.)
is how the panel treats a zone violation (entry/exit delay, no delay, interior-only),
not what kind of sensor is wired to it - the protocol has no separate physical-type
field. `binary_sensor.py`'s `_DEVICE_CLASS_MAP` maps these to Home Assistant device
classes on a best-effort, installer-convention basis (entry/exit -> door,
perimeter-instant -> the generic `opening` class rather than claiming `window`
specifically) - see the comment above that map for the reasoning.

**All-zone and per-zone bypass are toggles, not set/clear pairs.** The `zb` command
(and `Area.bypass()`'s zone-999 variant for "all zones in an area") flips bypass state;
there's no separate "clear bypass" command. `coordinator.unbypass_zone()` and
`ElkAlarmControlPanel.async_alarm_clear_bypass()` both just re-send the same bypass
call.

**The panel has no onboard temperature sensor.** `Panel.temperature` isn't a thing -
keypad temperature probes (`Keypad.temperature`, once enrolled) are the only
panel-adjacent temperature source; zone temperature comes from zones defined as
`TEMPERATURE` type.

**PIN codes arrive as strings from Home Assistant's UI/service calls** but
`elkm1_lib`'s command helpers want an `int`. Every entity command method converts (and
warns, rather than crashing, on a non-numeric PIN) before calling into the coordinator.

**Command methods write, they don't return command success/failure over the wire** -
the protocol is fire-and-forget for commands; success is only observable via the
resulting state broadcast. Coordinator command methods return `True`/raise on local
failure (no connection, etc.), not panel-side confirmation.
