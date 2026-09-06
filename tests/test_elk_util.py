"""Unit tests for helpers/elk/util.py's serial URL helper.

Network/M1XEP connectivity (and its TLS handling) was removed entirely
2026-09-05 - see docs/decisions.md. This module now only ever sees a
`serial://` URL.
"""

from __future__ import annotations

import pytest

from custom_components.elkm1.helpers.elk.util import parse_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("serial://COM3", "COM3"),
        ("serial:///dev/ttyUSB0", "/dev/ttyUSB0"),
        ("serial:///dev/serial/by-id/usb-FTDI_FT232R-if00", "/dev/serial/by-id/usb-FTDI_FT232R-if00"),
    ],
)
def test_parse_url_returns_the_serial_port_path(url, expected):
    assert parse_url(url) == expected


def test_parse_url_rejects_a_non_serial_scheme():
    """Network schemes are gone entirely - any non-serial scheme is invalid."""
    with pytest.raises(ValueError, match="Invalid scheme"):
        parse_url("elk://1.2.3.4:2101")


def test_parse_url_rejects_an_unrecognized_scheme():
    with pytest.raises(ValueError, match="Invalid scheme"):
        parse_url("ftp://1.2.3.4")
