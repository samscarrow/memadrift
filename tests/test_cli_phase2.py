import json
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from memadrift.cli import cli
from memadrift.ids import generate_id
from memadrift.models import (
    Impact,
    MemoryItem,
    MemoryType,
    Scope,
    Source,
    Status,
    VerifyMode,
)
from memadrift.parser import MemoryFile, Parser
from memadrift.pending import add_to_queue, read_queue

SCHEMA_CONTENT = """\
keys:
  env.editor:
    type: env
    sources:
      - env_var:EDITOR
    aliases:
      - editor

  user.name:
    type: fact
    sources:
      - git_config:user.name
    aliases:
      - name

  env.shell:
    type: env
    sources:
      - env_var:SHELL
    aliases:
      - shell

  path.home:
    type: env
    sources:
      - env_var:HOME
      - path_exists:~
    aliases:
      - home

  old.fact:
    type: fact
    sources:
      - user_confirm
    aliases:
      - oldfact
"""


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def workspace(tmp_path):
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(SCHEMA_CONTENT)
    return tmp_path


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


# ── optimize tests ──────────────────────────────────────────────

class TestOptimize:
    def _cold_item(self) -> MemoryItem:
        """Create a cold item: LOW impact, FACT type, verified >180 days ago."""
        item_id = generate_id("fact", "global", "old.fact")
        return MemoryItem(
            id=item_id,
            type=MemoryType.FACT,
            scope=Scope.parse("global"),
            key="old.fact",
            value="stale_data",
            src=Source.DOC,
            status=Status.ACTIVE,
            last_verified=date(2024, 1, 1),
            ttl_days=90,
            verify_mode=VerifyMode.AUTO,
            impact=Impact.LOW,
        )

    def test_optimize_dry_run(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        item = self._cold_item()
        mf = MemoryFile(frontmatter={"version": 1}, items=[item], path=mem_path)
        Parser.write(mf, mem_path, backup=False)

        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "optimize", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "old.fact" in result.output
        assert "would be archived" in result.output

    def test_optimize_moves_cold_item(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        item = self._cold_item()
        mf = MemoryFile(frontmatter={"version": 1}, items=[item], path=mem_path)
        Parser.write(mf, mem_path, backup=False)

        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "optimize"],
        )
        assert result.exit_code == 0
        assert "Archived" in result.output
        assert "Moved 1 item(s)" in result.output

        # Verify item is in archive and removed from index
        reloaded = Parser.read(mem_path)
        assert len(reloaded.items) == 0
        assert "archive.md" in reloaded.frontmatter.get("includes", [])

        archive = Parser.read(workspace / "archive.md")
        assert len(archive.items) == 1
        assert archive.items[0].key == "old.fact"

    def test_optimize_creates_archive(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        item = self._cold_item()
        mf = MemoryFile(frontmatter={"version": 1}, items=[item], path=mem_path)
        Parser.write(mf, mem_path, backup=False)

        runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "optimize"],
        )
        archive_path = workspace / "archive.md"
        assert archive_path.exists()
        archive = Parser.read(archive_path)
        assert archive.frontmatter.get("role") == "archive"

    def test_optimize_includes_updated(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        item = self._cold_item()
        mf = MemoryFile(frontmatter={"version": 1}, items=[item], path=mem_path)
        Parser.write(mf, mem_path, backup=False)

        runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "optimize"],
        )
        reloaded = Parser.read(mem_path)
        assert "archive.md" in reloaded.frontmatter["includes"]

    def test_optimize_no_cold_items(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        # Recent, high-impact item — not cold
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "optimize"],
        )
        assert result.exit_code == 0
        assert "No cold items found" in result.output

    def test_optimize_custom_archive(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        item = self._cold_item()
        mf = MemoryFile(frontmatter={"version": 1}, items=[item], path=mem_path)
        Parser.write(mf, mem_path, backup=False)

        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "optimize", "--archive", "old_stuff.md"],
        )
        assert result.exit_code == 0
        assert (workspace / "old_stuff.md").exists()


# ── scan --deep tests ──────────────────────────────────────────

class TestScanDeep:
    def test_scan_deep_flag_accepted(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("EDITOR", "vim")
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--deep", "--dry-run"],
        )
        assert result.exit_code == 0

    def test_scan_deep_includes_topic_items(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/bash")
        mem_path = workspace / "MEMORY.md"
        topic_path = workspace / "topic.md"

        # Create index with include
        item_id = generate_id("env", "global", "env.editor")
        index_content = (
            "---\nversion: 1\nincludes:\n  - topic.md\n---\n"
            f"{item_id} | env | scope=global | key=env.editor"
            " | value=vim | src=tool | status=active"
            " | last_verified=2025-01-15 | ttl_days=30 | verify_mode=auto | impact=low\n"
        )
        mem_path.write_text(index_content)

        # Create topic with a checkable item
        topic_id = generate_id("env", "global", "env.shell")
        topic_content = (
            "---\nversion: 1\n---\n"
            f"{topic_id} | env | scope=global | key=env.shell"
            " | value=/bin/bash | src=tool | status=active"
            " | last_verified=2025-01-15 | ttl_days=30 | verify_mode=auto | impact=low\n"
        )
        topic_path.write_text(topic_content)

        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--deep", "--dry-run"],
        )
        assert result.exit_code == 0
        # Should check items from both files
        assert "env.shell" in result.output

    def test_scan_deep_writes_back(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        mem_path = workspace / "MEMORY.md"
        topic_path = workspace / "topic.md"

        mem_path.write_text("---\nversion: 1\nincludes:\n  - topic.md\n---\n")
        topic_id = generate_id("env", "global", "env.shell")
        topic_content = (
            "---\nversion: 1\n---\n"
            f"{topic_id} | env | scope=global | key=env.shell"
            " | value=/bin/bash | src=tool | status=active"
            " | last_verified=2025-01-15 | ttl_days=30 | verify_mode=auto | impact=low\n"
        )
        topic_path.write_text(topic_content)

        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "scan", "--deep"],
        )
        assert result.exit_code == 0
        assert "Wrote" in result.output
        # Verify value was updated
        reloaded = Parser.read(topic_path)
        assert reloaded.items[0].value == "/bin/zsh"


# ── --network flag tests ────────────────────────────────────────

class TestNetworkFlag:
    def test_network_flag_accepted(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        result = runner.invoke(
            cli,
            ["--network", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "scan", "--dry-run"],
        )
        assert result.exit_code == 0

    def test_env_file_loaded(self, runner, workspace, monkeypatch):
        mem_path = workspace / "MEMORY.md"
        env_file = workspace / "test.env"
        env_file.write_text("TEST_NETWORK_VAR=loaded\n")
        monkeypatch.delenv("TEST_NETWORK_VAR", raising=False)

        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        result = runner.invoke(
            cli,
            ["--network", "--env-file", str(env_file),
             "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "scan", "--dry-run"],
        )
        assert result.exit_code == 0
        assert os.environ.get("TEST_NETWORK_VAR") == "loaded"

    def test_sources_not_added_without_network(self, runner, workspace):
        """Without --network, external sources aren't instantiated."""
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        # Default scan (no --network)
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "scan", "--dry-run"],
        )
        assert result.exit_code == 0


# ── pending queue + verify-pending tests ────────────────────────

class TestPendingQueue:
    def test_scan_pending_queue(self, runner, workspace):
        """Items with no source get queued when --pending-queue is set."""
        schema_with_user = SCHEMA_CONTENT + """\
  editor.theme:
    type: pref
    sources:
      - user_confirm
    aliases:
      - theme
"""
        (workspace / "schema.yaml").write_text(schema_with_user)
        mem_path = workspace / "MEMORY.md"
        queue_path = workspace / "pending.json"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "editor.theme", "--value", "monokai",
             "--type", "pref", "--verify-mode", "human"],
        )
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--dry-run", "--pending-queue", str(queue_path)],
        )
        assert result.exit_code == 0
        assert "queued for pending" in result.output
        entries = read_queue(queue_path)
        assert len(entries) == 1
        assert entries[0]["key"] == "editor.theme"

    def test_verify_pending_empty(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        queue_path = workspace / "pending.json"
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "verify-pending", "--queue", str(queue_path)],
        )
        assert result.exit_code == 0
        assert "No pending verifications" in result.output

    def test_verify_pending_resolves(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        queue_path = workspace / "pending.json"

        # Add an item
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        mf = Parser.read(mem_path)
        item_id = mf.items[0].id

        # Manually add to queue
        add_to_queue(
            item_id=item_id,
            key="env.editor",
            current_value="vim",
            verify_mode="auto",
            source_file=str(mem_path),
            evidence="no source",
            path=queue_path,
        )

        # Verify with "y" (confirm current value)
        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "verify-pending", "--queue", str(queue_path)],
            input="y\n",
        )
        assert result.exit_code == 0
        assert "Resolved 1 pending" in result.output
        assert read_queue(queue_path) == []

    def test_verify_pending_missing_item(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        queue_path = workspace / "pending.json"
        mem_path.write_text("---\nversion: 1\n---\n")
        # Queue references an item not in the memory file
        add_to_queue("mem_ZZZZZZZZ", "phantom", "val", "auto", str(mem_path), "e", queue_path)
        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "verify-pending", "--queue", str(queue_path)],
        )
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_scan_without_pending_queue_skips(self, runner, workspace):
        """Without --pending-queue, items without source just skip normally."""
        schema_with_user = SCHEMA_CONTENT + """\
  editor.theme:
    type: pref
    sources:
      - user_confirm
    aliases:
      - theme
"""
        (workspace / "schema.yaml").write_text(schema_with_user)
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "editor.theme", "--value", "monokai",
             "--type", "pref", "--verify-mode", "human"],
        )
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "no checkable source" in result.output
