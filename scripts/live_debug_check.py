#!/usr/bin/env python3
"""Live smoke test: run the real Elk-M1 integration against physical hardware.

Drives the actual `custom_components/elkm1` code (config entry setup,
`ElkDataUpdateCoordinator`, entity-platform forwarding, clean unload) against
a real panel - not a mocked test, and not a standalone protocol script. See
`docs/live_qualification.md` for the full history of live runs this
supplements and the incidents ("cn" driving an unrelated siren) that keep the
scope of this script deliberately read-only.

Not part of the CI gate - this touches a real serial (or, in principle,
network) connection. Run it by hand when debugging connectivity against real
hardware, or as part of a release qualification pass.

Read-only by design: connects, logs in, waits for the first coordinator
refresh, reports what got forwarded to the entity registry, listens for a
window of live push traffic, then unloads. Never sends an arm/disarm/output/
bypass/write command.

Prerequisites (native Windows works directly against a COM port; on Linux/
WSL the serial device must actually be attached to that environment):

    pip install --user homeassistant==2026.9.0
    pip install --user --no-deps pytest-homeassistant-custom-component==0.13.362

The harness package is pulled in `--no-deps` deliberately: its pytest plugin
(`plugins.py`) imports `fcntl` and only runs on Linux/WSL (see the
`ha-dev-current` skill's "HA test harness needs WSL" note), but the
`common.py` helpers this script actually uses (`MockConfigEntry`,
`async_test_home_assistant`) have no such dependency and run natively on
Windows.

Usage:
    python scripts/live_debug_check.py --port COM3
    python scripts/live_debug_check.py --port COM3 --listen-seconds 30 -v
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_LOGGER = logging.getLogger("live_debug_check")


async def _run(repo_root: Path, port: str, prefix: str, listen_seconds: float) -> int:
    from homeassistant import loader
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import entity_registry as er, frame as frame_helper
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_test_home_assistant,
    )

    # Give HA's loader a real on-disk custom_components/elkm1 to discover
    # without writing test-harness .storage/ clutter into the actual repo.
    config_dir = tempfile.mkdtemp(prefix="elkm1_live_check_")
    shutil.copytree(
        repo_root / "custom_components" / "elkm1",
        Path(config_dir) / "custom_components" / "elkm1",
    )

    exit_code = 1
    try:
        async with async_test_home_assistant(config_dir=config_dir) as hass:
            try:
                # Force the loader to (re)scan for custom components instead
                # of trusting any cached/empty discovery.
                hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
                # Normally done by homeassistant.bootstrap during full startup.
                frame_helper.async_setup(hass)
                # This standalone script's call stack has no real
                # integration-loader frame for frame.get_integration_frame()
                # to find, so DataUpdateCoordinator's "pass config_entry
                # explicitly" deprecation notice hits the no-integration-found
                # path and raises by default (core_behavior=ERROR) - a
                # harness artifact of running outside the real loader, not a
                # product bug (real production setup always has a proper
                # frame and this call is silently ignored for custom
                # integrations). Silence just this one helper.
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

                _LOGGER.info("Setup result: %s, entry state: %s", setup_ok, entry.state)
                if not setup_ok or entry.state is not ConfigEntryState.LOADED:
                    _LOGGER.error("Setup did not reach LOADED - aborting")
                    return 1

                coordinator = entry.runtime_data.coordinator
                data = coordinator.data
                _LOGGER.info("--- Panel snapshot ---")
                _LOGGER.info("panel_version=%s", data.panel_version)
                _LOGGER.info(
                    "num_areas=%d zones=%d outputs=%d thermostats=%d counters=%d "
                    "settings=%d tasks=%d keypads=%d lights=%d",
                    data.num_areas,
                    len(data.zones),
                    len(data.outputs),
                    len(data.thermostats),
                    len(data.counters),
                    len(data.settings),
                    len(data.tasks),
                    len(data.keypads),
                    len(data.lights),
                )
                _LOGGER.info(
                    "connected=%s last_update_success=%s",
                    coordinator.connected,
                    coordinator.last_update_success,
                )
                _LOGGER.info(
                    "zones_faulted=%s (%s)",
                    data.zones_faulted,
                    data.faulted_zone_names or "none",
                )
                for area_index, area_data in sorted(data.areas.items()):
                    _LOGGER.info(
                        "area %d: alarm_state=%s armed_status=%s arm_up_state=%s "
                        "entry_delay_active=%s exit_delay_active=%s",
                        area_index + 1,
                        area_data.alarm_state,
                        area_data.armed_status,
                        area_data.arm_up_state,
                        area_data.entry_delay_active,
                        area_data.exit_delay_active,
                    )

                entity_reg = er.async_get(hass)
                entities = [
                    e
                    for e in entity_reg.entities.values()
                    if e.config_entry_id == entry.entry_id
                ]
                by_domain: dict[str, int] = {}
                for e in entities:
                    by_domain[e.domain] = by_domain.get(e.domain, 0) + 1
                _LOGGER.info(
                    "--- Entities forwarded to the registry: %d total ---", len(entities)
                )
                for domain, count in sorted(by_domain.items()):
                    _LOGGER.info("  %-20s %d", domain, count)

                _LOGGER.info(
                    "--- Listening for %.0fs of live push traffic "
                    "(DEBUG logs above show frames) ---",
                    listen_seconds,
                )
                await asyncio.sleep(listen_seconds)

                _LOGGER.info("=== Unloading cleanly ===")
                unload_ok = await hass.config_entries.async_unload(entry.entry_id)
                await hass.async_block_till_done()
                _LOGGER.info("Unload result: %s, entry state: %s", unload_ok, entry.state)

                exit_code = 0 if setup_ok and unload_ok else 1
            except Exception:
                _LOGGER.exception("Live check failed with an exception")
                exit_code = 1
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)

    _LOGGER.info("=== %s ===", "PASS" if exit_code == 0 else "FAIL")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--repo",
        default=REPO_ROOT,
        type=Path,
        help="Path to the ha_int_elkm1 repo root (default: this script's own repo)",
    )
    parser.add_argument("--port", default="COM3", help="Serial port the panel is attached to")
    parser.add_argument("--prefix", default="", help="Config entry prefix")
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=15.0,
        dest="listen_seconds",
        help="How long to observe live push traffic before unloading (default: 15s)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG-level logs for everything, not just custom_components.elkm1",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    if not args.verbose:
        logging.getLogger("custom_components.elkm1").setLevel(logging.DEBUG)

    return asyncio.run(_run(args.repo, args.port, args.prefix, args.listen_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
