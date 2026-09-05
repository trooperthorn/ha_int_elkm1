"""ELK-M1 protocol implementation owned by this integration directly.

Replaces the third-party `elkm1-lib` dependency; see docs/decisions.md
(2026-09-05) for why, and docs/protocol.md / docs/protocol_coverage.md for
what was verified against the manufacturer's primary-source PDF and real
hardware while rewriting it.
"""

from __future__ import annotations

from .hub import Elk

__all__ = ["Elk"]
