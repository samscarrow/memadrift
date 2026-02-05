from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from memadrift.fixer import FixResult


def format_entry(result: FixResult, memory_file: str) -> dict:
    """Convert FixResult to a flat dict for JSON serialization."""
    item = result.item
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "item_id": item.id,
        "key": item.key,
        "action": result.action.value,
        "old_value": result.old_value,
        "new_value": result.new_value,
        "detail": result.detail,
        "src": item.src.value,
        "scope": str(item.scope),
        "type": item.type.value,
        "memory_file": memory_file,
    }


def write_entries(results: list[FixResult], audit_path: Path, memory_file: str) -> int:
    """Append JSON-lines entries. Returns count written."""
    if not results:
        return 0
    lines = [
        json.dumps(format_entry(r, memory_file), separators=(",", ":"))
        for r in results
    ]
    with open(audit_path, "a") as f:
        f.write("\n".join(lines) + "\n")
    return len(lines)
