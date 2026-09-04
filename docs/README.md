# Documentation index

One line per document stating what it owns, so a reader knows where a fact belongs. Code
carries only what a reader needs at the point of reading; explanation lives here.

- `design.md`: architecture and rationale (push-first coordinator, login versus connected,
  dynamic entity creation, transport replacement, entity mapping choices, test strategy).
- `protocol.md`: wire and panel facts (baud sweep, heartbeat window, command buffer,
  Global Programming broadcast bits, firmware floor, trouble status, alarm and zone
  states), each marked verified or unverified.
- `operations.md`: the test gate, the release path and its GitHub App, branch protection,
  runtime knobs, and line endings.
- `decisions.md`: dated decisions with the alternative rejected and why.
- `backlog.md`: dated open items moved out of code.
- `protocol_coverage.md`: which ELK-M1 RS-232 ASCII protocol v1.90 messages the
  integration implements, and how.
- `live_qualification.md`: the hardware release qualification matrix that mocked CI cannot
  replace.
- `cross_integration.md`: what is real integration code versus blueprint-only support for
  Alarmo, Better Thermostat, Davis Weather, UniFi Protect, Browser Mod, and ESP32
  Bluetooth proxies.
- `../custom_components/elkm1/PROJECT_MAP.md`: the structural map of the integration's
  files and the library quirks a contributor must know before changing coordinator or
  entity code.
