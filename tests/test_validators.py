from datetime import date
from pathlib import Path

from memadrift.models import (
    Impact,
    MemoryItem,
    MemoryType,
    Scope,
    Source,
    Status,
    VerifyMode,
)
from memadrift.parser import MemoryFile, MemoryStore, Parser
from memadrift.validators import validate_cross_file_ids, validate_ref


def _make_item(**overrides) -> MemoryItem:
    defaults = dict(
        id="mem_ABCDEFGH",
        type=MemoryType.ENV,
        scope=Scope.parse("global"),
        key="env.editor",
        value="vim",
        src=Source.TOOL,
        status=Status.ACTIVE,
        last_verified=date(2025, 1, 15),
        ttl_days=30,
        verify_mode=VerifyMode.AUTO,
        impact=Impact.LOW,
    )
    defaults.update(overrides)
    return MemoryItem(**defaults)


class TestValidateRef:
    def test_valid_ref_file_only(self, tmp_path):
        target = tmp_path / "archive.md"
        target.write_text("---\nversion: 1\n---\n")
        errors = validate_ref("archive.md", tmp_path)
        assert errors == []

    def test_valid_ref_with_anchor_id(self, tmp_path):
        item = _make_item(id="mem_ABCDEFGH")
        mf = MemoryFile(frontmatter={"version": 1}, items=[item])
        Parser.write(mf, tmp_path / "archive.md", backup=False)
        errors = validate_ref("archive.md#mem_ABCDEFGH", tmp_path)
        assert errors == []

    def test_valid_ref_with_anchor_key(self, tmp_path):
        item = _make_item(key="env.editor")
        mf = MemoryFile(frontmatter={"version": 1}, items=[item])
        Parser.write(mf, tmp_path / "archive.md", backup=False)
        errors = validate_ref("archive.md#env.editor", tmp_path)
        assert errors == []

    def test_missing_file(self, tmp_path):
        errors = validate_ref("nonexistent.md", tmp_path)
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_missing_anchor(self, tmp_path):
        item = _make_item(id="mem_ABCDEFGH")
        mf = MemoryFile(frontmatter={"version": 1}, items=[item])
        Parser.write(mf, tmp_path / "archive.md", backup=False)
        errors = validate_ref("archive.md#mem_ZZZZZZZZ", tmp_path)
        assert len(errors) == 1
        assert "anchor not found" in errors[0]

    def test_no_anchor_ref(self, tmp_path):
        target = tmp_path / "notes.md"
        target.write_text("---\nversion: 1\n---\n")
        errors = validate_ref("notes.md", tmp_path)
        assert errors == []


class TestValidateCrossFileIds:
    def test_unique_ids(self, tmp_path):
        index = MemoryFile(
            frontmatter={},
            items=[_make_item(id="mem_AAAAAAAA")],
            path=tmp_path / "MEMORY.md",
        )
        topic = MemoryFile(
            frontmatter={},
            items=[_make_item(id="mem_BBBBBBBB")],
            path=tmp_path / "topic.md",
        )
        store = MemoryStore(index=index, topics={"topic.md": topic})
        errors = validate_cross_file_ids(store)
        assert errors == []

    def test_duplicate_ids_across_files(self, tmp_path):
        index = MemoryFile(
            frontmatter={},
            items=[_make_item(id="mem_AAAAAAAA")],
            path=tmp_path / "MEMORY.md",
        )
        topic = MemoryFile(
            frontmatter={},
            items=[_make_item(id="mem_AAAAAAAA")],
            path=tmp_path / "topic.md",
        )
        store = MemoryStore(index=index, topics={"topic.md": topic})
        errors = validate_cross_file_ids(store)
        assert len(errors) == 1
        assert "Duplicate ID" in errors[0]

    def test_duplicate_ids_within_file(self, tmp_path):
        index = MemoryFile(
            frontmatter={},
            items=[
                _make_item(id="mem_AAAAAAAA", key="env.editor"),
                _make_item(id="mem_AAAAAAAA", key="env.shell"),
            ],
            path=tmp_path / "MEMORY.md",
        )
        store = MemoryStore(index=index)
        errors = validate_cross_file_ids(store)
        assert len(errors) == 1

    def test_empty_store(self, tmp_path):
        index = MemoryFile(frontmatter={}, items=[], path=tmp_path / "MEMORY.md")
        store = MemoryStore(index=index)
        errors = validate_cross_file_ids(store)
        assert errors == []
