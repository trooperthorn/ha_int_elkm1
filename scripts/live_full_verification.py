#!/usr/bin/env python3
"""Guided, interactive verification of every Elk-M1 function against real hardware.

This is for you to run yourself, in your own terminal, once, while the panel
is still connected and before you have to disable/bench-test it again. It is
not part of the CI gate, not something the assistant runs for you, and it
never accepts a passcode as a command-line argument or logs one - every code
prompt uses `getpass` (no echo).

Read-only checks (connection, entity forwarding, current status) always run
first and need no confirmation. Every write-capable function after that is
its own numbered step: it prints exactly what it is about to send and to
what area/zone/output/task/light number, states its risk level, and waits
for you to type `yes` before doing anything - nothing fires without you
confirming that specific step. Type anything else (including just Enter) to
skip that one step and move to the next; nothing is skipped silently.

Risk levels, and why:
  SAFE     - read-only, or a write with no plausible physical side effect
             (a counter value in panel RAM, a keypad text message already
             proven harmless in this session's live testing).
  MODERATE - a real write that needs your passcode (arm/disarm, zone
             bypass). Arming is refused automatically if the target area has
             any violated (open) zone assigned to it - see
             docs/live_qualification.md's arm-with-violated-zones risk note
             - and disarm is always attempted afterward even if the arm
             itself failed, so a half-finished step can't leave an area
             armed.
  HIGH     - drives a real output, task, or PLC light address. Only wire
             format and panel acknowledgement are verified by every earlier
             live run in docs/live_qualification.md; nobody has verified
             what is actually connected to a given output/task/light number
             on this specific panel. The "cn" incident in that document (an
             audible alarm from a supposedly-inert output test) is exactly
             this risk, and is why these steps ask for the specific number
             AND a typed "yes" before sending anything, every time.
  SKIPPED  - thermostat set/request: no Elk-connected thermostat exists on
             this bench setup, a deliberate scope decision recorded in
             docs/decisions.md, not tested here.

Prerequisites (same as scripts/live_debug_check.py):
    pip install --user homeassistant==2026.9.0
    pip install --user --no-deps pytest-homeassistant-custom-component==0.13.362

Usage:
    python scripts/live_full_verification.py --list      # see the catalog, no connection made
    python scripts/live_full_verification.py --port COM3 # run for real
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import shutil
import sys
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
_LOGGER = logging.getLogger("live_full_verification")


@dataclass
class Step:
    """One function under test."""

    name: str
    risk: str
    description: str
    run: Callable[[Any], Awaitable[None]]
    needs_code: bool = False


def _print_catalog(steps: list[Step]) -> None:
    print("\nCatalog of verification steps, in the order they run:\n")
    for i, step in enumerate(steps, 1):
        code_note = " (needs passcode)" if step.needs_code else ""
        print(f"  {i:2d}. [{step.risk:8s}] {step.name}{code_note}")
        print(f"       {step.description}")
    print(
        "\nEvery step above SAFE prints exactly what it will send and asks you to "
        "type 'yes' before doing anything. Nothing runs without that.\n"
    )


def _ask(prompt: str) -> bool:
    answer = input(f"{prompt} [type 'yes' to proceed, anything else to skip]: ").strip()
    return answer.lower() == "yes"


def _ask_int(prompt: str) -> int | None:
    raw = input(f"{prompt} (or Enter to skip): ").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        print(f"  '{raw}' isn't a number - skipping this step.")
        return None


class Context:
    """Shared state passed to every step."""

    def __init__(self, hass: Any, coordinator: Any) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._code: str | None = None

    def code(self) -> str:
        if self._code is None:
            self._code = getpass.getpass(
                "Enter the panel user code for this and any later step that needs it: "
            )
        return self._code


async def _step_snapshot(ctx: Context) -> None:
    data = ctx.coordinator.data
    _LOGGER.info("panel_version=%s connected=%s", data.panel_version, ctx.coordinator.connected)
    _LOGGER.info(
        "zones_faulted=%s (%s)", data.zones_faulted, data.faulted_zone_names or "none"
    )
    for area_index, area_data in sorted(data.areas.items()):
        _LOGGER.info(
            "area %d: alarm_state=%s armed_status=%s arm_up_state=%s",
            area_index + 1,
            area_data.alarm_state,
            area_data.armed_status,
            area_data.arm_up_state,
        )


async def _step_entity_states(ctx: Context) -> None:
    from homeassistant.helpers import entity_registry as er

    entity_reg = er.async_get(ctx.hass)
    owned_ids = {
        e.entity_id
        for e in entity_reg.entities.values()
        if e.config_entry_id == ctx.coordinator.config_entry.entry_id
    }
    owned_states = [s for s in ctx.hass.states.async_all() if s.entity_id in owned_ids]
    unavailable = [s.entity_id for s in owned_states if s.state in ("unavailable", "unknown")]
    _LOGGER.info(
        "%d entities have a real state written; %d are unavailable/unknown%s",
        len(owned_states),
        len(unavailable),
        f": {unavailable[:10]}" if unavailable else "",
    )


async def _step_display_message(ctx: Context) -> None:
    area = _ask_int("Which area's keypads should show the test message? (1-8)")
    if area is None:
        return
    if not _ask(f"About to send a display message to area {area}'s keypads"):
        return
    await ctx.coordinator.display_message(
        area_index=area - 1, line1="HA Verify", line2="Function Test", clear=1
    )
    _LOGGER.info("Sent. Check the physical keypad for area %d now.", area)


async def _step_speak(ctx: Context) -> None:
    number = _ask_int("Word number to speak (0-799, see vocabulary.py)")
    if number is None:
        return
    if not _ask(f"About to send speak_word({number}) - listen for audio from a keypad"):
        return
    await ctx.coordinator.speak_word(number)
    _LOGGER.info("Sent. If a keypad has a speaker, it may have just spoken.")


async def _step_counter(ctx: Context) -> None:
    index = _ask_int("Counter number to round-trip a test value through (1-64)")
    if index is None:
        return
    counters = ctx.coordinator.data.counters
    if index < 1 or index > len(counters):
        print(f"  Counter {index} doesn't exist on this panel - skipping.")
        return
    obj = counters[index - 1]
    original = getattr(obj, "value", None)
    if not _ask(
        f"About to write counter {index} to 12345 then restore it to {original!r}"
    ):
        return
    await ctx.coordinator.async_queue_command(lambda: obj.set(12345), f"counter {index} set")
    await asyncio.sleep(0.5)
    _LOGGER.info("Wrote 12345. Readback (may lag one poll): %s", getattr(obj, "value", None))
    if original is not None:
        await ctx.coordinator.async_queue_command(
            lambda: obj.set(int(original)), f"counter {index} restore"
        )
        _LOGGER.info("Restored to %s.", original)


async def _step_set_time(ctx: Context) -> None:
    if not _ask("About to write the panel's real-time clock to the current time"):
        return
    from homeassistant.util import dt as dt_util

    await ctx.coordinator.set_panel_time(dt_util.now())
    _LOGGER.info("Sent. Check a keypad's clock display if it has one.")


async def _step_zone_bypass(ctx: Context) -> None:
    zone = _ask_int("Zone number to bypass then immediately un-bypass (1-208)")
    if zone is None:
        return
    if not _ask(f"About to bypass zone {zone}, confirm the change, then clear the bypass"):
        return
    code = ctx.code()
    await ctx.coordinator.bypass_zone(zone, code)
    await asyncio.sleep(1.0)
    zones = ctx.coordinator.data.zones
    if zone - 1 < len(zones):
        _LOGGER.info("Zone %d logical_status now: %s", zone, zones[zone - 1].logical_status)
    await ctx.coordinator.unbypass_zone(zone, code)
    _LOGGER.info("Sent the clear-bypass toggle back.")


async def _step_arm_disarm(ctx: Context) -> None:
    area = _ask_int("Area number to arm-away then disarm (1-8)")
    if area is None:
        return
    area_index = area - 1
    violated = [
        z
        for z in ctx.coordinator.data.zones
        if getattr(z, "area", -1) == area_index
        and str(getattr(z, "logical_status", "")).endswith("VIOLATED")
    ]
    if violated:
        print(
            f"  REFUSING: area {area} has {len(violated)} violated zone(s) assigned "
            "to it. Arming with a violated zone risks an immediate real alarm - see "
            "docs/live_qualification.md. Clear or bypass those zones first if you "
            "want to test this area, or pick a different area."
        )
        return
    if not _ask(f"About to arm area {area} (arm-away) then disarm it"):
        return
    code = ctx.code()
    try:
        result = await ctx.coordinator.async_alarm_arm_away(area_index, int(code))
        _LOGGER.info("Arm result: %s", result)
        await asyncio.sleep(2.0)
        data = ctx.coordinator.data.areas.get(area_index)
        if data:
            _LOGGER.info(
                "area %d now: alarm_state=%s armed_status=%s arm_up_state=%s",
                area,
                data.alarm_state,
                data.armed_status,
                data.arm_up_state,
            )
    finally:
        _LOGGER.info("Restoring: disarming area %d ...", area)
        result = await ctx.coordinator.async_alarm_disarm(area_index, int(code))
        _LOGGER.info("Disarm result: %s", result)


async def _step_output(ctx: Context) -> None:
    output = _ask_int("Output number to turn ON for 3 seconds then off (1-208)")
    if output is None:
        return
    print(
        f"  HIGH RISK: output {output} may be wired to anything - a siren, a relay, "
        "a light. The 'cn' incident in docs/live_qualification.md happened exactly "
        "this way. Only proceed if you know what output %d actually drives."
        % output
    )
    if not _ask(f"About to turn output {output} ON for 3 seconds"):
        return
    outputs = ctx.coordinator.data.outputs
    if output - 1 >= len(outputs):
        print(f"  Output {output} doesn't exist on this panel - skipping.")
        return
    obj = outputs[output - 1]
    await ctx.coordinator.async_queue_command(lambda: obj.turn_on(3), f"output {output} on")
    _LOGGER.info("Sent. Output should be on now for ~3 seconds, then auto-off.")


async def _step_task(ctx: Context) -> None:
    task = _ask_int("Task number to activate (1-32)")
    if task is None:
        return
    print(
        f"  HIGH RISK: task {task} may run a real panel-side automation macro with "
        "unknown side effects. Only proceed if you know what task %d actually does."
        % task
    )
    if not _ask(f"About to activate task {task}"):
        return
    tasks = ctx.coordinator.data.tasks
    if task - 1 >= len(tasks):
        print(f"  Task {task} doesn't exist on this panel - skipping.")
        return
    obj = tasks[task - 1]
    await ctx.coordinator.async_queue_command(obj.activate, f"task {task} activate")
    _LOGGER.info("Sent.")


async def _step_light(ctx: Context) -> None:
    light = _ask_int("PLC light address (1-256) to turn on then off")
    if light is None:
        return
    print(
        f"  HIGH RISK: light {light} may be a real powerline-controlled device - a "
        "lamp, an appliance, anything paired to that housecode/unit. Only proceed "
        "if you know what light %d actually is." % light
    )
    if not _ask(f"About to turn light {light} on then off"):
        return
    lights = ctx.coordinator.data.lights
    if light - 1 >= len(lights):
        print(f"  Light {light} doesn't exist on this panel - skipping.")
        return
    obj = lights[light - 1]
    await ctx.coordinator.async_queue_command(lambda: obj.level(100), f"light {light} on")
    await asyncio.sleep(2.0)
    await ctx.coordinator.async_queue_command(lambda: obj.level(0), f"light {light} off")
    _LOGGER.info("Sent on then off.")


def _build_steps() -> list[Step]:
    return [
        Step("Panel snapshot", "SAFE", "Read panel version, area/zone status.", _step_snapshot),
        Step(
            "Entity states",
            "SAFE",
            "Confirm every forwarded entity has a real (not unavailable) state.",
            _step_entity_states,
        ),
        Step(
            "Display message",
            "SAFE",
            "Write a text message to one area's keypads (already proven harmless "
            "in this session's live testing).",
            _step_display_message,
        ),
        Step(
            "Speak word",
            "CAUTION",
            "Ask the panel to speak a vocabulary word; unconfirmed whether any "
            "keypad here has an active speaker.",
            _step_speak,
        ),
        Step(
            "Counter round-trip",
            "SAFE",
            "Write a counter to a test value, read it back, restore the original.",
            _step_counter,
        ),
        Step(
            "Set panel time",
            "CAUTION",
            "Write the panel's real-time clock to the current time.",
            _step_set_time,
        ),
        Step(
            "Zone bypass round-trip",
            "MODERATE",
            "Bypass one zone, confirm the change, then clear the bypass. Needs "
            "your passcode.",
            _step_zone_bypass,
            needs_code=True,
        ),
        Step(
            "Arm then disarm",
            "MODERATE",
            "Arm-away one area then disarm it. Needs your passcode. Refuses to "
            "run if the area has any violated zone assigned to it.",
            _step_arm_disarm,
            needs_code=True,
        ),
        Step(
            "Output control",
            "HIGH",
            "Turn one output on for 3 seconds, then off. Unknown physical wiring "
            "- the 'cn' incident risk.",
            _step_output,
        ),
        Step(
            "Task activation",
            "HIGH",
            "Activate one task (panel-side automation macro). Unknown side effects.",
            _step_task,
        ),
        Step(
            "PLC light control",
            "HIGH",
            "Turn one PLC light address on then off. Unknown physical device.",
            _step_light,
        ),
    ]


async def _run(repo_root: Path, port: str, prefix: str) -> int:
    from homeassistant import loader
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import frame as frame_helper
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_test_home_assistant,
    )

    config_dir = tempfile.mkdtemp(prefix="elkm1_full_verify_")
    shutil.copytree(
        repo_root / "custom_components" / "elkm1",
        Path(config_dir) / "custom_components" / "elkm1",
    )

    exit_code = 1
    try:
        async with async_test_home_assistant(config_dir=config_dir) as hass:
            try:
                hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
                frame_helper.async_setup(hass)
                frame_helper.report_usage = lambda *a, **k: None

                entry = MockConfigEntry(
                    domain="elkm1",
                    data={
                        "connection_type": "serial",
                        "serial_port": port,
                        "device_id": f"serial:{port}",
                        "prefix": prefix,
                        "pin": "",
                    },
                    unique_id=f"serial:{port}",
                )
                entry.add_to_hass(hass)

                _LOGGER.info("=== Setting up elkm1 against %s ===", port)
                setup_ok = await hass.config_entries.async_setup(entry.entry_id)
                await hass.async_block_till_done()
                if not setup_ok or entry.state is not ConfigEntryState.LOADED:
                    _LOGGER.error("Setup did not reach LOADED - aborting")
                    return 1

                ctx = Context(hass, entry.runtime_data.coordinator)

                print(
                    "\nThermostat set/request: SKIPPED - no Elk-connected thermostat "
                    "on this bench setup (see docs/decisions.md).\n"
                )

                for step in _build_steps():
                    print(f"\n--- {step.name} [{step.risk}] ---")
                    print(f"    {step.description}")
                    try:
                        await step.run(ctx)
                    except Exception:
                        _LOGGER.exception("Step '%s' raised - continuing", step.name)

                _LOGGER.info("=== Unloading cleanly ===")
                unload_ok = await hass.config_entries.async_unload(entry.entry_id)
                await hass.async_block_till_done()
                _LOGGER.info("Unload result: %s, entry state: %s", unload_ok, entry.state)
                exit_code = 0 if setup_ok and unload_ok else 1
            except Exception:
                _LOGGER.exception("Verification run failed with an exception")
                exit_code = 1
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)

    _LOGGER.info("=== %s ===", "DONE" if exit_code == 0 else "FAILED")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", default=REPO_ROOT, type=Path)
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--list", action="store_true", help="Print the catalog and exit")
    args = parser.parse_args()

    if args.list:
        _print_catalog(_build_steps())
        return 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("custom_components.elkm1").setLevel(logging.INFO)

    return asyncio.run(_run(args.repo, args.port, args.prefix))


if __name__ == "__main__":
    raise SystemExit(main())
