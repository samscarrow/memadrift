import os

import pytest

from memadrift.reality import DriftVerdict, LocalEnvSource, UserSource


class TestLocalEnvEnvVar:
    def test_match(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "expected_value")
        source = LocalEnvSource()
        result = source.check("env_var:TEST_VAR", "expected_value")
        assert result.verdict == DriftVerdict.MATCH

    def test_contradiction(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "actual_value")
        source = LocalEnvSource()
        result = source.check("env_var:TEST_VAR", "expected_value")
        assert result.verdict == DriftVerdict.CONTRADICTION
        assert result.actual == "actual_value"

    def test_unset(self, monkeypatch):
        monkeypatch.delenv("TEST_VAR_NONEXISTENT", raising=False)
        source = LocalEnvSource()
        result = source.check("env_var:TEST_VAR_NONEXISTENT", "something")
        assert result.verdict == DriftVerdict.UNVERIFIABLE


class TestLocalEnvBinary:
    def test_binary_exists(self):
        source = LocalEnvSource()
        result = source.check("binary_exists:python3", "python3")
        assert result.verdict == DriftVerdict.MATCH

    def test_binary_missing(self):
        source = LocalEnvSource()
        result = source.check("binary_exists:nonexistent_binary_xyz", "nonexistent_binary_xyz")
        assert result.verdict == DriftVerdict.CONTRADICTION


class TestLocalEnvPath:
    def test_path_exists(self, tmp_path):
        test_file = tmp_path / "testfile"
        test_file.touch()
        source = LocalEnvSource()
        result = source.check(f"path_exists:{test_file}", str(test_file))
        assert result.verdict == DriftVerdict.MATCH

    def test_path_missing(self):
        source = LocalEnvSource()
        result = source.check("path_exists:/nonexistent/path/xyz", "/nonexistent/path/xyz")
        assert result.verdict == DriftVerdict.CONTRADICTION


class TestLocalEnvCanCheck:
    def test_known_prefixes(self):
        source = LocalEnvSource()
        assert source.can_check("env_var:FOO") is True
        assert source.can_check("git_config:user.name") is True
        assert source.can_check("path_exists:/tmp") is True
        assert source.can_check("binary_exists:python") is True

    def test_unknown_prefix(self):
        source = LocalEnvSource()
        assert source.can_check("api_call:something") is False


class TestUserSource:
    def test_user_confirms(self):
        source = UserSource(prompt_fn=lambda expected: expected)
        result = source.check("user_confirm", "vim")
        assert result.verdict == DriftVerdict.MATCH

    def test_user_provides_different(self):
        source = UserSource(prompt_fn=lambda expected: "emacs")
        result = source.check("user_confirm", "vim")
        assert result.verdict == DriftVerdict.CONTRADICTION
        assert result.actual == "emacs"

    def test_user_declines(self):
        source = UserSource(prompt_fn=lambda expected: None)
        result = source.check("user_confirm", "vim")
        assert result.verdict == DriftVerdict.UNVERIFIABLE

    def test_can_check(self):
        source = UserSource()
        assert source.can_check("user_confirm") is True
        assert source.can_check("env_var:FOO") is False
