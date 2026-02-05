import os
from pathlib import Path

from memadrift.secrets import load_env


class TestLoadEnv:
    def test_basic_load(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        # Remove if already set
        monkeypatch.delenv("FOO", raising=False)
        monkeypatch.delenv("BAZ", raising=False)
        loaded = load_env(env_file)
        assert loaded == {"FOO": "bar", "BAZ": "qux"}
        assert os.environ["FOO"] == "bar"
        assert os.environ["BAZ"] == "qux"

    def test_comments_skipped(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nKEY=val\n# another\n")
        monkeypatch.delenv("KEY", raising=False)
        loaded = load_env(env_file)
        assert loaded == {"KEY": "val"}

    def test_no_override_existing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EXISTING", "original")
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=new_value\n")
        loaded = load_env(env_file)
        assert loaded == {}
        assert os.environ["EXISTING"] == "original"

    def test_missing_file(self, tmp_path):
        loaded = load_env(tmp_path / "nonexistent.env")
        assert loaded == {}

    def test_quoted_values(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text('DQ="double quoted"\nSQ=\'single quoted\'\n')
        monkeypatch.delenv("DQ", raising=False)
        monkeypatch.delenv("SQ", raising=False)
        loaded = load_env(env_file)
        assert loaded["DQ"] == "double quoted"
        assert loaded["SQ"] == "single quoted"

    def test_blank_lines_skipped(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nABC=123\n\n")
        monkeypatch.delenv("ABC", raising=False)
        loaded = load_env(env_file)
        assert loaded == {"ABC": "123"}
