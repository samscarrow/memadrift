from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def read_queue(path: Path | str) -> list[dict]:
    """Read the pending verification queue from a JSON file."""
    path = Path(path)
    if not path.exists():
        return []
    text = path.read_text().strip()
    if not text:
        return []
    return json.loads(text)


def write_queue(entries: list[dict], path: Path | str) -> None:
    """Write the pending verification queue to a JSON file."""
    path = Path(path)
    path.write_text(json.dumps(entries, indent=2) + "\n")


def add_to_queue(
    item_id: str,
    key: str,
    current_value: str,
    verify_mode: str,
    source_file: str,
    evidence: str,
    path: Path | str,
) -> None:
    """Add an item to the pending queue. Deduplicates by item_id."""
    entries = read_queue(path)
    # Deduplicate
    if any(e["item_id"] == item_id for e in entries):
        return
    entries.append({
        "item_id": item_id,
        "key": key,
        "current_value": current_value,
        "verify_mode": verify_mode,
        "source_file": source_file,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "evidence": evidence,
    })
    write_queue(entries, path)


def remove_from_queue(item_id: str, path: Path | str) -> bool:
    """Remove an item from the queue. Returns True if found and removed."""
    entries = read_queue(path)
    new_entries = [e for e in entries if e["item_id"] != item_id]
    if len(new_entries) == len(entries):
        return False
    write_queue(new_entries, path)
    return True
