# Design

Architecture and rationale for the Elk-M1 integration. `custom_components/elkm1/PROJECT_MAP.md`
is the structural map (which file owns what, and the library quirks that shape the
coordinator); this document carries the reasoning behind choices that the map only names.
Wire and device facts live in `protocol.md`; configuration and release operations in
`operations.md`; dated decisions with their rejected alternatives in `decisions.md`.

## Connection and coordinator

The coordinator is `local_push`. Once the panel's Global Programming "Xmit ... Changes"
settings are enabled it broadcasts state changes on its own; `helpers/elk/` (this
integration's own protocol implementation - see `docs/decisions.md` 2026-09-05) decodes
those into its typed Zone, Area, Output, and Task objects, the coordinator observes them
through per-element callbacks, and pushes the snapshot onward with
`async_set_updated_data()`. The
polling `update_interval` is a bounded AS/AZ/CS/SS/LW safety net, not the primary data path.

Setup waits for the panel's `login` notifier event rather than `connected`. `connected`
only means the socket or serial link opened; for the secure network schemes the credentials
are sent after that, and only the M1XEP's reply proves them accepted or rejected. The
schemes with no authentication fire the same `login` event when the first `vn` sync reply
arrives, so waiting on `login` uniformly proves the panel is answering and lets a rejected
login raise `ConfigEntryAuthFailed` instead of a generic timeout.

The first-setup timeout is a ceiling on how long setup waits before surfacing
`ConfigEntryNotReady`, sized for a full nine-rate baud sweep plus a couple of backoff
cycles. It is not a retry count; the transport retries indefinitely on its own.

The config flow builds a fully scheme-prefixed URL (`elk://`, `elks://`, `elksv1_2://`,
`serial://`), and the coordinator uses it as-is. Re-wrapping it in another scheme was the
cause of one earlier connection bug.

`helpers/elk/elements.py`'s `Elements` allocates the hardware-maximum number of every
element (eight areas, 208 zones, and so on - `helpers/elk/const.py`'s `Max`). Only elements
that have received real sync data are treated as configured, so entity counts reflect the
panel rather than that ceiling. Names arrive one index at
a time through sequential `SD` replies that routinely outlast setup, so every platform adds
entities through `entity.async_add_dynamic_entities()`, which keeps listening for later
`SD` replies instead of creating entities in a single pass at platform setup. The test
`tests/test_binary_sensor.py::test_zone_binary_sensor_appears_once_configured_after_setup`
is the regression test for the bug that motivated this: zero zone sensors ever appeared.

Zone voltage is only requested for zones the panel defines as analog (definition 34),
because `Zones.sync()` never sends `zv` and asking all 208 slots would be wasteful.

The trouble-status handler is registered alongside `helpers/elk/panel.py`'s own
`Panel._ss_handler` (the notifier supports several handlers per message type) so the
coordinator receives the raw per-condition string. The `Panel` object only exposes a
pre-joined display string, which loses which individual conditions are active;
`helpers/troublestatus.py` parses the raw string into one boolean per condition using the
same index mapping `Panel._ss_handler` uses internally.

`ElkPanelData` keeps references to `helpers/elk/`'s own live element objects rather than a
second parallel set of dataclasses, because those objects are the source of truth. Only
panel-wide aggregates (areas, faulted and active summaries, connection-derived fields) are
promoted to typed fields, replacing an earlier untyped dictionary with string keys.

## Transport

`helpers/transport.py` owns the connect/reconnect/read-loop supervision against
`helpers/elk/connection.py`'s own `Connection` class - no monkey-patching of any kind, since
this repository owns `Connection` directly (see `docs/decisions.md` 2026-09-05; this split
predates that removal and is kept deliberately). The manager supervises open, streams,
bounded reconnect backoff, cancellation, and awaited close, and adds host-side baud-rate
detection for serial links. Network links have no baud rate to detect.

Baud detection reuses `helpers/elk/message.py`'s `vn_encode()` and `decode()` so the
checksum and framing logic stays identical to the one place this repository implements it.
A winning probe hands its open reader and writer back to the caller instead of closing and
reopening the port; the second open wastes a round trip and, on some USB-serial adapters,
trips DTR-reset or settling quirks. Reconnects try the cached rate first so they lock on
immediately. `probe_baud` is the validation-only variant for the config flow and USB
discovery, which need a yes or no and do not keep the connection.

The network heartbeat window is scaled with the configured poll interval; the reasoning
and the numbers are in `protocol.md`.

`cw_encode`/`rw_encode`/`tr_encode`/`ts_encode` in `helpers/elk/message.py` declare their
real reply codes directly (fixed relative to the removed `elkm1-lib` 2.2.15 dependency,
whose equivalents omitted them from their encoder metadata - see `docs/decisions.md`
2026-09-05); the `RESPONSE_COMMAND_OVERRIDES` table that used to patch this at the
transport layer is retired. Supplemental keypad (`KC`) data (`kc_detail_decode`) is
published before the plain `KC` event so the Home Assistant key event carries the complete
keypad state, and correlation happens only after a frame passes length, checksum, and
decode.

## Panel settings verification

The protocol cannot read back the Global Programming "Xmit ... Changes" bits, so
`helpers/panel_settings.py` infers them from whether each gated broadcast type has been
seen since connecting. "Confirmed active" means seen at least once; "unconfirmed" is not
"confirmed disabled", because nothing of that type may have changed yet. Verification runs
as a background task, not awaited by entry setup, because it sleeps a few seconds to let
broadcasts arrive and is purely diagnostic. The version check polls briefly because
`Panel.sync()` already sent `vn` and the asynchronous reply may not have landed yet.

## Entities

Every entity shares one panel-wide device for now (see `backlog.md`). The device's
`sw_version` is the panel firmware from the `vn` reply once known; entities created before
the first sync omit it.

Every alarm panel command goes through a wrapper that raises `HomeAssistantError` on
failure. Without it a failed command was only logged and the service-call or automation
trace reported success even though the panel never received or rejected the command. The
number of area entities comes from the coordinator's parsed data, defaulting to one.

Zone definitions encode the panel's arming response, not the physical sensor type, so the
binary-sensor device-class map is installer convention: entry/exit definitions become
`door`; perimeter-instant becomes the generic `opening` class rather than `window`, because
the protocol cannot distinguish a window from a non-entry door. The per-area "any door or
window open" sensor is the primary, hardware-independent integration point for Better
Thermostat or any climate integration's open-window pause; it needs only contact zones, one
entity per area so a multi-area panel can pause HVAC in one area without another's doors
interfering. `docs/cross_integration.md` has the full picture. Definitions 33 and 34 are
sensors, not binary sensors.

Thermostats expose emergency heat as a separate switch rather than an hvac mode, avoiding
two competing controls for one setting. Elk's AUTO switches between heat and cool
setpoints, which is Home Assistant's `HEAT_COOL`, not its own system-decides `AUTO`. The
setpoint limits are generic HVAC defaults because the manual documents no panel-enforced
range.

Outputs 65 through 208 are reported and controllable but almost never physically present;
like every other element, one only gets an entity once the panel has actually given it a
name, and outputs past 64 are additionally created disabled by default even then, since
that range is rare hardware. Counters and custom values are created only when the panel
has given them a real name; unnamed slots wait for an options-flow opt-in. Tasks are
momentary activations of a pre-programmed sequence with no queryable state, which matches
scene semantics. `zb` toggles bypass and has no separate clear command; the alarm panel's
`async_alarm_clear_bypass` and the `elkm1.sensor_zone_bypass` service both just re-send the
same call for that reason. Zone bypass is deliberately not a switch: a switch entity has no
way to require a code before acting, so exposing bypass that way would let anyone with
dashboard or automation access silently bypass a zone using the panel's stored PIN with no
confirmation at all - a materially weaker boundary than the alarm panel card, which can at
least prompt a human for a code. `ElkZoneBypassBinarySensor` shows bypass status read-only;
actually bypassing or clearing a zone's bypass requires the code-required
`elkm1.sensor_zone_bypass` service. See `docs/decisions.md` 2026-09-05.

Alarmo auto-setup matches zone sensors by the `_zone_` marker in their unique_id, not by
entity_id, because the entity_id comes from the panel's zone name (for example
`binary_sensor.front_door`) and never contains the word "zone". The service is registered
once.

Entity services are registered from `async_setup` through
`service.async_register_platform_entity_service`, so they exist before any platform loads
and do not depend on platform setup order (developer blog 2025-09-25).

`deprecate_entity` looks the existing entity up by unique_id, renames the unique ID only
when the target entity ID is still free, and always returns True so the entity still
registers. `ELKM1Data` remains as an alias of `ElkRuntimeData` until the last importer is
migrated (see `backlog.md`).

## Tests

`tests/test_coordinator.py` runs against real `helpers.elk.Elk` objects wherever practical,
because the bug classes found during development (wrong event name, wrong enum values,
wrong command encoding) only show up against the real implementation.
`test_sd_reply_notifies_coordinator_listeners` covers the listener path that lets dynamic
entity creation work.

## Blueprints

`unifi_protect_example.yaml` groups its inputs as door/window recording, armed-away camera
switching, motion snapshot with notification, and full lockdown. `night_peremeter.yaml`
announces a warning, then the door count and type, then the window count and type, waits
five more seconds, then names each open door and window. `security_summary.yaml` announces
each faulted zone number. `elk_davis_atmospheric_pre_arm.yaml` triggers on the proxy
toggle, evaluates the weather inputs against the safety thresholds, and broadcasts the
warning through the user's TTS integration. `auto_setup_alarmo.yaml` waits until the panel
is fully online before running setup.

## Unverified

- "Rapid close/reopen can trip DTR-reset or settling quirks on some USB-serial adapters"
  (originally a comment in `helpers/baud_probe.py`): stated from field experience, not
  reproduced under test.
