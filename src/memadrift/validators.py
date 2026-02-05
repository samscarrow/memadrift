from __future__ import annotations

from pathlib import Path

from memadrift.parser import MemoryStore, Parser


def validate_ref(ref: str, base_dir: Path) -> list[str]:
    """Validate a ref pointer. Returns list of error strings (empty = valid)."""
    errors: list[str] = []
    if "#" in ref:
        file_part, anchor = ref.split("#", 1)
    else:
        file_part = ref
        anchor = None

    target_path = base_dir / file_part
    if not target_path.exists():
        errors.append(f"ref target file not found: {file_part}")
        return errors

    if anchor is not None:
        mf = Parser.read(target_path)
        found = any(
            item.id == anchor or item.key == anchor for item in mf.items
        )
        if not found:
            errors.append(f"ref anchor not found in {file_part}: {anchor}")

    return errors


def validate_cross_file_ids(store: MemoryStore) -> list[str]:
    """Check for duplicate IDs across all files in a store."""
    errors: list[str] = []
    seen: dict[str, str] = {}  # id -> file description
    for mf in store.all_files:
        label = str(mf.path) if mf.path else "<unknown>"
        for item in mf.items:
            if item.id in seen:
                errors.append(
                    f"Duplicate ID {item.id} in {label} (first seen in {seen[item.id]})"
                )
            else:
                seen[item.id] = label
    return errors
