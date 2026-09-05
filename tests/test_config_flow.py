"""Tests for configuration, identity, reconfigure, and reauth contracts."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import (
    CONF_ADDRESS,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PREFIX,
    CONF_PROTOCOL,
    CONF_USERNAME,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from custom_components.elkm1.config_flow import (
    CannotConnect,
    Elkm1ConfigFlow,
    InvalidAuth,
    _address_from_discovery,
    _make_url_from_data,
    get_persistent_port_path,
    validate_input,
)
from custom_components.elkm1.const import CONF_POLL_INTERVAL, DOMAIN
from custom_components.elkm1.helpers.elk.discovery import ElkSystem
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


def test_get_persistent_port_path_returns_original_on_realpath_error():
    with patch(
        "custom_components.elkm1.config_flow.os.path.realpath", side_effect=OSError
    ):
        assert get_persistent_port_path("/dev/ttyUSB0") == "/dev/ttyUSB0"


def test_get_persistent_port_path_prefers_by_id_symlink():
    def fake_realpath(path):
        if path in ("/dev/ttyUSB0", "/dev/serial/by-id/elk-panel"):
            return "/dev/ttyUSB0"
        raise OSError

    with (
        patch(
            "custom_components.elkm1.config_flow.os.path.realpath",
            side_effect=fake_realpath,
        ),
        patch(
            "custom_components.elkm1.config_flow.glob.glob",
            side_effect=lambda pattern: (
                ["/dev/serial/by-id/elk-panel"] if "by-id" in pattern else []
            ),
        ),
    ):
        assert (
            get_persistent_port_path("/dev/ttyUSB0")
            == "/dev/serial/by-id/elk-panel"
        )


def test_get_persistent_port_path_skips_symlink_realpath_error():
    def fake_realpath(path):
        if path == "/dev/ttyUSB0":
            return "/dev/ttyUSB0"
        raise OSError

    with (
        patch(
            "custom_components.elkm1.config_flow.os.path.realpath",
            side_effect=fake_realpath,
        ),
        patch(
            "custom_components.elkm1.config_flow.glob.glob",
            side_effect=lambda pattern: (
                ["/dev/serial/by-id/broken"] if "by-id" in pattern else []
            ),
        ),
    ):
        assert get_persistent_port_path("/dev/ttyUSB0") == "/dev/ttyUSB0"


def test_make_url_from_data_prefers_explicit_host():
    assert _make_url_from_data({CONF_HOST: "elk://5.6.7.8"}) == "elk://5.6.7.8"


def test_address_from_discovery_appends_nonstandard_port():
    device = ElkSystem(MAC, "1.2.3.4", 4370)
    assert _address_from_discovery(device) == "1.2.3.4:4370"


async def test_validate_input_requires_credentials_for_secure_protocol():
    with pytest.raises(InvalidAuth):
        await validate_input(
            {CONF_PROTOCOL: "secure", CONF_ADDRESS: "1.2.3.4"}, None
        )


async def test_validate_input_prefers_explicit_prefix_as_title():
    with patch(
        "custom_components.elkm1.config_flow.validate_network_connection",
        AsyncMock(return_value=None),
    ):
        info = await validate_input(
            {
                CONF_HOST: "elk://1.2.3.4",
                CONF_USERNAME: "admin",
                CONF_PASSWORD: "secret",
                CONF_PREFIX: "vacation-home",
            },
            MAC,
        )
    assert info["title"] == "vacation-home"


async def test_validate_input_defaults_title_without_mac():
    with patch(
        "custom_components.elkm1.config_flow.validate_network_connection",
        AsyncMock(return_value=None),
    ):
        info = await validate_input({CONF_HOST: "elk://1.2.3.4"}, None)
    assert info["title"] == "ElkM1"


async def test_integration_discovery_uses_upstream_payload_then_confirmation(hass):
    """The upstream ELK library payload is accepted directly, port and all."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY},
        data={"mac_address": MAC, "ip_address": "1.2.3.4", "port": 2601},
    )
    assert result["type"] == "form"
    assert result["step_id"] == "discovery_confirm"


async def test_discovery_updates_existing_entry_and_schedules_reload(
    hass, mock_network_entry
):
    mock_network_entry.add_to_hass(hass)
    reload = MagicMock()
    with (
        patch(
            "custom_components.elkm1.config_flow.async_update_entry_from_discovery",
            return_value=True,
        ),
        patch.object(hass.config_entries, "async_schedule_reload", reload),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo("1.2.3.4", "", MAC.replace(":", "")),
        )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    reload.assert_called_once_with(mock_network_entry.entry_id)


async def test_discovery_aborts_when_matching_flow_in_progress(hass):
    with patch.object(
        hass.config_entries.flow, "async_has_matching_flow", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo("9.9.9.9", "", "aabbccddeeaa"),
        )
    assert result["type"] == "abort"
    assert result["reason"] == "already_in_progress"


async def test_discovery_aborts_when_directed_discovery_finds_nothing(hass):
    """A DHCP hint without a port that fails directed discovery cannot proceed."""
    with patch(
        "custom_components.elkm1.config_flow.async_discover_device",
        AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo("9.9.9.9", "", "aabbccddeebb"),
        )
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


def test_is_matching_compares_discovered_host():
    flow = Elkm1ConfigFlow()
    flow.host = "1.2.3.4"
    other = Elkm1ConfigFlow()
    other.host = "1.2.3.4"
    assert flow.is_matching(other) is True
    other.host = "5.6.7.8"
    assert flow.is_matching(other) is False


async def test_discovery_confirm_proceeds_to_discovered_connection(hass):
    with patch(
        "custom_components.elkm1.config_flow.async_discover_device",
        AsyncMock(return_value=DEVICE),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo(DEVICE.ip_address, "", MAC.replace(":", "")),
        )
        assert result["step_id"] == "discovery_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {}
        )
    assert result["step_id"] == "discovered_connection"


async def test_manual_network_aborts_when_address_already_configured(
    hass, mock_network_entry
):
    mock_network_entry.add_to_hass(hass)
    with patch(
        "custom_components.elkm1.config_flow.async_discover_devices",
        AsyncMock(return_value=[]),
    ):
        result = await _start_manual_network(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "address": "1.2.3.4",
                "username": "",
                "password": "",
                "prefix": "",
                "protocol": "non-secure",
            },
        )
    assert result["type"] == "abort"
    assert result["reason"] == "address_already_configured"


async def test_manual_network_continues_when_directed_discovery_errors(hass):
    """A discovery-socket OSError is logged and does not abort the flow."""
    with (
        patch(
            "custom_components.elkm1.config_flow.async_discover_devices",
            AsyncMock(return_value=[]),
        ),
        patch(
            "custom_components.elkm1.config_flow.async_discover_device",
            AsyncMock(side_effect=OSError("network unreachable")),
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


async def test_manual_network_unexpected_error_is_reported_as_unknown(hass):
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
            AsyncMock(side_effect=RuntimeError("boom")),
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
    assert result["errors"] == {"base": "unknown"}


async def test_serial_unexpected_error_is_reported_as_unknown(hass):
    with (
        patch(
            "custom_components.elkm1.config_flow.validate_serial_port",
            AsyncMock(side_effect=RuntimeError("boom")),
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
            {"serial_port": "/dev/ttyUSB0", "prefix": "", "pin": ""},
        )
    assert result["errors"] == {"base": "unknown"}


@pytest.mark.parametrize(
    ("exception", "error_key", "error_value"),
    [
        (CannotConnect(), "base", "cannot_connect"),
        (InvalidAuth(), "password", "invalid_auth"),
    ],
)
async def test_reconfigure_network_errors(
    hass, mock_network_entry, exception, error_key: str, error_value: str
):
    mock_network_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.elkm1.config_flow.async_discover_device",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.elkm1.config_flow.validate_input",
            AsyncMock(side_effect=exception),
        ),
    ):
        result = await mock_network_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "address": "1.2.3.4",
                "username": "admin",
                "password": "bad",
                "protocol": "secure",
            },
        )
    assert result["type"] == "form"
    assert result["errors"][error_key] == error_value


async def test_reconfigure_network_unexpected_error_is_reported_as_unknown(
    hass, mock_network_entry
):
    mock_network_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.elkm1.config_flow.async_discover_device",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.elkm1.config_flow.validate_input",
            AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        result = await mock_network_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "address": "1.2.3.4",
                "username": "admin",
                "password": "bad",
                "protocol": "secure",
            },
        )
    assert result["errors"] == {"base": "unknown"}


async def test_reconfigure_network_keeps_identity_when_undiscovered(
    hass, mock_network_entry
):
    """Reconfigure succeeds using the entry's existing identity when directed discovery finds nothing."""
    mock_network_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.elkm1.config_flow.async_discover_device",
            AsyncMock(return_value=None),
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
                "address": "1.2.3.4",
                "username": "admin",
                "password": "secret",
                "protocol": "secure",
            },
        )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert mock_network_entry.data["mac_address"] == MAC
    assert mock_network_entry.unique_id == MAC


async def test_reconfigure_serial_unexpected_error_is_reported_as_unknown(
    hass, mock_serial_entry
):
    mock_serial_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.elkm1.config_flow.validate_serial_port",
            AsyncMock(side_effect=RuntimeError("boom")),
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
    assert result["errors"] == {"base": "unknown"}


async def test_reconfigure_serial_probe_failure_stays_on_form(
    hass, mock_serial_entry
):
    mock_serial_entry.add_to_hass(hass)
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
        result = await mock_serial_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "serial_port": "/dev/ttyUSB0",
                "prefix": "elkm1",
                "pin": "",
            },
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize(
    ("exception", "error_key", "error_value"),
    [
        (InvalidAuthError("rejected"), "password", "invalid_auth"),
        (ConnectionTimeoutError("timeout"), "base", "cannot_connect"),
    ],
)
async def test_reauth_errors(
    hass, mock_network_entry, exception, error_key: str, error_value: str
):
    mock_network_entry.add_to_hass(hass)
    with patch(
        "custom_components.elkm1.config_flow.validate_network_connection",
        AsyncMock(side_effect=exception),
    ):
        result = await mock_network_entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "replacement", "password": "replacement-secret"},
        )
    assert result["type"] == "form"
    assert result["errors"][error_key] == error_value


async def test_reauth_serial_entry_is_unsupported(hass, mock_serial_entry):
    mock_serial_entry.add_to_hass(hass)
    result = await mock_serial_entry.start_reauth_flow(hass)
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_unsupported"


async def test_reauth_unexpected_error_is_reported_as_unknown(
    hass, mock_network_entry
):
    mock_network_entry.add_to_hass(hass)
    with patch(
        "custom_components.elkm1.config_flow.validate_network_connection",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await mock_network_entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "replacement", "password": "replacement-secret"},
        )
    assert result["errors"] == {"base": "unknown"}
