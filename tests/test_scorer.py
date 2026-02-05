from datetime import date

import pytest

from memadrift.models import (
    Impact,
    MemoryItem,
    MemoryType,
    Scope,
    Source,
    Status,
    VerifyMode,
)
from memadrift.scorer import age_days, is_stale, priority, rank


def _make_item(**overrides) -> MemoryItem:
    defaults = dict(
        id="mem_ABCDEFGH",
        type=MemoryType.ENV,
        scope=Scope.parse("global"),
        key="env.editor",
        value="vim",
        src=Source.TOOL,
        status=Status.ACTIVE,
        last_verified=date(2025, 1, 1),
        ttl_days=30,
        verify_mode=VerifyMode.AUTO,
        impact=Impact.LOW,
    )
    defaults.update(overrides)
    return MemoryItem(**defaults)


TODAY = date(2025, 2, 1)


class TestAgeDays:
    def test_known_age(self):
        item = _make_item(last_verified=date(2025, 1, 1))
        assert age_days(item, today=TODAY) == 31

    def test_never_verified(self):
        item = _make_item(last_verified="never")
        assert age_days(item, today=TODAY) == 3650

    def test_verified_today(self):
        item = _make_item(last_verified=TODAY)
        assert age_days(item, today=TODAY) == 0


class TestIsStale:
    def test_stale(self):
        item = _make_item(last_verified=date(2025, 1, 1), ttl_days=30)
        assert is_stale(item, today=TODAY) is True

    def test_not_stale(self):
        item = _make_item(last_verified=date(2025, 1, 15), ttl_days=30)
        assert is_stale(item, today=TODAY) is False

    def test_ttl_zero_never_stale(self):
        item = _make_item(last_verified=date(2020, 1, 1), ttl_days=0)
        assert is_stale(item, today=TODAY) is False

    def test_never_verified_stale(self):
        item = _make_item(last_verified="never", ttl_days=30)
        assert is_stale(item, today=TODAY) is True


class TestPriority:
    def test_high_impact_higher_priority(self):
        low = _make_item(impact=Impact.LOW)
        high = _make_item(impact=Impact.HIGH)
        assert priority(high, today=TODAY) > priority(low, today=TODAY)

    def test_older_higher_priority(self):
        recent = _make_item(last_verified=date(2025, 1, 25))
        old = _make_item(last_verified=date(2024, 1, 1))
        assert priority(old, today=TODAY) > priority(recent, today=TODAY)

    def test_human_verify_lower_priority(self):
        auto = _make_item(verify_mode=VerifyMode.AUTO)
        human = _make_item(verify_mode=VerifyMode.HUMAN)
        assert priority(auto, today=TODAY) > priority(human, today=TODAY)


class TestRank:
    def test_ordering(self):
        items = [
            _make_item(id="mem_AAAAAAAA", impact=Impact.LOW, last_verified=date(2025, 1, 25)),
            _make_item(id="mem_BBBBBBBB", impact=Impact.HIGH, last_verified=date(2024, 1, 1)),
            _make_item(id="mem_CCCCCCCC", impact=Impact.MED, last_verified="never"),
        ]
        ranked = rank(items, today=TODAY)
        # HIGH impact + old should be first, MED + never second, LOW + recent last
        assert ranked[0].id == "mem_CCCCCCCC"  # MED * 3650 / 1.1
        assert ranked[1].id == "mem_BBBBBBBB"  # HIGH * 397 / 1.1
        assert ranked[2].id == "mem_AAAAAAAA"  # LOW * 7 / 1.1
