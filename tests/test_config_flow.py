"""Tests for configuration, identity, and reconfigure contracts.

Serial/USB is the only supported transport - network (M1XEP) connectivity,
including discovery, manual network entry, and reauth (nothing to
reauthenticate without credentials), was removed entirely 2026-09-05 as a
deliberate security posture. See docs/decisions.md.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.helpers import selector
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.elkm1.config_flow import get_persistent_port_path
from custom_components.elkm1.const import CONF_PIN, CONF_POLL_INTERVAL, DOMAIN


def _selector_for(schema, key) -> selector.TextSelector:
    return schema.schema[next(k for k in schema.schema if k == key)]


async def test_serial_form_masks_the_pin_field(hass):
    """A stored PIN must never render in the clear - see docs/decisions.md
    2026-09-05. The reconfigure form pre-fills the current value as this
    field's default, so an unmasked text box would show the real PIN on
    screen every time someone reopens Configure."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"

    field = _selector_for(result["data_schema"], CONF_PIN)
    assert isinstance(field, selector.TextSelector)
    assert field.config["type"] == selector.TextSelectorType.PASSWORD


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
        assert result["step_id"] == "user"
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
            result["flow_id"],
            {"serial_port": "/dev/ttyUSB9", "prefix": "", "pin": ""},
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


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
            result["flow_id"],
            {"serial_port": "/dev/ttyUSB0", "prefix": "", "pin": ""},
        )
    assert result["errors"] == {"base": "unknown"}


async def test_duplicate_serial_identity_is_rejected(hass, mock_serial_entry):
    """The same persistent serial port cannot be configured twice."""
    mock_serial_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.elkm1.config_flow.validate_serial_port",
            AsyncMock(return_value=115200),
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
            result["flow_id"],
            {
                "serial_port": mock_serial_entry.data["serial_port"],
                "prefix": "",
                "pin": "",
            },
        )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


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


async def test_reconfigure_serial_masks_the_pin_field_and_prefills_it(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "connection_type": "serial",
            "serial_port": "/dev/ttyUSB0",
            "device_id": "serial:/dev/ttyUSB0",
            "baud_rate": 115200,
            "prefix": "elkm1",
            "pin": "9876",
        },
        unique_id="serial:/dev/ttyUSB0",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)

    field = _selector_for(result["data_schema"], CONF_PIN)
    assert isinstance(field, selector.TextSelector)
    assert field.config["type"] == selector.TextSelectorType.PASSWORD
    assert result["data_schema"]({"serial_port": "x", "prefix": "y"})["pin"] == "9876"


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


async def test_options_flow_updates_fallback_poll(hass, mock_serial_entry):
    """Post-setup options remain supported."""
    mock_serial_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(
        mock_serial_entry.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 90}
    )
    assert result["type"] == "create_entry"
    assert mock_serial_entry.options[CONF_POLL_INTERVAL] == 90


async def test_multiple_serial_panels_have_isolated_identities(hass):
    """Multiple panels are supported when their persistent serial ports differ."""
    with (
        patch(
            "custom_components.elkm1.config_flow.validate_serial_port",
            AsyncMock(return_value=115200),
        ),
        patch(
            "custom_components.elkm1.config_flow.get_persistent_port_path",
            side_effect=lambda value: value,
        ),
        patch(
            "custom_components.elkm1.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        for port in ("/dev/ttyUSB0", "/dev/ttyUSB1"):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"serial_port": port, "prefix": "", "pin": ""},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_POLL_INTERVAL: 30}
            )
            assert result["type"] == "create_entry"

    entries = hass.config_entries.async_entries(DOMAIN)
    assert {entry.unique_id for entry in entries} == {
        "serial:/dev/ttyUSB0",
        "serial:/dev/ttyUSB1",
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
