from __future__ import annotations

from datetime import date

from memadrift.models import Impact, MemoryItem, VerifyMode

IMPACT_WEIGHTS: dict[Impact, float] = {
    Impact.LOW: 1.0,
    Impact.MED: 5.0,
    Impact.HIGH: 10.0,
}

VERIFY_COSTS: dict[VerifyMode, float] = {
    VerifyMode.AUTO: 0.1,
    VerifyMode.HUMAN: 100.0,
    VerifyMode.EXTERNAL: 50.0,
}

NEVER_VERIFIED_DAYS = 3650


def age_days(item: MemoryItem, today: date | None = None) -> int:
    if today is None:
        today = date.today()
    if isinstance(item.last_verified, str):
        return NEVER_VERIFIED_DAYS
    return (today - item.last_verified).days


def is_stale(item: MemoryItem, today: date | None = None) -> bool:
    if item.ttl_days == 0:
        return False
    return age_days(item, today) > item.ttl_days


def priority(item: MemoryItem, today: date | None = None) -> float:
    impact_w = IMPACT_WEIGHTS[item.impact]
    age = age_days(item, today)
    cost = VERIFY_COSTS[item.verify_mode]
    return (impact_w * age) / (1 + cost)


def rank(items: list[MemoryItem], today: date | None = None) -> list[MemoryItem]:
    return sorted(items, key=lambda it: priority(it, today), reverse=True)
