"""Small URL/SSL utilities shared by the connection and transport modules."""

from __future__ import annotations

import ssl
from functools import cache

# The M1XEP does not support TLS version auto-negotiation; the caller must
# pick the version via the connection URL scheme.
TLS_VERSIONS = {
    "elks": ssl.TLSVersion.TLSv1,
    "elksv1_0": ssl.TLSVersion.TLSv1,
    "elksv1_2": ssl.TLSVersion.TLSv1_2,
    "elksv1_3": ssl.TLSVersion.TLSv1_3,
}


def url_scheme_is_secure(url: str) -> bool:
    """Whether this connection URL's scheme requires SSL/TLS (and login)."""
    scheme, _dest = url.split("://")
    return scheme.startswith("elks")


@cache
def ssl_context_for_scheme(scheme: str) -> ssl.SSLContext:
    """Build (and cache) an SSL context for one of the `elks*` schemes."""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if tls := TLS_VERSIONS.get(scheme):
        ssl_context.minimum_version = tls
        ssl_context.maximum_version = tls

    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    ssl_context.set_ciphers("DEFAULT:@SECLEVEL=0")
    ssl_context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    return ssl_context


def parse_url(url: str) -> tuple[str, str, int, ssl.SSLContext | None]:
    """Parse a connection URL into (scheme, host/port-target, port, ssl_context)."""
    scheme, dest = url.split("://")
    host = None
    ssl_context = None
    if scheme == "elk":
        host, port = dest.split(":") if ":" in dest else (dest, "2101")
    elif TLS_VERSIONS.get(scheme):
        host, port = dest.split(":") if ":" in dest else (dest, "2601")
        ssl_context = ssl_context_for_scheme(scheme)
        scheme = "elks"
    elif scheme == "serial":
        host, port = dest.split(":") if ":" in dest else (dest, "115200")
    else:
        raise ValueError(f"Invalid scheme '{scheme}'")
    return (scheme, host, int(port), ssl_context)
