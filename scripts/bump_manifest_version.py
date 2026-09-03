#!/usr/bin/env python3
"""Write a new version into custom_components/elkm1/manifest.json in place.

Used only by .github/workflows/release.yml, which computes the next
calendar version (YYYY.MM.DD.N) and calls this script to make manifest.json
match the commit it is about to tag - manifest.json's "version" field is
never edited by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MANIFEST_PATH = Path("custom_components/elkm1/manifest.json")


def bump(version: str) -> None:
    """Set manifest.json's "version" field to `version`, preserving formatting."""
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    data["version"] = version
    MANIFEST_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <new-version>")
    bump(sys.argv[1])
