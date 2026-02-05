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
        assert "0.1.0" in result.output


class TestHelp:
    def test_help_shows_commands(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ids" in result.output
        assert "lint" in result.output
        assert "scan" in result.output
        assert "add" in result.output


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
