from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from memadrift.models import MemoryItem, Source, Status
from memadrift.reality import DriftResult, DriftVerdict


class FixAction(Enum):
    AUTO_UPDATED = "auto_updated"
    MARKED_SUSPECT = "marked_suspect"
    NO_ACTION = "no_action"
    ALREADY_CORRECT = "already_correct"


@dataclass
class FixResult:
    item: MemoryItem
    action: FixAction
    old_value: str | None
    new_value: str | None
    detail: str


def apply_fix(
    item: MemoryItem,
    drift: DriftResult,
    today: date | None = None,
) -> FixResult:
    if today is None:
        today = date.today()

    if drift.verdict == DriftVerdict.MATCH:
        item.last_verified = today
        return FixResult(
            item=item,
            action=FixAction.ALREADY_CORRECT,
            old_value=None,
            new_value=None,
            detail="Value matches reality; refreshed last_verified",
        )

    if drift.verdict == DriftVerdict.UNVERIFIABLE:
        return FixResult(
            item=item,
            action=FixAction.NO_ACTION,
            old_value=None,
            new_value=None,
            detail=f"Cannot verify: {drift.evidence}",
        )

    # CONTRADICTION
    if item.src in (Source.TOOL, Source.INFERRED):
        old_value = item.value
        item.value = drift.actual
        item.last_verified = today
        item.status = Status.ACTIVE
        return FixResult(
            item=item,
            action=FixAction.AUTO_UPDATED,
            old_value=old_value,
            new_value=drift.actual,
            detail=f"Auto-updated from {old_value!r} to {drift.actual!r}",
        )

    # src == user or doc: mark suspect, don't change value
    item.status = Status.SUSPECT
    return FixResult(
        item=item,
        action=FixAction.MARKED_SUSPECT,
        old_value=item.value,
        new_value=None,
        detail=f"Marked suspect: expected {item.value!r}, reality is {drift.actual!r}",
    )
