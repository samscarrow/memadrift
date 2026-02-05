from __future__ import annotations

import io
import json
from unittest.mock import patch
from urllib.error import URLError

import pytest

from memadrift.external import ExternalSource, GitHubSource, _github_api
from memadrift.reality import DriftVerdict


class TestExternalSourceCanCheck:
    def test_http_json(self):
        src = ExternalSource()
        assert src.can_check("http_json:https://example.com/api|name") is True

    def test_http_status(self):
        src = ExternalSource()
        assert src.can_check("http_status:https://example.com") is True

    def test_unknown(self):
        src = ExternalSource()
        assert src.can_check("env_var:EDITOR") is False


class TestExternalSourceHttpJson:
    def _mock_urlopen(self, data):
        """Return a context manager that yields a fake response."""
        body = json.dumps(data).encode()
        resp = io.BytesIO(body)
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: None
        return resp

    def test_match(self):
        src = ExternalSource()
        with patch("memadrift.external.urlopen") as mock:
            mock.return_value = self._mock_urlopen({"version": "1.2.3"})
            result = src.check("http_json:https://api.example.com/info|version", "1.2.3")
        assert result.verdict == DriftVerdict.MATCH

    def test_contradiction(self):
        src = ExternalSource()
        with patch("memadrift.external.urlopen") as mock:
            mock.return_value = self._mock_urlopen({"version": "2.0.0"})
            result = src.check("http_json:https://api.example.com/info|version", "1.2.3")
        assert result.verdict == DriftVerdict.CONTRADICTION
        assert result.actual == "2.0.0"

    def test_network_error(self):
        src = ExternalSource()
        with patch("memadrift.external.urlopen") as mock:
            mock.side_effect = URLError("connection refused")
            result = src.check("http_json:https://api.example.com/info|version", "1.2.3")
        assert result.verdict == DriftVerdict.UNVERIFIABLE

    def test_missing_field(self):
        src = ExternalSource()
        with patch("memadrift.external.urlopen") as mock:
            mock.return_value = self._mock_urlopen({"other": "data"})
            result = src.check("http_json:https://api.example.com/info|version", "1.2.3")
        assert result.verdict == DriftVerdict.UNVERIFIABLE

    def test_malformed_no_pipe(self):
        src = ExternalSource()
        result = src.check("http_json:https://example.com", "val")
        assert result.verdict == DriftVerdict.UNVERIFIABLE


class TestExternalSourceHttpStatus:
    def test_match(self):
        src = ExternalSource()
        resp = io.BytesIO(b"")
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: None
        with patch("memadrift.external.urlopen") as mock:
            mock.return_value = resp
            result = src.check("http_status:https://example.com", "200")
        assert result.verdict == DriftVerdict.MATCH

    def test_network_error(self):
        src = ExternalSource()
        with patch("memadrift.external.urlopen") as mock:
            mock.side_effect = URLError("timeout")
            result = src.check("http_status:https://example.com", "200")
        assert result.verdict == DriftVerdict.UNVERIFIABLE


class TestGitHubSourceCanCheck:
    def test_github_repo(self):
        src = GitHubSource()
        assert src.can_check("github_repo:owner/repo") is True

    def test_github_branch(self):
        src = GitHubSource()
        assert src.can_check("github_branch:owner/repo") is True

    def test_github_visibility(self):
        src = GitHubSource()
        assert src.can_check("github_visibility:owner/repo") is True

    def test_unknown(self):
        src = GitHubSource()
        assert src.can_check("env_var:FOO") is False


class TestGitHubSourceCheck:
    def test_repo_match(self):
        src = GitHubSource()
        data = {"full_name": "samscarrow/memadrift", "default_branch": "master", "private": False}
        with patch("memadrift.external._github_api", return_value=data):
            result = src.check("github_repo:samscarrow/memadrift", "samscarrow/memadrift")
        assert result.verdict == DriftVerdict.MATCH

    def test_branch_contradiction(self):
        src = GitHubSource()
        data = {"full_name": "owner/repo", "default_branch": "main", "private": False}
        with patch("memadrift.external._github_api", return_value=data):
            result = src.check("github_branch:owner/repo", "master")
        assert result.verdict == DriftVerdict.CONTRADICTION
        assert result.actual == "main"

    def test_visibility_public(self):
        src = GitHubSource()
        data = {"full_name": "owner/repo", "default_branch": "main", "private": False}
        with patch("memadrift.external._github_api", return_value=data):
            result = src.check("github_visibility:owner/repo", "public")
        assert result.verdict == DriftVerdict.MATCH

    def test_visibility_private(self):
        src = GitHubSource()
        data = {"full_name": "owner/repo", "default_branch": "main", "private": True}
        with patch("memadrift.external._github_api", return_value=data):
            result = src.check("github_visibility:owner/repo", "private")
        assert result.verdict == DriftVerdict.MATCH

    def test_api_error(self):
        src = GitHubSource()
        with patch("memadrift.external._github_api", side_effect=URLError("forbidden")):
            result = src.check("github_repo:owner/repo", "owner/repo")
        assert result.verdict == DriftVerdict.UNVERIFIABLE

    def test_malformed_no_colon(self):
        src = GitHubSource()
        result = src.check("github_repo", "owner/repo")
        assert result.verdict == DriftVerdict.UNVERIFIABLE
