"""Panel settings configuration and verification.

The Xmit Changes bits cannot be read back; they are inferred from observed
broadcasts. See docs/protocol.md.
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

    `enabled` False means "unconfirmed", not "confirmed disabled".
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
        # Panel.sync() already sent vn; the reply is async, so poll briefly.
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

            # Floor is 4.6.8 on 4.x or 5.2.0 on 5.x+; a plain tuple compare would accept 5.0.x.
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
    """Verify panel is properly configured for Home Assistant."""
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
