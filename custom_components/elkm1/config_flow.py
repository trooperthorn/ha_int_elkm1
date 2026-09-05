"""Config flow for Elk-M1 Control."""

from __future__ import annotations

import glob
import logging
import os
from typing import Any, Self, override
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_ADDRESS,
    CONF_DEVICE,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PREFIX,
    CONF_PROTOCOL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, selector
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.typing import DiscoveryInfoType, VolDictType
from homeassistant.util import slugify

from .const import (
    CONF_AUTO_CONFIGURE,
    CONF_BAUD_RATE,
    CONF_CONNECTION_TYPE,
    CONF_DEVICE_ID,
    CONF_MAC_ADDRESS,
    CONF_PIN,
    CONF_POLL_INTERVAL,
    CONF_SERIAL_PORT,
    CONNECTION_NETWORK,
    CONNECTION_SERIAL,
    DEFAULT_POLL_INTERVAL,
    DISCOVER_SCAN_TIMEOUT,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .discovery import (
    _short_mac,
    async_discover_device,
    async_discover_devices,
    async_update_entry_from_discovery,
)
from .helpers.elk.discovery import ElkSystem
from .helpers.transport import (
    ConnectionTimeoutError,
    InvalidAuthError,
    validate_network_connection,
    validate_serial_port,
)

NON_SECURE_PORT = 2101
SECURE_PORT = 2601
STANDARD_PORTS = {NON_SECURE_PORT, SECURE_PORT}

METHOD_NETWORK = "network"
METHOD_SERIAL = "serial"
MANUAL_NETWORK = "manual_network"

_LOGGER = logging.getLogger(__name__)

PROTOCOL_MAP = {
    "secure": "elks://",
    "TLS 1.2": "elksv1_2://",
    "non-secure": "elk://",
}
SECURE_PROTOCOLS = ["secure", "TLS 1.2"]
NETWORK_PROTOCOLS = [*SECURE_PROTOCOLS, "non-secure"]
DEFAULT_SECURE_PROTOCOL = "secure"
DEFAULT_NON_SECURE_PROTOCOL = "non-secure"
PORT_PROTOCOL_MAP = {
    NON_SECURE_PORT: DEFAULT_NON_SECURE_PROTOCOL,
    SECURE_PORT: DEFAULT_SECURE_PROTOCOL,
}
BASE_NETWORK_SCHEMA: VolDictType = {
    vol.Optional(CONF_USERNAME, default=""): str,
    vol.Optional(CONF_PASSWORD, default=""): str,
}


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


def _make_url_from_data(data: dict[str, Any]) -> str:
    """Build a canonical network URL from flow input."""
    if host := data.get(CONF_HOST):
        return str(host)
    protocol = PROTOCOL_MAP[data[CONF_PROTOCOL]]
    return f"{protocol}{data[CONF_ADDRESS]}"


def _address_from_discovery(device: ElkSystem) -> str:
    """Append a discovered port only when it is non-standard."""
    if device.port in STANDARD_PORTS:
        return device.ip_address
    return f"{device.ip_address}:{device.port}"


def _placeholders_from_device(device: ElkSystem) -> dict[str, str]:
    return {
        "mac_address": _short_mac(device.mac_address),
        "host": _address_from_discovery(device),
    }


def _protocol_from_url(url: str) -> str:
    """Return the flow protocol name represented by a canonical URL."""
    return next(
        (name for name, prefix in PROTOCOL_MAP.items() if url.startswith(prefix)),
        DEFAULT_SECURE_PROTOCOL,
    )


async def validate_input(data: dict[str, Any], mac: str | None) -> dict[str, str]:
    """Verify a live network panel and distinguish auth from transport failure."""
    userid = str(data.get(CONF_USERNAME, ""))
    password = str(data.get(CONF_PASSWORD, ""))
    prefix = str(data.get(CONF_PREFIX, ""))
    url = _make_url_from_data(data)

    if url.startswith(("elks://", "elksv1_2://")) and (not userid or not password):
        raise InvalidAuth
    try:
        await validate_network_connection(url, userid, password)
    except InvalidAuthError as exc:
        raise InvalidAuth from exc
    except (ConnectionTimeoutError, OSError) as exc:
        raise CannotConnect from exc

    short_mac = _short_mac(mac) if mac else None
    if prefix and prefix != short_mac:
        title = prefix
    elif mac:
        title = f"ElkM1 {short_mac}"
    else:
        title = "ElkM1"
    return {"title": title, CONF_HOST: url, CONF_PREFIX: slugify(prefix)}


class Elkm1ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Elk-M1 configuration and identity contract."""

    VERSION = 2
    MINOR_VERSION = 1

    host: str | None = None

    def __init__(self) -> None:
        self._discovered_device: ElkSystem | None = None
        self._discovered_devices: dict[str, ElkSystem] = {}
        self._pending_data: dict[str, Any] | None = None
        self._pending_title: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: ConfigEntry) -> ElkOptionsFlowHandler:
        """Return the operational options flow."""
        return ElkOptionsFlowHandler()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the transport before selecting a specific interface."""
        if user_input is not None:
            if user_input[CONF_CONNECTION_TYPE] == METHOD_SERIAL:
                return await self.async_step_serial()
            return await self.async_step_network()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONNECTION_TYPE): vol.In(
                        {
                            METHOD_NETWORK: "Network / M1XEP",
                            METHOD_SERIAL: "Direct Serial / USB",
                        }
                    )
                }
            ),
        )

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a discovered network panel or manual network entry."""
        if user_input is not None:
            selected = user_input[CONF_DEVICE]
            if selected == MANUAL_NETWORK:
                return await self.async_step_manual_connection()
            await self.async_set_unique_id(selected, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._discovered_device = self._discovered_devices[selected]
            return await self.async_step_discovered_connection()

        current_ids = self._async_current_ids(include_ignore=False)
        current_hosts = {
            hostname_from_url(str(entry.data.get(CONF_HOST, "")))
            for entry in self._async_current_entries(include_ignore=False)
        }
        devices = await async_discover_devices(self.hass, DISCOVER_SCAN_TIMEOUT)
        self._discovered_devices = {
            dr.format_mac(device.mac_address): device for device in devices
        }
        choices = {
            mac: f"{_short_mac(device.mac_address)} ({device.ip_address})"
            for mac, device in self._discovered_devices.items()
            if mac not in current_ids and device.ip_address not in current_hosts
        }
        choices[MANUAL_NETWORK] = "Manual Network Entry"
        return self.async_show_form(
            step_id="network",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): vol.In(choices)}),
        )

    @override
    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle DHCP discovery."""
        self._discovered_device = ElkSystem(
            discovery_info.macaddress, discovery_info.ip, 0
        )
        return await self._async_handle_discovery()

    @override
    async def async_step_integration_discovery(
        self, discovery_info: DiscoveryInfoType
    ) -> ConfigFlowResult:
        """Handle an upstream ELK library discovery."""
        self._discovered_device = ElkSystem(
            str(discovery_info["mac_address"]),
            str(discovery_info["ip_address"]),
            int(discovery_info["port"]),
        )
        return await self._async_handle_discovery()

    async def _async_handle_discovery(self) -> ConfigFlowResult:
        """Deduplicate and confirm an automatically discovered panel."""
        device = self._discovered_device
        assert device is not None
        mac = dr.format_mac(device.mac_address)
        self.host = device.ip_address
        await self.async_set_unique_id(mac)

        for entry in self._async_current_entries(include_ignore=False):
            if entry.unique_id == mac:
                if async_update_entry_from_discovery(self.hass, entry, device):
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_abort(reason="already_configured")
        if self.hass.config_entries.flow.async_has_matching_flow(self):
            return self.async_abort(reason="already_in_progress")
        self._abort_if_unique_id_configured()

        if not device.port:
            device = await async_discover_device(self.hass, device.ip_address)
            if device is None:
                return self.async_abort(reason="cannot_connect")
            self._discovered_device = device
        return await self.async_step_discovery_confirm()

    @override
    def is_matching(self, other_flow: Self) -> bool:
        """Return whether another discovery flow targets this host."""
        return other_flow.host == self.host

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered interface before verifying the panel."""
        device = self._discovered_device
        assert device is not None
        self.context["title_placeholders"] = _placeholders_from_device(device)
        if user_input is not None:
            return await self.async_step_discovered_connection()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders=_placeholders_from_device(device),
        )

    async def async_step_discovered_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify a discovered panel using the chosen ELK network scheme."""
        device = self._discovered_device
        assert device is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            values = dict(user_input)
            values[CONF_ADDRESS] = _address_from_discovery(device)
            values[CONF_PREFIX] = (
                _short_mac(device.mac_address) if self._async_current_entries() else ""
            )
            result = await self._async_prepare_network(values, device, errors)
            if result is not None:
                return result

        default_protocol = PORT_PROTOCOL_MAP.get(
            device.port, DEFAULT_SECURE_PROTOCOL
        )
        return self.async_show_form(
            step_id="discovered_connection",
            data_schema=vol.Schema(
                {
                    **BASE_NETWORK_SCHEMA,
                    vol.Required(
                        CONF_PROTOCOL, default=default_protocol
                    ): vol.In(NETWORK_PROTOCOLS),
                }
            ),
            errors=errors,
            description_placeholders=_placeholders_from_device(device),
        )

    async def async_step_manual_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify a manually entered network endpoint."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._async_prepare_network(user_input, None, errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="manual_connection",
            data_schema=vol.Schema(
                {
                    **BASE_NETWORK_SCHEMA,
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_PREFIX, default=""): str,
                    vol.Required(
                        CONF_PROTOCOL, default=DEFAULT_SECURE_PROTOCOL
                    ): vol.In(NETWORK_PROTOCOLS),
                }
            ),
            errors=errors,
        )

    async def _async_prepare_network(
        self,
        user_input: dict[str, Any],
        discovered_device: ElkSystem | None,
        errors: dict[str, str],
    ) -> ConfigFlowResult | None:
        """Verify network transport and stage a canonical, identified entry."""
        endpoint = _make_url_from_data(user_input)
        if self._url_already_configured(endpoint):
            return self.async_abort(reason="address_already_configured")

        device = discovered_device
        if device is None:
            host = hostname_from_url(endpoint)
            try:
                device = await async_discover_device(self.hass, host)
            except OSError as err:
                _LOGGER.debug("Directed ELK discovery of %s failed: %s", host, err)

        formatted_mac = dr.format_mac(device.mac_address) if device else None
        if formatted_mac:
            await self.async_set_unique_id(formatted_mac, raise_on_progress=False)
            self._abort_if_unique_id_configured()

        try:
            info = await validate_input(user_input, formatted_mac)
        except CannotConnect:
            errors["base"] = "cannot_connect"
            return None
        except InvalidAuth:
            errors[CONF_PASSWORD] = "invalid_auth"
            return None
        except Exception:
            _LOGGER.exception("Unexpected error verifying ELK network connection")
            errors["base"] = "unknown"
            return None

        self._pending_title = info["title"]
        self._pending_data = {
            CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
            CONF_HOST: info[CONF_HOST],
            CONF_USERNAME: str(user_input.get(CONF_USERNAME, "")),
            CONF_PASSWORD: str(user_input.get(CONF_PASSWORD, "")),
            CONF_AUTO_CONFIGURE: True,
            CONF_PREFIX: info[CONF_PREFIX],
        }
        if formatted_mac:
            self._pending_data[CONF_MAC_ADDRESS] = formatted_mac
        return await self.async_step_elkm1_options()

    async def async_step_serial(
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
            step_id="serial",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERIAL_PORT): selector.SerialPortSelector(),
                    vol.Optional(CONF_PREFIX, default="elkm1"): str,
                    vol.Optional(CONF_PIN, default=""): str,
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

    def _url_already_configured(self, url: str) -> bool:
        """Return whether another entry owns the same network hostname."""
        host = hostname_from_url(url)
        return any(
            hostname_from_url(str(entry.data.get(CONF_HOST, ""))) == host
            for entry in self._async_current_entries()
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure an entry while enforcing stable panel identity."""
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_SERIAL:
            return await self.async_step_reconfigure_serial(user_input)

        errors: dict[str, str] = {}
        current = entry.data
        if user_input is not None:
            endpoint = _make_url_from_data(user_input)
            device: ElkSystem | None = None
            formatted_mac: str | None
            try:
                device = await async_discover_device(
                    self.hass, hostname_from_url(endpoint)
                )
                info = await validate_input(user_input, entry.unique_id)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors[CONF_PASSWORD] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected error during ELK reconfiguration")
                errors["base"] = "unknown"
            else:
                if device is not None:
                    formatted_mac = dr.format_mac(device.mac_address)
                    await self.async_set_unique_id(formatted_mac)
                    self._abort_if_unique_id_mismatch()
                else:
                    await self.async_set_unique_id(entry.unique_id)
                    formatted_mac = str(current.get(CONF_MAC_ADDRESS, "")) or None
                return self.async_update_and_abort(
                    entry,
                    unique_id=self.unique_id,
                    data_updates={
                        CONF_CONNECTION_TYPE: CONNECTION_NETWORK,
                        CONF_HOST: info[CONF_HOST],
                        CONF_USERNAME: str(user_input.get(CONF_USERNAME, "")),
                        CONF_PASSWORD: str(user_input.get(CONF_PASSWORD, "")),
                        CONF_MAC_ADDRESS: formatted_mac,
                    },
                )

        current_url = str(current.get(CONF_HOST, ""))
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ADDRESS, default=hostname_from_url(current_url)
                    ): str,
                    vol.Optional(
                        CONF_USERNAME, default=current.get(CONF_USERNAME, "")
                    ): str,
                    vol.Optional(CONF_PASSWORD, default=""): str,
                    vol.Required(
                        CONF_PROTOCOL, default=_protocol_from_url(current_url)
                    ): vol.In(NETWORK_PROTOCOLS),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_serial(
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
            step_id="reconfigure_serial",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SERIAL_PORT,
                        default=str(current.get(CONF_SERIAL_PORT, "")),
                    ): selector.SerialPortSelector(),
                    vol.Optional(
                        CONF_PREFIX, default=current.get(CONF_PREFIX, "elkm1")
                    ): str,
                    vol.Optional(CONF_PIN, default=current.get(CONF_PIN, "")): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, _entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start credential replacement after a rejected ELK login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify and store replacement network credentials."""
        entry = self._get_reauth_entry()
        if entry.data.get(CONF_CONNECTION_TYPE) == CONNECTION_SERIAL:
            return self.async_abort(reason="reauth_unsupported")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_network_connection(
                    str(entry.data[CONF_HOST]),
                    str(user_input[CONF_USERNAME]),
                    str(user_input[CONF_PASSWORD]),
                )
            except InvalidAuthError:
                errors[CONF_PASSWORD] = "invalid_auth"
            except (ConnectionTimeoutError, OSError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during ELK reauthentication")
                errors["base"] = "unknown"
            else:
                return self.async_update_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: str(user_input[CONF_USERNAME]),
                        CONF_PASSWORD: str(user_input[CONF_PASSWORD]),
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "host": hostname_from_url(str(entry.data.get(CONF_HOST, "")))
            },
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


class CannotConnect(HomeAssistantError):
    """The ELK transport did not produce a valid panel response."""


class InvalidAuth(HomeAssistantError):
    """The M1XEP rejected the supplied credentials."""
