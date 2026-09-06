"""Small URL utility shared by the connection and transport modules."""

from __future__ import annotations


def parse_url(url: str) -> str:
    """Return the serial port path from a `serial://` connection URL."""
    scheme, dest = url.split("://")
    if scheme != "serial":
        raise ValueError(f"Invalid scheme '{scheme}'")
    return dest
