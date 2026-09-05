# Elk-M1 Control for Home Assistant

![GitHub Release](https://img.shields.io/github/v/release/trooperthorn/ha_int_elkm1?style=for-the-badge)
![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home_Assistant-2026.8.3-blue.svg?style=for-the-badge)

A Home Assistant custom integration for **Elk-M1 Gold** and **M1EZ8** security/automation
control panels, connected over the network (M1XEP module) or a direct serial/USB cable.

*This is a community-developed integration and is not officially affiliated with Elk
Products, Inc.*

## Architecture

The integration owns the Elk-M1 ASCII protocol directly (`custom_components/elkm1/helpers/elk/`)
- message encoding/decoding and the panel's typed subsystem objects (areas, zones,
outputs, tasks, thermostats, lights, counters, keypads). Each config entry owns a
single native `asyncio` connection/reconnect task, so serial connections can be
opened with automatic baud-rate detection (the protocol has no way to query or negotiate
baud rate on the wire; a Global Programming setting fixes it at 9600-115200, so on
connect the integration sweeps the standard rates and locks onto whichever one gets a
valid reply, caching it on the config entry for future reconnects).

Data flows push-first: the panel broadcasts state changes once its Global Programming
"Xmit ... Changes" settings are enabled, and the coordinator reacts to those broadcasts
immediately rather than polling. A configurable poll interval (Settings for the config
entry) is a fallback for panels that have broadcasts disabled, not the primary data path.

## Requirements

* Home Assistant 2026.8.3 on Python 3.14.2 or newer.
* An Elk-M1 Security Panel connected via an M1XEP Ethernet module, or a direct
  serial/USB cable.

Direct serial currently uses pinned `pyserial-asyncio-fast`; the planned dependency
transition is to Home Assistant's `serialx` stack. The legacy `pyserial-asyncio`
package is intentionally not installed alongside it.

## Installation

### HACS (recommended)
1. Open **HACS** in Home Assistant.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Add this repository's URL, category **Integration**.
4. Search for **Elk-M1 Security**, click **Download**, then restart Home Assistant.

### Manual
1. Download the latest release from this repository.
2. Copy `custom_components/elkm1` into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

### Setup
1. In Home Assistant, go to **Settings > Devices & Services > Add Integration** and
   search for **Elk-M1**.
2. Follow **Connection method > Interface or discovered panel > Verify ELK-M1 > ELK
   options > Complete**. Network discovery, manual network entry, and direct Serial/USB
   remain separate choices. Serial uses Home Assistant's serial-port selector and only
   the selected port is probed.
3. For a network connection, the panel's username/password (for secure schemes) are
   verified with a real, briefly-lived connection before the entry is created. For
   serial, the selected port is probed with an ELK `vn` request while sweeping baud
   rates automatically. Generic USB chip VID/PID pairs are intentionally not advertised
   as ELK devices; choose the adapter explicitly unless product-specific metadata is
   available.

Afterward, **Settings > Devices & Services > Elk-M1 > Configure** lets you change the
poll-interval fallback, and **Reconfigure** lets you change the connection itself
without deleting and re-adding the integration.

## What it creates

Platform | What
---|---
`alarm_control_panel` | One entity per configured area (1-8), with arm-away/home/night/vacation/custom-bypass and disarm. Panic trigger is intentionally unavailable because ELK protocol v1.90 defines no third-party panic command.
`binary_sensor` | One entity per configured zone (door/window/motion/smoke/CO/freeze/gas/heat/water, mapped from the panel's zone-definition field), one per system trouble condition (disabled by default), and one aggregate "any door/window open" sensor per area.
`sensor` | Panel status/trouble summary, an active-zones count, and per-zone temperature/voltage sensors for zones defined as such.
`switch` | Physical outputs 1-208 (65-208 disabled by default), thermostat emergency-heat, zone bypass (as a toggle), and a proxy switch for pre-arm automation blueprints.
`climate` | Elk-connected thermostats, if the panel has any.
`light` | PLC/X10 lighting outputs.
`number` | RAM counters and EEPROM custom values that have a panel-assigned name.
`time` | Time-of-day-typed custom values.
`scene` | Elk tasks (fire-and-forget activations).

Every entity that receives a panel-assigned name (zones, outputs, tasks, thermostats,
lights, counters) picks it up automatically - no manual naming required, though names
may arrive slightly after entity creation on first sync.

## Cross-integration support

See [`docs/cross_integration.md`](docs/cross_integration.md) for the full picture.
Briefly: **Alarmo** and **Better Thermostat** get real code-level support (an
Alarmo-auto-setup helper service, a one-way state-mirror blueprint that keeps Alarmo in
sync with the physical panel's arm/disarm/alarm state with no artificial delay, and a
per-area door/window aggregate sensor built specifically to feed any climate
integration's window-pause logic, not just Elk's own thermostats). **Davis Weather**,
**Unifi Protect**, **Browser Mod**, and **ESP32 Bluetooth Proxy** have no direct data
link to the panel, so support there means standards-compliant entities plus ready-made
[Blueprints](blueprints/automation/) rather than integration code.

## Services

Domain-level (`elkm1.*`), routed to a specific panel via an optional `prefix` field
when more than one is configured:

* `elkm1.speak_word` / `elkm1.speak_phrase` - speak a vocabulary word/phrase through
  the panel's voice driver.
* `elkm1.set_time` - write the panel's real-time clock.
* `elkm1.display_message` - show a message on an area's keypads.
* `elkm1.get_security_summary` - returns faulted-zone data to an automation/script.
* `elkm1.alarmo_auto_setup` - scans for this integration's zone `binary_sensor`
  entities and posts a notification listing them, for quick setup in Alarmo's
  **Sensors** tab.

Entity-level, targeting specific entities:

* Standard `alarm_control_panel.*` services (`alarm_disarm`, `alarm_arm_away`,
  `alarm_arm_home`, `alarm_arm_night`, `alarm_arm_vacation`,
  `alarm_arm_custom_bypass`, `alarm_trigger`), plus this integration's
  `elkm1.alarm_bypass` / `elkm1.alarm_clear_bypass` (toggle bypass for all zones in an
  area) and `elkm1.alarm_arm_home_instant` / `elkm1.alarm_arm_night_instant`
  (Elk's no-entry-delay arm variants).
* `elkm1.sensor_zone_bypass` / `elkm1.sensor_zone_trigger` on zone `binary_sensor`
  entities.
* `elkm1.sensor_counter_refresh` / `elkm1.sensor_counter_set` on counter `number`
  entities.
* `elkm1.switch_output_turn_on_for` on output `switch` entities, to turn one on for a
  specified duration.

## Removing the integration

**Settings > Devices & Services > Elk-M1 > ...(menu) > Delete** removes the config
entry, its entities, and its device registry entries; nothing is left behind on the
panel itself (this integration never writes persistent configuration to the panel). If
installed via HACS, remove it from HACS afterward to stop tracking updates; a manual
install can be removed by deleting `custom_components/elkm1` and restarting.

## Troubleshooting

Enable debug logging for the integration (**Settings > Devices & Services > Elk-M1 >
...(menu) > Enable debug logging**, or `logger.set_level` for
`custom_components.elkm1` in `configuration.yaml`) to see connection attempts, baud
detection, and raw protocol traffic. The `diagnostics` download (from the integration's
device page) includes a redacted snapshot of the panel's current state - useful when
filing an issue.

## Contributing

`requirements-dev.txt` has the pinned dev dependencies. `ruff check .` and
`mypy --config-file mypy.ini` are the project's lint/type checks; `pytest` runs the test
suite in `tests/`. `custom_components/elkm1/quality_scale.yaml` tracks this
integration's status against Home Assistant's quality scale honestly - rules are marked
`todo` with a real reason rather than `done` until actually verified.

Design rationale, protocol facts, and the release path live under `docs/`; start at
[`docs/README.md`](docs/README.md).

Hardware release qualification is deliberately separate from mocked CI. See
[`docs/live_qualification.md`](docs/live_qualification.md); a passing config-flow test
does not prove a live secure/non-secure XEP or serial panel connection.
