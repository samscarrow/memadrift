from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path | str) -> dict[str, str]:
    """Load key=value pairs from a .env file into os.environ.

    Skips comments, blank lines, and existing env vars.
    Strips surrounding quotes from values. Returns the loaded pairs.
    """
    path = Path(path)
    if not path.exists():
        return {}

    loaded: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # Don't override existing env vars
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded
