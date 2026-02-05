from pathlib import Path

import pytest

from memadrift.schema import KeyDef, Schema


@pytest.fixture
def schema_path(tmp_path):
    content = """\
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
"""
    path = tmp_path / "schema.yaml"
    path.write_text(content)
    return path


class TestSchemaLoad:
    def test_load(self, schema_path):
        schema = Schema.load(schema_path)
        assert schema.resolve("env.editor") == "env.editor"

    def test_alias_resolution(self, schema_path):
        schema = Schema.load(schema_path)
        assert schema.resolve("editor") == "env.editor"
        assert schema.resolve("name") == "user.name"
        assert schema.resolve("shell") == "env.shell"

    def test_canonical_self_resolution(self, schema_path):
        schema = Schema.load(schema_path)
        assert schema.resolve("env.editor") == "env.editor"
        assert schema.resolve("user.name") == "user.name"

    def test_unknown_key(self, schema_path):
        schema = Schema.load(schema_path)
        assert schema.resolve("nonexistent") is None

    def test_sources_for(self, schema_path):
        schema = Schema.load(schema_path)
        sources = schema.sources_for("env.editor")
        assert sources == ["env_var:EDITOR"]

    def test_sources_for_alias(self, schema_path):
        schema = Schema.load(schema_path)
        sources = schema.sources_for("editor")
        assert sources == ["env_var:EDITOR"]

    def test_sources_for_unknown(self, schema_path):
        schema = Schema.load(schema_path)
        assert schema.sources_for("nonexistent") == []

    def test_get_keydef(self, schema_path):
        schema = Schema.load(schema_path)
        kd = schema.get("env.editor")
        assert kd is not None
        assert kd.canonical_key == "env.editor"
        assert kd.type == "env"
        assert "editor" in kd.aliases
