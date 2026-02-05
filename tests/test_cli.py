import json
import os
import shutil
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from memadrift.cli import cli
from memadrift.ids import generate_id
from memadrift.parser import Parser

FIXTURES = Path(__file__).parent.parent / "fixtures"

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
"""


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace with a schema file."""
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(SCHEMA_CONTENT)
    return tmp_path


class TestVersion:
    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.output


class TestHelp:
    def test_help_shows_commands(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ids" in result.output
        assert "lint" in result.output
        assert "scan" in result.output
        assert "add" in result.output
        assert "optimize" in result.output
        assert "verify-pending" in result.output


class TestAdd:
    def test_add_creates_file(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        assert result.exit_code == 0, result.output
        assert "Added" in result.output
        assert mem_path.exists()
        mf = Parser.read(mem_path)
        assert len(mf.items) == 1
        assert mf.items[0].key == "env.editor"
        assert mf.items[0].value == "vim"

    def test_add_rejects_duplicate(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "emacs"],
        )
        assert result.exit_code != 0
        assert "Duplicate" in result.output or "Duplicate" in (result.output + str(result.exception or ""))

    def test_add_correct_id(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        mf = Parser.read(mem_path)
        expected_id = generate_id("env", "global", "env.editor")
        assert mf.items[0].id == expected_id


class TestIds:
    def test_ids_fixes_wrong_ids(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        shutil.copy(FIXTURES / "sample_memory.md", mem_path)
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "ids"],
        )
        assert result.exit_code == 0
        assert "Updated 2 ID(s)" in result.output

    def test_ids_all_correct(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        # Add an item with correct ID
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "ids"],
        )
        assert result.exit_code == 0
        assert "All IDs are correct" in result.output

    def test_ids_deep_normalizes_across_files(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        topic_path = workspace / "topic.md"
        mem_path.write_text(
            "---\nversion: 1\nincludes:\n  - topic.md\n---\n"
            "mem_AAAAAAAA | env | scope=global | key=env.editor"
            " | value=vim | src=tool | status=active"
            " | last_verified=2025-01-15 | ttl_days=30 | verify_mode=auto | impact=low\n"
        )
        topic_path.write_text(
            "---\nversion: 1\n---\n"
            "mem_BBBBBBBB | env | scope=global | key=env.shell"
            " | value=/bin/bash | src=tool | status=active"
            " | last_verified=2025-01-15 | ttl_days=30 | verify_mode=auto | impact=low\n"
        )
        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "ids", "--deep"],
        )
        assert result.exit_code == 0
        assert "Updated" in result.output or "All IDs are correct" in result.output

    def test_ids_deep_no_changes(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        # Use add to create a correct-ID item, then verify --deep reports correct
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"),
             "ids", "--deep"],
        )
        assert result.exit_code == 0
        assert "All IDs are correct" in result.output

    def test_ids_missing_file(self, runner, workspace):
        result = runner.invoke(
            cli,
            ["--memory", str(workspace / "nonexistent.md"),
             "--schema", str(workspace / "schema.yaml"),
             "ids"],
        )
        assert result.exit_code != 0


class TestLint:
    def test_lint_clean(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "lint"],
        )
        assert result.exit_code == 0
        assert "Lint passed" in result.output

    def test_lint_wrong_ids(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        shutil.copy(FIXTURES / "sample_memory.md", mem_path)
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "lint"],
        )
        assert result.exit_code != 0

    def test_lint_overlong(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        shutil.copy(FIXTURES / "overlong_memory.md", mem_path)
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "lint"],
        )
        assert result.exit_code != 0
        assert "200 lines" in (result.output + str(result.exception or ""))


class TestLintRefs:
    def test_lint_valid_ref(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        target = workspace / "archive.md"
        target.write_text("---\nversion: 1\n---\n")
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        # Manually add ref to the record
        mf = Parser.read(mem_path)
        mf.items[0].ref = "archive.md"
        Parser.write(mf, mem_path, backup=False)
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "lint"],
        )
        assert result.exit_code == 0

    def test_lint_invalid_ref_missing_file(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        mf = Parser.read(mem_path)
        mf.items[0].ref = "nonexistent.md"
        Parser.write(mf, mem_path, backup=False)
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "lint"],
        )
        assert result.exit_code != 0

    def test_lint_invalid_ref_missing_anchor(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        target = workspace / "archive.md"
        target.write_text("---\nversion: 1\n---\n")
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        mf = Parser.read(mem_path)
        mf.items[0].ref = "archive.md#mem_ZZZZZZZZ"
        Parser.write(mf, mem_path, backup=False)
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "lint"],
        )
        assert result.exit_code != 0


class TestBackupCli:
    def test_ids_creates_backup(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        shutil.copy(FIXTURES / "sample_memory.md", mem_path)
        original = mem_path.read_text()
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "ids"],
        )
        assert result.exit_code == 0
        bak = workspace / "MEMORY.md.bak"
        assert bak.exists()
        assert bak.read_text() == original

    def test_add_no_backup_for_new_file(self, runner, workspace):
        mem_path = workspace / "NEW_MEMORY.md"
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim"],
        )
        assert result.exit_code == 0
        assert not (workspace / "NEW_MEMORY.md.bak").exists()

    def test_no_backup_flag(self, runner, workspace):
        mem_path = workspace / "MEMORY.md"
        shutil.copy(FIXTURES / "sample_memory.md", mem_path)
        result = runner.invoke(
            cli,
            ["--no-backup", "--memory", str(mem_path),
             "--schema", str(workspace / "schema.yaml"), "ids"],
        )
        assert result.exit_code == 0
        assert not (workspace / "MEMORY.md.bak").exists()


class TestScan:
    def test_scan_dry_run(self, runner, workspace, monkeypatch):
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
             "scan", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output

    def test_scan_applies_fixes(self, runner, workspace, monkeypatch):
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
             "scan"],
        )
        assert result.exit_code == 0
        assert "Wrote" in result.output or "already correct" in result.output.lower()

    def test_scan_interactive_flag_accepted(self, runner, workspace, monkeypatch):
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
             "scan", "--interactive", "--dry-run"],
        )
        assert result.exit_code == 0

    def test_scan_non_interactive_skips_user_confirm(self, runner, workspace):
        """Item with only user_confirm source is skipped without --interactive."""
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

    def test_scan_interactive_human_verify_fallback(self, runner, workspace):
        """verify_mode=human item with no user_confirm in schema gets implicit fallback when --interactive."""
        mem_path = workspace / "MEMORY.md"
        # user.name has git_config source only — no user_confirm in schema
        # We use a schema without user_confirm for user.name
        schema_no_user_confirm = """\
keys:
  user.name:
    type: fact
    sources:
      - git_config:user.name
    aliases:
      - name
"""
        (workspace / "schema.yaml").write_text(schema_no_user_confirm)
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "user.name", "--value", "Sam",
             "--type", "fact", "--verify-mode", "human", "--src", "user"],
        )
        # Feed "y" to the UserSource prompt to confirm
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--interactive", "--dry-run"],
            input="y\n",
        )
        assert result.exit_code == 0
        # Should have checked via user_confirm fallback, not "no checkable source"
        assert "no checkable source" not in result.output


class TestScanBudget:
    def test_scan_limit(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("EDITOR", "vim")
        monkeypatch.setenv("SHELL", "/bin/bash")
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.shell", "--value", "/bin/bash", "--src", "tool"],
        )
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--limit", "1", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Limit reached" in result.output

    def test_scan_max_cost(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("EDITOR", "vim")
        monkeypatch.setenv("SHELL", "/bin/bash")
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.shell", "--value", "/bin/bash", "--src", "tool"],
        )
        # AUTO costs 0.1 each, so budget of 0.1 allows 1 item then stops
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--max-cost", "0.1", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Budget exhausted" in result.output

    def test_scan_budget_message(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("EDITOR", "vim")
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        # Budget of 0.05 is below AUTO cost (0.1), so stops immediately
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--max-cost", "0.05", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Budget exhausted" in result.output


class TestScanAudit:
    def test_scan_writes_audit_log(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("EDITOR", "nvim")
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        audit_path = workspace / "audit.jsonl"
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--audit-log", str(audit_path)],
        )
        assert result.exit_code == 0, result.output
        assert audit_path.exists()
        entry = json.loads(audit_path.read_text().strip().split("\n")[0])
        assert entry["key"] == "env.editor"
        assert entry["action"] == "auto_updated"
        assert entry["old_value"] == "vim"
        assert entry["new_value"] == "nvim"
        assert "Appended" in result.output

    def test_scan_dry_run_no_audit(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("EDITOR", "nvim")
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        audit_path = workspace / "audit.jsonl"
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--dry-run", "--audit-log", str(audit_path)],
        )
        assert result.exit_code == 0
        assert not audit_path.exists()

    def test_scan_no_audit_flag(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("EDITOR", "nvim")
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        audit_path = workspace / "audit.jsonl"
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--no-audit", "--audit-log", str(audit_path)],
        )
        assert result.exit_code == 0
        assert not audit_path.exists()

    def test_scan_custom_audit_path(self, runner, workspace, monkeypatch):
        monkeypatch.setenv("EDITOR", "nvim")
        mem_path = workspace / "MEMORY.md"
        runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "add", "--key", "env.editor", "--value", "vim", "--src", "tool"],
        )
        custom_path = workspace / "custom.jsonl"
        default_path = workspace / "audit.jsonl"
        result = runner.invoke(
            cli,
            ["--memory", str(mem_path), "--schema", str(workspace / "schema.yaml"),
             "scan", "--audit-log", str(custom_path)],
        )
        assert result.exit_code == 0, result.output
        assert custom_path.exists()
        assert not default_path.exists()
