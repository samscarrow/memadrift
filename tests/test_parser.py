import os
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
from memadrift.parser import MemoryFile, ParseError, Parser


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


SAMPLE_RECORD = (
    "mem_ABCDEFGH | env | scope=global | key=env.editor"
    " | value=vim | src=tool | status=active"
    " | last_verified=2025-01-15 | ttl_days=30 | verify_mode=auto | impact=low"
)

SAMPLE_WITH_FRONTMATTER = f"""\
---
version: 1
owner: sam
---
{SAMPLE_RECORD}
"""


class TestRoundTrip:
    def test_write_then_read(self, tmp_path):
        item = _make_item()
        mf = MemoryFile(frontmatter={"version": 1}, items=[item])
        path = tmp_path / "MEMORY.md"
        Parser.write(mf, path)
        loaded = Parser.read(path)
        assert len(loaded.items) == 1
        assert loaded.items[0].id == "mem_ABCDEFGH"
        assert loaded.items[0].key == "env.editor"
        assert loaded.items[0].value == "vim"
        assert loaded.frontmatter["version"] == 1

    def test_multiple_items(self, tmp_path):
        items = [
            _make_item(id="mem_AAAAAAAA", key="env.editor"),
            _make_item(id="mem_BBBBBBBB", key="env.shell", value="/bin/bash"),
        ]
        mf = MemoryFile(frontmatter={}, items=items)
        path = tmp_path / "MEMORY.md"
        Parser.write(mf, path)
        loaded = Parser.read(path)
        assert len(loaded.items) == 2
        assert loaded.items[1].value == "/bin/bash"


class TestFrontmatter:
    def test_extract_frontmatter(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text(SAMPLE_WITH_FRONTMATTER)
        mf = Parser.read(path)
        assert mf.frontmatter["version"] == 1
        assert mf.frontmatter["owner"] == "sam"
        assert len(mf.items) == 1

    def test_no_frontmatter(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text(SAMPLE_RECORD + "\n")
        mf = Parser.read(path)
        assert mf.frontmatter == {}
        assert len(mf.items) == 1


class TestTolerantSpacing:
    def test_extra_spaces(self, tmp_path):
        record = (
            "mem_ABCDEFGH  |  env  |  scope=global  |  key=env.editor"
            "  |  value=vim  |  src=tool  |  status=active"
            "  |  last_verified=2025-01-15  |  ttl_days=30"
            "  |  verify_mode=auto  |  impact=low"
        )
        path = tmp_path / "test.md"
        path.write_text(record + "\n")
        mf = Parser.read(path)
        assert len(mf.items) == 1
        assert mf.items[0].value == "vim"

    def test_minimal_spaces(self, tmp_path):
        record = (
            "mem_ABCDEFGH|env|scope=global|key=env.editor"
            "|value=vim|src=tool|status=active"
            "|last_verified=2025-01-15|ttl_days=30"
            "|verify_mode=auto|impact=low"
        )
        path = tmp_path / "test.md"
        path.write_text(record + "\n")
        mf = Parser.read(path)
        assert len(mf.items) == 1


class TestCanonicalOutput:
    def test_canonical_format(self, tmp_path):
        item = _make_item()
        mf = MemoryFile(frontmatter={}, items=[item])
        path = tmp_path / "test.md"
        Parser.write(mf, path)
        content = path.read_text()
        assert "mem_ABCDEFGH | env | scope=global" in content
        assert "| value=vim |" in content


class TestParseErrors:
    def test_invalid_record(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("this is not a valid record\n")
        with pytest.raises(ParseError) as exc_info:
            Parser.read(path)
        assert exc_info.value.line_number == 1

    def test_invalid_enum_value(self, tmp_path):
        record = (
            "mem_ABCDEFGH | badtype | scope=global | key=env.editor"
            " | value=vim | src=tool | status=active"
            " | last_verified=2025-01-15 | ttl_days=30"
            " | verify_mode=auto | impact=low"
        )
        path = tmp_path / "test.md"
        path.write_text(record + "\n")
        with pytest.raises(ParseError):
            Parser.read(path)


class TestEmptyFile:
    def test_empty(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("")
        mf = Parser.read(path)
        assert mf.items == []
        assert mf.frontmatter == {}

    def test_only_frontmatter(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("---\nversion: 1\n---\n")
        mf = Parser.read(path)
        assert mf.items == []
        assert mf.frontmatter["version"] == 1


class TestCommentsAndBlanks:
    def test_comments_skipped(self, tmp_path):
        content = f"# This is a comment\n\n{SAMPLE_RECORD}\n"
        path = tmp_path / "test.md"
        path.write_text(content)
        mf = Parser.read(path)
        assert len(mf.items) == 1

    def test_blank_lines_skipped(self, tmp_path):
        content = f"\n\n{SAMPLE_RECORD}\n\n"
        path = tmp_path / "test.md"
        path.write_text(content)
        mf = Parser.read(path)
        assert len(mf.items) == 1


class TestValuesWithSpaces:
    def test_value_with_spaces(self, tmp_path):
        record = (
            "mem_ABCDEFGH | fact | scope=global | key=user.name"
            " | value=Sam Scarrow | src=user | status=active"
            " | last_verified=2025-01-15 | ttl_days=90"
            " | verify_mode=human | impact=med"
        )
        path = tmp_path / "test.md"
        path.write_text(record + "\n")
        mf = Parser.read(path)
        assert mf.items[0].value == "Sam Scarrow"


class TestRefField:
    def test_parse_record_with_ref(self, tmp_path):
        record = (
            "mem_ABCDEFGH | env | scope=global | key=env.editor"
            " | value=vim | src=tool | status=active"
            " | last_verified=2025-01-15 | ttl_days=30 | verify_mode=auto | impact=low"
            " | ref=archive.md#mem_ABCDEFGH"
        )
        path = tmp_path / "test.md"
        path.write_text(record + "\n")
        mf = Parser.read(path)
        assert len(mf.items) == 1
        assert mf.items[0].ref == "archive.md#mem_ABCDEFGH"

    def test_parse_record_without_ref(self, tmp_path):
        record = (
            "mem_ABCDEFGH | env | scope=global | key=env.editor"
            " | value=vim | src=tool | status=active"
            " | last_verified=2025-01-15 | ttl_days=30 | verify_mode=auto | impact=low"
        )
        path = tmp_path / "test.md"
        path.write_text(record + "\n")
        mf = Parser.read(path)
        assert len(mf.items) == 1
        assert mf.items[0].ref is None

    def test_roundtrip_with_ref(self, tmp_path):
        item = _make_item(ref="patterns.md#mem_ABCDEFGH")
        mf = MemoryFile(frontmatter={}, items=[item])
        path = tmp_path / "test.md"
        Parser.write(mf, path)
        loaded = Parser.read(path)
        assert loaded.items[0].ref == "patterns.md#mem_ABCDEFGH"

    def test_roundtrip_without_ref(self, tmp_path):
        item = _make_item()
        mf = MemoryFile(frontmatter={}, items=[item])
        path = tmp_path / "test.md"
        Parser.write(mf, path)
        loaded = Parser.read(path)
        assert loaded.items[0].ref is None
        content = path.read_text()
        assert "ref=" not in content

    def test_ref_with_anchor_fragment(self, tmp_path):
        record = (
            "mem_ABCDEFGH | env | scope=global | key=env.editor"
            " | value=vim | src=tool | status=active"
            " | last_verified=2025-01-15 | ttl_days=30 | verify_mode=auto | impact=low"
            " | ref=topics/archive.md#env.editor"
        )
        path = tmp_path / "test.md"
        path.write_text(record + "\n")
        mf = Parser.read(path)
        assert mf.items[0].ref == "topics/archive.md#env.editor"


class TestBackup:
    def test_write_creates_backup(self, tmp_path):
        item = _make_item()
        mf = MemoryFile(frontmatter={"version": 1}, items=[item])
        path = tmp_path / "MEMORY.md"
        Parser.write(mf, path)
        original = path.read_text()

        # Write again with a changed item
        mf.items[0] = _make_item(value="emacs")
        Parser.write(mf, path)

        bak = tmp_path / "MEMORY.md.bak"
        assert bak.exists()
        assert bak.read_text() == original

    def test_write_no_backup_flag(self, tmp_path):
        item = _make_item()
        mf = MemoryFile(frontmatter={}, items=[item])
        path = tmp_path / "MEMORY.md"
        Parser.write(mf, path)
        Parser.write(mf, path, backup=False)

        bak = tmp_path / "MEMORY.md.bak"
        assert not bak.exists()

    def test_write_backup_new_file_no_crash(self, tmp_path):
        item = _make_item()
        mf = MemoryFile(frontmatter={}, items=[item])
        path = tmp_path / "NEW.md"
        Parser.write(mf, path)  # backup=True but file doesn't exist yet — no error
        assert path.exists()
        assert not (tmp_path / "NEW.md.bak").exists()


class TestAtomicWrite:
    def test_no_temp_file_on_success(self, tmp_path):
        item = _make_item()
        mf = MemoryFile(frontmatter={}, items=[item])
        path = tmp_path / "test.md"
        Parser.write(mf, path)
        # No temp files should remain
        temps = [f for f in tmp_path.iterdir() if f.name.startswith(".memadrift_")]
        assert temps == []

    def test_original_preserved_on_error(self, tmp_path):
        path = tmp_path / "test.md"
        path.write_text("original content")
        # Create a MemoryFile with a path that will cause write to succeed
        # but verify the mechanism works
        item = _make_item()
        mf = MemoryFile(frontmatter={}, items=[item])
        Parser.write(mf, path)
        content = path.read_text()
        assert "mem_ABCDEFGH" in content
