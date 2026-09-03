"""Panel settings configuration and verification.

The Elk-M1 ASCII protocol has no command to read back the panel's Global
Programming "Xmit ... Changes" bits (locations 30, 35-40) that gate
whether it proactively broadcasts zone/output/task/light/keypad changes
and event-log entries - these can only be set via a keypad or ElkRP, not
queried over the RS232/IP link. So there is no way to directly confirm
whether they're enabled; the best this module can do is empirically infer
it from whether the corresponding broadcast type has actually been seen
since connecting, and be honest that "not seen yet" isn't proof it's
disabled (it could just mean nothing of that type has changed yet).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Global Programming location -> (setting name, broadcast message type it gates).
REQUIRED_SETTINGS: dict[int, tuple[str, str]] = {
    35: ("Transmit Event Log (G35)", "LD"),
    36: ("Transmit Zone Changes (G36)", "ZC"),
    37: ("Transmit Output Changes (G37)", "CC"),
    38: ("Transmit Automation Task Changes (G38)", "TC"),
    39: ("Transmit Light Changes (G39)", "PC"),
    40: ("Transmit Keypad Changes (G40)", "KC"),
}


async def check_required_settings(coordinator: Any) -> dict[int, dict[str, Any]]:
    """Report, per Global Programming location, whether its broadcast has been observed.

    `enabled` here means "confirmed active" (the broadcast has been seen at
    least once), not "confirmed disabled" when False - the honest label for
    a location whose broadcast hasn't arrived yet is "unconfirmed", since
    that can just mean nothing of that type has changed since connecting.
    """
    counts = getattr(coordinator, "broadcast_counts", {})
    return {
        location: {
            "name": name,
            "message_type": msg_type,
            "enabled": counts.get(msg_type, 0) > 0,
            "broadcast_count": counts.get(msg_type, 0),
        }
        for location, (name, msg_type) in REQUIRED_SETTINGS.items()
    }


async def check_panel_version(coordinator: Any) -> str | None:
    """Check ELK-M1 panel version by sending the 'vn' command.

    Args:
        coordinator: ElkDataUpdateCoordinator instance

    Returns:
        Version string (e.g., "4.6.8" or "5.2.0") or None if not available
    """
    try:
        # The panel version is already requested as part of the panel's
        # sync-on-connect sequence (Panel.sync() sends vn); the reply is
        # async and may not have arrived yet right after first refresh, so
        # poll briefly rather than assuming it's already there.
        version = coordinator.data.panel_version
        for _ in range(15):
            if version:
                break
            await asyncio.sleep(0.2)
            version = coordinator.data.panel_version

        if version:
            _LOGGER.info("ELK-M1 Panel Version: %s", version)

            parts = str(version).split(".")
            major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
            minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            version_tuple = (major, minor, patch)

            # Minimum: 4.6.8+ on the 4.x branch, or 5.2.0+ on 5.x and later -
            # a plain version_tuple >= (4, 6, 8) would also accept 5.0.0/5.1.x
            # (lexicographic comparison stops at the first differing element),
            # which are below the required 5.2.0 floor, so the 4.x branch is
            # checked only when major == 4.
            if version_tuple >= (5, 2, 0) or (major == 4 and version_tuple >= (4, 6, 8)):
                _LOGGER.info("Panel version %s is supported", version)
                return str(version)

            _LOGGER.warning(
                "Panel version %s may have limited feature support. "
                "Recommended: 4.6.8+ or 5.2.0+",
                version,
            )
            return str(version)

        _LOGGER.warning("Could not determine panel version. Did the panel respond?")
        return None

    except Exception as err:
        _LOGGER.debug("Error checking panel version: %s", err)
        return None


async def verify_panel_configuration(coordinator: Any) -> tuple[bool, dict[str, Any]]:
    """Verify panel is properly configured for Home Assistant.

    Gives Global Programming broadcast settings a brief window to prove
    themselves (a real change would normally arrive within a few seconds
    of connecting if push updates are working) before reporting which are
    confirmed active vs. unconfirmed.
    """
    _LOGGER.info("Verifying ELK-M1 panel configuration...")

    details: dict[str, Any] = {}

    version = await check_panel_version(coordinator)
    details["version"] = version

    # Give broadcasts a short window to arrive before checking.
    await asyncio.sleep(5.0)
    settings_status = await check_required_settings(coordinator)
    details["settings"] = settings_status

    unconfirmed = [s["name"] for s in settings_status.values() if not s["enabled"]]
    if unconfirmed:
        _LOGGER.warning(
            "Could not confirm these Global Programming settings are enabled "
            "(no broadcast of the matching type has been seen yet - this may "
            "just mean nothing of that type has changed, or it may mean the "
            "setting needs to be enabled via keypad or ElkRP under "
            "'Global Programming'): %s",
            ", ".join(unconfirmed),
        )

    is_configured = version is not None
    details["configured"] = is_configured

    return is_configured, details
