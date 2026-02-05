import shutil
from datetime import date
from pathlib import Path

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
from memadrift.parser import MemoryFile, MemoryStore, ParseError, Parser

FIXTURES = Path(__file__).parent.parent / "fixtures"


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


class TestReadStore:
    def test_read_store_with_includes(self, tmp_path):
        shutil.copy(FIXTURES / "index_with_includes.md", tmp_path / "MEMORY.md")
        shutil.copy(FIXTURES / "topic_memory.md", tmp_path / "topic_memory.md")
        store = Parser.read_store(tmp_path / "MEMORY.md")
        assert len(store.index.items) == 1
        assert "topic_memory.md" in store.topics
        assert len(store.topics["topic_memory.md"].items) == 1

    def test_read_store_empty_includes(self, tmp_path):
        index_path = tmp_path / "MEMORY.md"
        index_path.write_text("---\nversion: 1\nincludes: []\n---\n")
        store = Parser.read_store(index_path)
        assert store.topics == {}
        assert store.index.items == []

    def test_read_store_no_includes(self, tmp_path):
        index_path = tmp_path / "MEMORY.md"
        index_path.write_text("---\nversion: 1\n---\n")
        store = Parser.read_store(index_path)
        assert store.topics == {}

    def test_read_store_missing_include_error(self, tmp_path):
        index_path = tmp_path / "MEMORY.md"
        index_path.write_text("---\nversion: 1\nincludes:\n  - missing.md\n---\n")
        with pytest.raises(ParseError, match="not found"):
            Parser.read_store(index_path)

    def test_read_store_absolute_path_rejection(self, tmp_path):
        index_path = tmp_path / "MEMORY.md"
        index_path.write_text("---\nversion: 1\nincludes:\n  - /etc/passwd\n---\n")
        with pytest.raises(ParseError, match="Absolute path"):
            Parser.read_store(index_path)

    def test_read_store_base_dir(self, tmp_path):
        index_path = tmp_path / "MEMORY.md"
        index_path.write_text("---\nversion: 1\n---\n")
        store = Parser.read_store(index_path)
        assert store.base_dir == tmp_path


class TestWriteStore:
    def test_write_store_roundtrip(self, tmp_path):
        index_item = _make_item(id="mem_AAAAAAAA", key="env.editor")
        topic_item = _make_item(id="mem_BBBBBBBB", key="user.name", value="Sam")
        index = MemoryFile(
            frontmatter={"version": 1, "includes": ["topic.md"]},
            items=[index_item],
            path=tmp_path / "MEMORY.md",
        )
        topic = MemoryFile(
            frontmatter={"version": 1, "role": "archive"},
            items=[topic_item],
            path=tmp_path / "topic.md",
        )
        store = MemoryStore(index=index, topics={"topic.md": topic})
        Parser.write_store(store, backup=False)

        loaded = Parser.read_store(tmp_path / "MEMORY.md")
        assert len(loaded.index.items) == 1
        assert loaded.index.items[0].key == "env.editor"
        assert len(loaded.topics["topic.md"].items) == 1
        assert loaded.topics["topic.md"].items[0].key == "user.name"

    def test_write_store_creates_topic_file(self, tmp_path):
        index = MemoryFile(
            frontmatter={"version": 1, "includes": ["new_topic.md"]},
            items=[],
            path=tmp_path / "MEMORY.md",
        )
        topic_item = _make_item(id="mem_CCCCCCCC", key="env.shell")
        topic = MemoryFile(
            frontmatter={"version": 1},
            items=[topic_item],
            path=tmp_path / "new_topic.md",
        )
        store = MemoryStore(index=index, topics={"new_topic.md": topic})
        Parser.write_store(store, backup=False)

        assert (tmp_path / "new_topic.md").exists()
        assert (tmp_path / "MEMORY.md").exists()


class TestAllItems:
    def test_all_items_aggregation(self, tmp_path):
        index_item = _make_item(id="mem_AAAAAAAA", key="env.editor")
        topic_item = _make_item(id="mem_BBBBBBBB", key="user.name")
        index = MemoryFile(
            frontmatter={"version": 1},
            items=[index_item],
            path=tmp_path / "MEMORY.md",
        )
        topic = MemoryFile(
            frontmatter={},
            items=[topic_item],
        )
        store = MemoryStore(index=index, topics={"topic.md": topic})
        assert len(store.all_items) == 2
        keys = [it.key for it in store.all_items]
        assert "env.editor" in keys
        assert "user.name" in keys

    def test_all_items_empty_store(self, tmp_path):
        index = MemoryFile(
            frontmatter={"version": 1},
            items=[],
            path=tmp_path / "MEMORY.md",
        )
        store = MemoryStore(index=index)
        assert store.all_items == []


class TestAllFiles:
    def test_all_files_ordering(self, tmp_path):
        index = MemoryFile(
            frontmatter={"version": 1},
            items=[],
            path=tmp_path / "MEMORY.md",
        )
        topic_a = MemoryFile(frontmatter={}, items=[], path=tmp_path / "a.md")
        topic_b = MemoryFile(frontmatter={}, items=[], path=tmp_path / "b.md")
        store = MemoryStore(
            index=index,
            topics={"a.md": topic_a, "b.md": topic_b},
        )
        files = store.all_files
        # Topics first, index last
        assert files[-1] is index
        assert len(files) == 3

    def test_all_files_no_topics(self, tmp_path):
        index = MemoryFile(
            frontmatter={"version": 1},
            items=[],
            path=tmp_path / "MEMORY.md",
        )
        store = MemoryStore(index=index)
        assert len(store.all_files) == 1
        assert store.all_files[0] is index


class TestMultipleIncludes:
    def test_multiple_includes(self, tmp_path):
        (tmp_path / "a.md").write_text("---\nversion: 1\n---\n")
        (tmp_path / "b.md").write_text("---\nversion: 1\n---\n")
        index_path = tmp_path / "MEMORY.md"
        index_path.write_text(
            "---\nversion: 1\nincludes:\n  - a.md\n  - b.md\n---\n"
        )
        store = Parser.read_store(index_path)
        assert len(store.topics) == 2
        assert "a.md" in store.topics
        assert "b.md" in store.topics
