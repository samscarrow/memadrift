import json
from datetime import date, datetime
from pathlib import Path

from memadrift.audit import format_entry, write_entries
from memadrift.fixer import FixAction, FixResult
from memadrift.models import (
    Impact,
    MemoryItem,
    MemoryType,
    Scope,
    Source,
    Status,
    VerifyMode,
)


def _make_item(**overrides):
    defaults = dict(
        id="mem_ABCDEFGH",
        type=MemoryType.ENV,
        scope=Scope(kind="global"),
        key="env.editor",
        value="nvim",
        src=Source.TOOL,
        status=Status.ACTIVE,
        last_verified=date(2026, 2, 5),
        ttl_days=30,
        verify_mode=VerifyMode.AUTO,
        impact=Impact.LOW,
    )
    defaults.update(overrides)
    return MemoryItem(**defaults)


def _make_result(**overrides):
    defaults = dict(
        item=_make_item(),
        action=FixAction.AUTO_UPDATED,
        old_value="vim",
        new_value="nvim",
        detail="Auto-updated from 'vim' to 'nvim'",
    )
    defaults.update(overrides)
    return FixResult(**defaults)


class TestFormatEntry:
    def test_format_entry_fields(self):
        result = _make_result()
        entry = format_entry(result, "MEMORY.md")

        assert entry["item_id"] == "mem_ABCDEFGH"
        assert entry["key"] == "env.editor"
        assert entry["action"] == "auto_updated"
        assert entry["old_value"] == "vim"
        assert entry["new_value"] == "nvim"
        assert entry["detail"] == "Auto-updated from 'vim' to 'nvim'"
        assert entry["src"] == "tool"
        assert entry["scope"] == "global"
        assert entry["type"] == "env"
        assert entry["memory_file"] == "MEMORY.md"
        # Timestamp should parse as ISO-8601
        datetime.fromisoformat(entry["timestamp"])

    def test_format_entry_null_values(self):
        result = _make_result(
            action=FixAction.ALREADY_CORRECT,
            old_value=None,
            new_value=None,
            detail="Value matches reality; refreshed last_verified",
        )
        entry = format_entry(result, "MEMORY.md")

        assert entry["action"] == "already_correct"
        assert entry["old_value"] is None
        assert entry["new_value"] is None


class TestWriteEntries:
    def test_write_entries_creates_file(self, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        result = _make_result()
        count = write_entries([result], audit_path, "MEMORY.md")

        assert count == 1
        assert audit_path.exists()
        entry = json.loads(audit_path.read_text().strip())
        assert entry["item_id"] == "mem_ABCDEFGH"

    def test_write_entries_appends(self, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        result = _make_result()
        write_entries([result], audit_path, "MEMORY.md")
        write_entries([result], audit_path, "MEMORY.md")

        lines = [l for l in audit_path.read_text().strip().split("\n") if l]
        assert len(lines) == 2

    def test_write_entries_empty_list(self, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        count = write_entries([], audit_path, "MEMORY.md")

        assert count == 0
        assert not audit_path.exists()

    def test_write_entries_multiple(self, tmp_path):
        audit_path = tmp_path / "audit.jsonl"
        results = [_make_result() for _ in range(3)]
        count = write_entries(results, audit_path, "MEMORY.md")

        assert count == 3
        lines = [l for l in audit_path.read_text().strip().split("\n") if l]
        assert len(lines) == 3
        for line in lines:
            entry = json.loads(line)
            assert entry["action"] == "auto_updated"
