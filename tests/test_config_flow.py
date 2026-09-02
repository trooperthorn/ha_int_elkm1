"""Tests for configuration, identity, reconfigure, and reauth contracts."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from elkm1_lib.discovery import ElkSystem
from homeassistant import config_entries
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from custom_components.elkm1.const import CONF_POLL_INTERVAL, DOMAIN
from custom_components.elkm1.helpers.transport import (
    ConnectionTimeoutError,
    InvalidAuthError,
)

MAC = "aa:bb:cc:dd:ee:ff"
DEVICE = ElkSystem(MAC, "1.2.3.4", 2601)


async def _start_manual_network(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"connection_type": "network"}
    )
    assert result["step_id"] == "network"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "manual_network"}
    )
    assert result["step_id"] == "manual_connection"
    return result


async def test_manual_network_verify_options_complete(hass):
    """Manual network setup verifies, collects options, and owns canonical data."""
    with (
        patch(
            "custom_components.elkm1.config_flow.async_discover_devices",
            AsyncMock(return_value=[]),
        ),
        patch(
            "custom_components.elkm1.config_flow.async_discover_device",
            AsyncMock(return_value=DEVICE),
        ),
        patch(
            "custom_components.elkm1.config_flow.validate_network_connection",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.elkm1.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await _start_manual_network(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "address": "1.2.3.4",
                "username": "admin",
                "password": "secret",
                "prefix": "",
                "protocol": "secure",
            },
        )
        assert result["step_id"] == "elkm1_options"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POLL_INTERVAL: 45}
        )

    assert result["type"] == "create_entry"
    assert result["data"]["connection_type"] == "network"
    assert result["data"]["host"] == "elks://1.2.3.4"
    assert result["data"]["mac_address"] == MAC
    assert result["options"] == {CONF_POLL_INTERVAL: 45}
    assert result["result"].unique_id == MAC


@pytest.mark.parametrize(
    ("exception", "error_key", "error_value"),
    [
        (ConnectionTimeoutError("timeout"), "base", "cannot_connect"),
        (InvalidAuthError("rejected"), "password", "invalid_auth"),
    ],
)
async def test_manual_network_errors(
    hass, exception, error_key: str, error_value: str
):
    """Transport timeout and credential rejection remain distinguishable."""
    with (
        patch(
            "custom_components.elkm1.config_flow.async_discover_devices",
            AsyncMock(return_value=[]),
        ),
        patch(
            "custom_components.elkm1.config_flow.async_discover_device",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.elkm1.config_flow.validate_network_connection",
            AsyncMock(side_effect=exception),
        ),
    ):
        result = await _start_manual_network(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "address": "1.2.3.4",
                "username": "admin",
                "password": "bad",
                "prefix": "",
                "protocol": "secure",
            },
        )
    assert result["type"] == "form"
    assert result["errors"][error_key] == error_value


async def test_serial_probes_only_selected_port_and_caches_baud(hass):
    """Serial setup probes the submitted selector value and stores its baud."""
    validate = AsyncMock(return_value=57600)
    with (
        patch(
            "custom_components.elkm1.config_flow.validate_serial_port", validate
        ),
        patch(
            "custom_components.elkm1.config_flow.get_persistent_port_path",
            side_effect=lambda value: f"/dev/serial/by-id/{value.rsplit('/', 1)[-1]}",
        ),
        patch(
            "custom_components.elkm1.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"connection_type": "serial"}
        )
        assert result["step_id"] == "serial"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "serial_port": "/dev/ttyUSB0",
                "prefix": "panel",
                "pin": "1234",
            },
        )
        assert result["step_id"] == "elkm1_options"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POLL_INTERVAL: 60}
        )

    validate.assert_awaited_once_with("/dev/serial/by-id/ttyUSB0")
    assert result["data"]["serial_port"] == "/dev/serial/by-id/ttyUSB0"
    assert result["data"]["baud_rate"] == 57600
    assert result["result"].unique_id == "serial:/dev/serial/by-id/ttyUSB0"


async def test_serial_probe_failure_does_not_create_entry(hass):
    """A non-ELK selected serial endpoint stays on the serial form."""
    with (
        patch(
            "custom_components.elkm1.config_flow.validate_serial_port",
            AsyncMock(side_effect=OSError("not an Elk")),
        ),
        patch(
            "custom_components.elkm1.config_flow.get_persistent_port_path",
            side_effect=lambda value: value,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"connection_type": "serial"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"serial_port": "/dev/ttyUSB9", "prefix": "", "pin": ""},
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_dhcp_uses_directed_discovery_then_confirmation(hass):
    """DHCP identity is completed with the upstream directed discovery."""
    directed = AsyncMock(return_value=DEVICE)
    with patch(
        "custom_components.elkm1.config_flow.async_discover_device", directed
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo("1.2.3.4", "", "aabbccddeeff"),
        )
    assert result["type"] == "form"
    assert result["step_id"] == "discovery_confirm"
    directed.assert_awaited_once_with(hass, "1.2.3.4")


async def test_duplicate_network_identity_is_rejected(hass, mock_network_entry):
    """The formatted panel MAC, not merely an address, prevents duplicates."""
    mock_network_entry.add_to_hass(hass)
    with patch(
        "custom_components.elkm1.config_flow.async_discover_devices",
        AsyncMock(return_value=[DEVICE]),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"connection_type": "network"}
        )
    choices = result["data_schema"].schema[
        next(iter(result["data_schema"].schema))
    ].container
    assert MAC not in choices


async def test_reconfigure_network_rejects_different_panel(
    hass, mock_network_entry
):
    """Network reconfigure aborts when directed discovery returns another MAC."""
    mock_network_entry.add_to_hass(hass)
    different = ElkSystem("11:22:33:44:55:66", "5.6.7.8", 2601)
    with (
        patch(
            "custom_components.elkm1.config_flow.async_discover_device",
            AsyncMock(return_value=different),
        ),
        patch(
            "custom_components.elkm1.config_flow.validate_network_connection",
            AsyncMock(return_value=None),
        ),
    ):
        result = await mock_network_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "address": "5.6.7.8",
                "username": "new",
                "password": "secret",
                "protocol": "secure",
            },
        )
    assert result["type"] == "abort"
    assert result["reason"] == "unique_id_mismatch"


async def test_reconfigure_serial_updates_same_persistent_adapter(
    hass, mock_serial_entry
):
    """Serial reconfigure verifies and updates the same stable adapter identity."""
    mock_serial_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.elkm1.config_flow.validate_serial_port",
            AsyncMock(return_value=38400),
        ),
        patch(
            "custom_components.elkm1.config_flow.get_persistent_port_path",
            side_effect=lambda value: value,
        ),
    ):
        result = await mock_serial_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "serial_port": "/dev/ttyUSB0",
                "prefix": "elkm1",
                "pin": "",
            },
        )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert mock_serial_entry.data["baud_rate"] == 38400


async def test_reauth_updates_credentials(hass, mock_network_entry):
    """Accepted credentials update the entry and rely on its reload listener."""
    mock_network_entry.add_to_hass(hass)
    with patch(
        "custom_components.elkm1.config_flow.validate_network_connection",
        AsyncMock(return_value=None),
    ):
        result = await mock_network_entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "replacement", "password": "replacement-secret"},
        )
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert mock_network_entry.data["username"] == "replacement"


async def test_options_flow_updates_fallback_poll(hass, mock_network_entry):
    """Post-setup options remain supported."""
    mock_network_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(
        mock_network_entry.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 90}
    )
    assert result["type"] == "create_entry"
    assert mock_network_entry.options[CONF_POLL_INTERVAL] == 90


async def test_multiple_panels_have_isolated_identities(hass):
    """Multiple panels are supported when their formatted MACs differ."""
    first = ElkSystem("aa:bb:cc:dd:ee:01", "1.2.3.1", 2601)
    second = ElkSystem("aa:bb:cc:dd:ee:02", "1.2.3.2", 2601)
    with (
        patch(
            "custom_components.elkm1.config_flow.async_discover_devices",
            AsyncMock(return_value=[first, second]),
        ),
        patch(
            "custom_components.elkm1.config_flow.validate_network_connection",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.elkm1.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        for device in (first, second):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"connection_type": "network"}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"device": device.mac_address}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "username": "admin",
                    "password": "secret",
                    "protocol": "secure",
                },
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_POLL_INTERVAL: 30}
            )
            assert result["type"] == "create_entry"

    entries = hass.config_entries.async_entries(DOMAIN)
    assert {entry.unique_id for entry in entries} == {
        first.mac_address,
        second.mac_address,
    }
