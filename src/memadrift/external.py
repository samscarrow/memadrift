from __future__ import annotations

import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from memadrift.reality import DriftResult, DriftVerdict, VerificationSource


class ExternalSource(VerificationSource):
    """Handles http_json:URL|field and http_status:URL source prefixes."""

    def __init__(self, timeout: int = 10):
        self._timeout = timeout

    def can_check(self, source_id: str) -> bool:
        prefix = source_id.split(":", 1)[0] if ":" in source_id else source_id
        return prefix in ("http_json", "http_status")

    def check(self, source_id: str, expected: str) -> DriftResult:
        if ":" not in source_id:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"Malformed source_id: {source_id}",
            )
        prefix, arg = source_id.split(":", 1)
        if prefix == "http_json":
            return self._check_http_json(arg, expected)
        if prefix == "http_status":
            return self._check_http_status(arg, expected)
        return DriftResult(
            verdict=DriftVerdict.UNVERIFIABLE,
            expected=expected,
            actual=None,
            evidence=f"Unknown prefix: {prefix}",
        )

    def _check_http_json(self, arg: str, expected: str) -> DriftResult:
        if "|" not in arg:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"http_json requires URL|field format, got: {arg}",
            )
        url, field = arg.rsplit("|", 1)
        try:
            req = Request(url)
            with urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read())
        except (URLError, OSError, json.JSONDecodeError, ValueError) as e:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"HTTP request failed: {e}",
            )
        actual = str(data.get(field, ""))
        if not actual:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"Field {field!r} not found in response",
            )
        if actual == expected:
            return DriftResult(
                verdict=DriftVerdict.MATCH,
                expected=expected,
                actual=actual,
                evidence=f"http_json {field} == {expected!r}",
            )
        return DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected=expected,
            actual=actual,
            evidence=f"http_json {field}: expected {expected!r}, got {actual!r}",
        )

    def _check_http_status(self, url: str, expected: str) -> DriftResult:
        try:
            req = Request(url, method="HEAD")
            with urlopen(req, timeout=self._timeout) as resp:
                actual = str(resp.status)
        except (URLError, OSError) as e:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"HTTP request failed: {e}",
            )
        if actual == expected:
            return DriftResult(
                verdict=DriftVerdict.MATCH,
                expected=expected,
                actual=actual,
                evidence=f"http_status == {expected}",
            )
        return DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected=expected,
            actual=actual,
            evidence=f"http_status: expected {expected!r}, got {actual!r}",
        )


def _github_api(path: str, token: str | None = None, timeout: int = 10) -> dict:
    """Make an authenticated GitHub API request. Raises on error."""
    url = f"https://api.github.com/{path.lstrip('/')}"
    req = Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class GitHubSource(VerificationSource):
    """Handles github_repo, github_branch, github_visibility source prefixes."""

    def __init__(self, timeout: int = 10):
        self._timeout = timeout

    def can_check(self, source_id: str) -> bool:
        prefix = source_id.split(":", 1)[0] if ":" in source_id else source_id
        return prefix in ("github_repo", "github_branch", "github_visibility")

    def check(self, source_id: str, expected: str) -> DriftResult:
        if ":" not in source_id:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"Malformed source_id: {source_id}",
            )
        prefix, repo = source_id.split(":", 1)
        token = os.environ.get("GITHUB_TOKEN")
        try:
            data = _github_api(f"repos/{repo}", token=token, timeout=self._timeout)
        except (URLError, OSError, json.JSONDecodeError, ValueError) as e:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"GitHub API failed: {e}",
            )

        if prefix == "github_repo":
            actual = data.get("full_name", "")
        elif prefix == "github_branch":
            actual = data.get("default_branch", "")
        elif prefix == "github_visibility":
            actual = "private" if data.get("private") else "public"
        else:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"Unknown GitHub prefix: {prefix}",
            )

        if actual == expected:
            return DriftResult(
                verdict=DriftVerdict.MATCH,
                expected=expected,
                actual=actual,
                evidence=f"{prefix} == {expected!r}",
            )
        return DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected=expected,
            actual=actual,
            evidence=f"{prefix}: expected {expected!r}, got {actual!r}",
        )
