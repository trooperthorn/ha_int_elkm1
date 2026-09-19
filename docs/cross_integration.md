# Cross-integration support

This integration's cross-integration support is deliberately tiered, based on
whether the other product actually exchanges data with the Elk-M1 panel or
simply lives alongside it in Home Assistant:

- **Code-level integration** (Alarmo, Better Thermostat): this repository
  ships Python code and/or entities specifically built to talk to that
  product.
- **Automation-layer support** (Davis Weather, Unifi Protect, Browser Mod,
  ESP32 Bluetooth Proxy): there is no direct data link between the Elk panel
  and these products, so support means standards-compliant entities (correct
  `device_class`, stable `unique_id`s, sensible naming) plus ready-made
  [Blueprints](../blueprints/automation/) that wire the two together in an
  automation - not new integration code.

## Alarmo (code-level)

Two independent, non-overlapping patterns are supported. Pick one per area;
Alarmo's own arm/disarm decisions and a state mirror pushing a different
history at the same entity are not reconciled against each other.

### Pattern 1: Alarmo as its own alarm brain (zone sensors only)

`alarmo_integration.py` registers `elkm1.alarmo_auto_setup`, a service that
scans the entity registry for this integration's zone `binary_sensor`
entities and posts a persistent notification listing them, so you can add
them to Alarmo's **Sensors** tab in a couple of clicks instead of hunting
through the entity list by hand. `blueprints/automation/auto_setup_alarmo.yaml`
runs it automatically on Home Assistant startup once the Elk panel is online.

Alarmo discovers `binary_sensor` entities on its own; this integration's job
is only to make its zones easy to find, not to duplicate Alarmo's arming
logic. Zone `device_class` is derived from the panel's zone-definition field
best-effort - see the comment above `_DEVICE_CLASS_MAP` in `binary_sensor.py`
for what the protocol does and doesn't tell us about physical sensor type.
In this pattern Alarmo is the source of truth for arm state; it never asks
the physical ELK panel what it thinks its own state is.

### Pattern 2: mirror the physical panel's state into Alarmo

`blueprints/automation/alarmo_state_sync.yaml` keeps Alarmo in step with the
ELK panel instead: it triggers on this integration's `alarm_control_panel`
entity changing to any stable state (`disarmed`, the five armed variants, or
`triggered`) and immediately calls the matching Alarmo service
(`alarmo.arm`/`alarmo.disarm`, or the standard `alarm_control_panel.alarm_trigger`
for `triggered`, since Alarmo has no dedicated external-trigger service).
There is no artificial delay in the automation itself; propagation time is
whatever the panel's own push (`AS`/`EE` broadcast to coordinator to entity
state) and Home Assistant's event bus take. The blueprint's own header
documents why it sends `skip_delay: true` and `force: true` on the Alarmo
side - ELK-M1's exit/entry delay has already run in hardware by the time the
panel reports a stable armed state, and the panel's own decision to arm
should not be second-guessed by Alarmo's independent sensor view once it is
being used purely as a mirror. This direction is one-way (ELK-M1 -> Alarmo);
it does not let Alarmo command the physical panel.

Whichever pattern is used, `alarm_control_panel.py`'s `changed_by` property
and its `last_user`/`last_user_name`/`last_keypad`/`last_user_time` state
attributes are sourced from the panel's own `IC` (user code) report -
`elk.users.username()`, which the library already syncs from the panel's
programmed user names via `sd`/`TextDescriptions.USER` - so an automation or
dashboard reacting to an Elk-M1 arm/disarm event can show who did it, not
just that it happened. `last_user_name` falls back to `User <n>` if that
user number has no name programmed on the panel, and to `Unknown` before any
`IC` message has been seen this session.

### Dashboard: collapsing the code entry (automation-layer)

Neither this integration nor Alarmo controls how a Lovelace card asks for the
code; that is a card-level setting. The core `alarm-panel` card always renders
the keypad. Niels Faber's `alarmo-card` (the Alarmo author's own card,
installed through HACS) does not:

```yaml
type: custom:alarmo-card
entity: alarm_control_panel.alarmo
keep_keypad_visible: false
```

`keep_keypad_visible` defaults to `false`, which is already the behaviour of
"show the arm buttons, and only expand the code entry once an arm mode is
selected". Set it explicitly so a later card edit does not silently change it.
`use_code_dialog: true` is the alternative presentation - the same code entry
as a modal popup rather than an inline expansion - and cannot be combined with
`keep_keypad_visible`, `hide_keypad`, or `button_scale_keypad`.

#### Why there is no biometric option here

Replacing the code with a phone fingerprint or face unlock is not offered by
this integration, and the reason is worth recording so it is not re-proposed:

* A biometric check performed in the card is not a security control. The card
  runs in the browser; `alarm_control_panel.alarm_disarm` remains callable
  directly over the authenticated websocket API, so the gate is friction, not
  a boundary. A real control needs the credential verified server-side, with
  the Elk user code held there and never sent to the frontend.
* WebAuthn platform authenticators are not dependable in the Home Assistant
  companion app, which is where a phone fingerprint would be used. Android's
  WebView does not expose Credential Manager to page script, and iOS WKWebView
  needs associated-domain wiring the companion app does not perform. It works
  in a plain browser, which is not the target.
* The supported per-action biometric path on iOS is an actionable notification
  carrying `authenticationRequired`, which forces device authentication before
  the action runs and reports back through the `mobile_app_notification_action`
  event. It is iOS-only; the Android companion app has no equivalent per-action
  flag. Verify the key against the current companion documentation before
  building on it.
* The zero-code approximation is the companion app's own biometric App Lock
  combined with Alarmo's `code_arm_required` / `code_disarm_required` set to
  `false`. This authenticates at app open rather than per arm or disarm, which
  is a coarser guarantee, and should be treated as convenience rather than as
  the panel's access control - the ELK panel's own user codes remain the
  authority over the hardware.

## Better Thermostat (code-level)

Two separate paths, because the more broadly useful one doesn't require the
Elk panel to have any Elk-connected thermostats - most installations don't.

### Primary: per-area door/window aggregate sensor

`binary_sensor.py` creates one `binary_sensor.elk_m1_area_N_openings` entity
per configured area (`device_class: opening`), which is on when any
door/window zone assigned to that area is violated. This is Elk's real value
for climate control: its door/window contact zones, not its thermostats.

Feed this sensor into Better Thermostat's own window-sensor setting (Better
Thermostat restores the exact prior mode/temperature automatically when the
window closes), or use
`blueprints/automation/pause_climate_on_opening.yaml` for any other climate
integration that lacks native window-sensor support - it works with any
`climate.*` entity, not just an Elk-connected one.

Door/window classification is best-effort: the Elk protocol's zone
"definition" field encodes the panel's *arming response* for a zone (entry/
exit delay, perimeter-instant, interior, etc.), not its physical sensor type.
Entry/exit zones are assumed to be doors and perimeter-instant zones are
exposed as the generic `opening` class rather than `window` specifically,
since the protocol has no way to confirm either.

### Secondary: wrapping an Elk-connected thermostat directly

If the panel does have Elk-connected thermostats, `climate.py`'s
`ElkThermostat` entity is a standards-compliant `climate.ClimateEntity`
(correct `hvac_modes`, `hvac_action`, `supported_features`) that Better
Thermostat - or any other climate-wrapping integration - can use as its
underlying entity like any other thermostat. Pair it with the per-zone
temperature-probe `sensor` entities as Better Thermostat's external
temperature sensor input.

## Davis Weather, Unifi Protect, Browser Mod, ESP32 Bluetooth Proxy (automation-layer)

None of these exchange data with the Elk panel directly, so there is no
integration code for them here - only Blueprints that combine their
entities with this integration's:

- `blueprints/automation/elk_davis_atmospheric_pre_arm.yaml` - checks Davis
  Weather conditions (rain, wind) before allowing an Elk area to arm.
- `blueprints/automation/unifi_protect_example.yaml` - snapshots/records a
  Unifi Protect camera in response to an Elk zone fault.
- `blueprints/automation/kiosk_security_popup.yaml` - pops up a Browser Mod
  kiosk alert on an Elk security event.
- ESP32 Bluetooth Proxy has no dedicated blueprint yet; it's a `bluetooth`
  platform, not an entity domain, so it participates through whatever
  `device_tracker`/presence entities it feeds - see
  `blueprints/automation/presence_arming.yaml` for a presence-driven
  arm/disarm example that works with any presence source, BLE-proxy-derived
  or not.

These blueprints use area-based entity matching where practical (matching an
Elk zone's area to a camera or notification target in the same area) rather
than hardcoding entity IDs, so they adapt to your own naming instead of
requiring edits before use.
