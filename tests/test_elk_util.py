"""Unit tests for helpers/elk/util.py's URL/SSL helpers. Closes a gap left
by the 2026-09-05 elkm1-lib removal (see docs/decisions.md).
"""

from __future__ import annotations

import ssl

import pytest

from custom_components.elkm1.helpers.elk.util import (
    parse_url,
    ssl_context_for_scheme,
    url_scheme_is_secure,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("elk://1.2.3.4:2101", False),
        ("serial://COM3:115200", False),
        ("elks://1.2.3.4:2601", True),
        ("elksv1_0://1.2.3.4:2601", True),
        ("elksv1_2://1.2.3.4:2601", True),
        ("elksv1_3://1.2.3.4:2601", True),
    ],
)
def test_url_scheme_is_secure(url, expected):
    assert url_scheme_is_secure(url) is expected


@pytest.mark.parametrize(
    ("scheme", "expected_version"),
    [
        ("elks", ssl.TLSVersion.TLSv1),
        ("elksv1_0", ssl.TLSVersion.TLSv1),
        ("elksv1_2", ssl.TLSVersion.TLSv1_2),
        ("elksv1_3", ssl.TLSVersion.TLSv1_3),
    ],
)
def test_ssl_context_for_scheme_pins_the_documented_tls_version(scheme, expected_version):
    """The M1XEP does not support TLS version auto-negotiation - see this
    module's own comment on `TLS_VERSIONS`."""
    ssl_context_for_scheme.cache_clear()
    context = ssl_context_for_scheme(scheme)
    assert context.minimum_version == expected_version
    assert context.maximum_version == expected_version


def test_ssl_context_for_scheme_disables_hostname_and_cert_verification():
    """The M1XEP's self-signed certificate cannot be verified against a real
    CA or hostname - this is a deliberate, documented compatibility choice,
    not an oversight."""
    ssl_context_for_scheme.cache_clear()
    context = ssl_context_for_scheme("elks")
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_ssl_context_for_scheme_is_cached_per_scheme():
    ssl_context_for_scheme.cache_clear()
    first = ssl_context_for_scheme("elks")
    second = ssl_context_for_scheme("elks")
    assert first is second


def test_ssl_context_for_scheme_tolerates_an_unknown_scheme():
    """`parse_url` only ever calls this for a scheme already confirmed to be
    in `TLS_VERSIONS`, but the function itself must not crash if asked for
    one that isn't - it just leaves min/max version at their SSL defaults."""
    ssl_context_for_scheme.cache_clear()
    context = ssl_context_for_scheme("unknown-scheme")
    assert context.check_hostname is False


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("elk://1.2.3.4:2101", ("elk", "1.2.3.4", 2101, None)),
        ("elk://1.2.3.4", ("elk", "1.2.3.4", 2101, None)),
        ("serial://COM3:9600", ("serial", "COM3", 9600, None)),
        ("serial://COM3", ("serial", "COM3", 115200, None)),
    ],
)
def test_parse_url_non_secure_schemes(url, expected):
    scheme, host, port, ssl_context = parse_url(url)
    assert (scheme, host, port, ssl_context) == expected


@pytest.mark.parametrize(
    ("url", "expected_host", "expected_port"),
    [
        ("elks://1.2.3.4:2601", "1.2.3.4", 2601),
        ("elks://1.2.3.4", "1.2.3.4", 2601),
        ("elksv1_2://1.2.3.4:2601", "1.2.3.4", 2601),
    ],
)
def test_parse_url_secure_schemes_build_an_ssl_context_and_normalize_the_scheme(
    url, expected_host, expected_port
):
    """Every `elks*` variant normalizes to plain "elks" in the returned
    tuple - the specific TLS version only affects which `ssl.SSLContext` is
    built, not the scheme label callers see."""
    scheme, host, port, ssl_context = parse_url(url)
    assert scheme == "elks"
    assert host == expected_host
    assert port == expected_port
    assert isinstance(ssl_context, ssl.SSLContext)


def test_parse_url_rejects_an_unrecognized_scheme():
    with pytest.raises(ValueError, match="Invalid scheme"):
        parse_url("ftp://1.2.3.4")
