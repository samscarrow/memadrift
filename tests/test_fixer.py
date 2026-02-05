from datetime import date

import pytest

from memadrift.fixer import FixAction, apply_fix
from memadrift.models import (
    Impact,
    MemoryItem,
    MemoryType,
    Scope,
    Source,
    Status,
    VerifyMode,
)
from memadrift.reality import DriftResult, DriftVerdict

TODAY = date(2025, 2, 1)


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


class TestFixerMatch:
    def test_match_refreshes_timestamp(self):
        item = _make_item(last_verified=date(2025, 1, 1))
        drift = DriftResult(
            verdict=DriftVerdict.MATCH,
            expected="vim",
            actual="vim",
            evidence="$EDITOR == 'vim'",
        )
        result = apply_fix(item, drift, today=TODAY)
        assert result.action == FixAction.ALREADY_CORRECT
        assert item.last_verified == TODAY


class TestFixerContradictionToolSource:
    def test_auto_fix(self):
        item = _make_item(src=Source.TOOL, value="vim")
        drift = DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected="vim",
            actual="nvim",
            evidence="$EDITOR: expected 'vim', got 'nvim'",
        )
        result = apply_fix(item, drift, today=TODAY)
        assert result.action == FixAction.AUTO_UPDATED
        assert result.old_value == "vim"
        assert result.new_value == "nvim"
        assert item.value == "nvim"
        assert item.last_verified == TODAY
        assert item.status == Status.ACTIVE

    def test_auto_fix_inferred_source(self):
        item = _make_item(src=Source.INFERRED, value="vim")
        drift = DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected="vim",
            actual="nvim",
            evidence="changed",
        )
        result = apply_fix(item, drift, today=TODAY)
        assert result.action == FixAction.AUTO_UPDATED
        assert item.value == "nvim"


class TestFixerContradictionUserSource:
    def test_suspect(self):
        item = _make_item(src=Source.USER, value="vim")
        drift = DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected="vim",
            actual="nvim",
            evidence="user says different",
        )
        result = apply_fix(item, drift, today=TODAY)
        assert result.action == FixAction.MARKED_SUSPECT
        assert item.status == Status.SUSPECT
        assert item.value == "vim"  # value unchanged

    def test_doc_source_suspect(self):
        item = _make_item(src=Source.DOC, value="vim")
        drift = DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected="vim",
            actual="nvim",
            evidence="doc conflict",
        )
        result = apply_fix(item, drift, today=TODAY)
        assert result.action == FixAction.MARKED_SUSPECT
        assert item.status == Status.SUSPECT


class TestFixerUnverifiable:
    def test_no_action(self):
        item = _make_item()
        drift = DriftResult(
            verdict=DriftVerdict.UNVERIFIABLE,
            expected="vim",
            actual=None,
            evidence="Cannot verify",
        )
        result = apply_fix(item, drift, today=TODAY)
        assert result.action == FixAction.NO_ACTION
        assert item.value == "vim"  # unchanged
