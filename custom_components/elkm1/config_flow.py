"""Config flow for Elk-M1 Control.

Serial/USB is the only supported transport - network (M1XEP) connectivity
was removed entirely as a deliberate security posture, not a missing
feature. See docs/decisions.md 2026-09-05.
"""

from __future__ import annotations

import glob
import logging
import os
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PREFIX
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BAUD_RATE,
    CONF_CONNECTION_TYPE,
    CONF_DEVICE_ID,
    CONF_PIN,
    CONF_POLL_INTERVAL,
    CONF_SERIAL_PORT,
    CONNECTION_SERIAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .helpers.transport import validate_serial_port

_LOGGER = logging.getLogger(__name__)

# A masked input for secrets shown on screen (the panel PIN) so a stored
# value is never displayed in the clear when a form is reopened, and isn't
# visible to anyone glancing at the screen while it's typed. See
# docs/decisions.md 2026-09-05.
_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


def hostname_from_url(url: str) -> str:
    """Return the hostname from an ELK URL."""
    parsed = urlparse(url)
    return parsed.hostname or url.replace("serial://", "")


def get_persistent_port_path(device_path: str) -> str:
    """Prefer Linux by-id, then by-path, for a selected serial endpoint."""
    try:
        resolved_target = os.path.realpath(device_path)
    except OSError:
        return device_path

    for directory in ("/dev/serial/by-id", "/dev/serial/by-path"):
        for symlink in glob.glob(f"{directory}/*"):
            try:
                if os.path.realpath(symlink) == resolved_target:
                    return symlink
            except OSError:
                continue
    return device_path


class Elkm1ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Elk-M1 serial configuration and identity contract."""

    VERSION = 3
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._pending_data: dict[str, Any] | None = None
        self._pending_title: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: ConfigEntry) -> ElkOptionsFlowHandler:
        """Return the operational options flow."""
        return ElkOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select one serial port, then probe only that port for an ELK panel."""
        errors: dict[str, str] = {}
        if user_input is not None:
            port = await self.hass.async_add_executor_job(
                get_persistent_port_path, str(user_input[CONF_SERIAL_PORT])
            )
            try:
                baud = await validate_serial_port(port)
            except (TimeoutError, OSError, ValueError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error probing selected ELK serial port")
                errors["base"] = "unknown"
            else:
                device_id = f"serial:{port}"
                await self.async_set_unique_id(device_id, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                raw_pin = user_input.get(CONF_PIN)
                pin = (
                    str(raw_pin).strip()
                    if raw_pin not in (None, "", 0, "0")
                    else ""
                )
                self._pending_title = f"Elk-M1 Serial @ {port}"
                self._pending_data = {
                    CONF_CONNECTION_TYPE: CONNECTION_SERIAL,
                    CONF_SERIAL_PORT: port,
                    CONF_DEVICE_ID: device_id,
                    CONF_BAUD_RATE: baud,
                    CONF_PREFIX: str(user_input.get(CONF_PREFIX, "elkm1")),
                    CONF_PIN: pin,
                }
                return await self.async_step_elkm1_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERIAL_PORT): selector.SerialPortSelector(),
                    vol.Optional(CONF_PREFIX, default="elkm1"): str,
                    vol.Optional(CONF_PIN, default=""): _PASSWORD_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_elkm1_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect operational options after panel verification."""
        assert self._pending_data is not None
        assert self._pending_title is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._pending_title,
                data=self._pending_data,
                options={CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL]},
            )
        return self.async_show_form(
            step_id="elkm1_options",
            data_schema=_options_schema(DEFAULT_POLL_INTERVAL),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure a serial endpoint without accepting a different adapter."""
        entry = self._get_reconfigure_entry()
        current = entry.data
        errors: dict[str, str] = {}
        if user_input is not None:
            port = await self.hass.async_add_executor_job(
                get_persistent_port_path, str(user_input[CONF_SERIAL_PORT])
            )
            try:
                baud = await validate_serial_port(
                    port, current.get(CONF_BAUD_RATE)
                )
            except (TimeoutError, OSError, ValueError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error probing ELK serial port")
                errors["base"] = "unknown"
            else:
                device_id = f"serial:{port}"
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_mismatch()
                raw_pin = user_input.get(CONF_PIN)
                pin = (
                    str(raw_pin).strip()
                    if raw_pin not in (None, "", 0, "0")
                    else ""
                )
                return self.async_update_and_abort(
                    entry,
                    unique_id=device_id,
                    data_updates={
                        CONF_CONNECTION_TYPE: CONNECTION_SERIAL,
                        CONF_SERIAL_PORT: port,
                        CONF_DEVICE_ID: device_id,
                        CONF_BAUD_RATE: baud,
                        CONF_PREFIX: str(user_input.get(CONF_PREFIX, "elkm1")),
                        CONF_PIN: pin,
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SERIAL_PORT,
                        default=str(current.get(CONF_SERIAL_PORT, "")),
                    ): selector.SerialPortSelector(),
                    vol.Optional(
                        CONF_PREFIX, default=current.get(CONF_PREFIX, "elkm1")
                    ): str,
                    vol.Optional(
                        CONF_PIN, default=current.get(CONF_PIN, "")
                    ): _PASSWORD_SELECTOR,
                }
            ),
            errors=errors,
        )


def _options_schema(default: int) -> vol.Schema:
    """Return the operational options schema."""
    return vol.Schema(
        {
            vol.Optional(CONF_POLL_INTERVAL, default=default): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
            )
        }
    )


class ElkOptionsFlowHandler(OptionsFlow):
    """Handle operational ELK options after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update fallback polling options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(
                self.config_entry.options.get(
                    CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                )
            ),
        )
