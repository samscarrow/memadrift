from __future__ import annotations

import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DriftVerdict(Enum):
    MATCH = "match"
    CONTRADICTION = "contradiction"
    UNVERIFIABLE = "unverifiable"


@dataclass
class DriftResult:
    verdict: DriftVerdict
    expected: str
    actual: str | None
    evidence: str


class VerificationSource(ABC):
    @abstractmethod
    def can_check(self, source_id: str) -> bool: ...

    @abstractmethod
    def check(self, source_id: str, expected: str) -> DriftResult: ...


class LocalEnvSource(VerificationSource):
    def can_check(self, source_id: str) -> bool:
        prefix = source_id.split(":", 1)[0] if ":" in source_id else source_id
        return prefix in ("env_var", "git_config", "path_exists", "binary_exists")

    def check(self, source_id: str, expected: str) -> DriftResult:
        if ":" not in source_id:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"Malformed source_id: {source_id}",
            )
        prefix, arg = source_id.split(":", 1)
        dispatch = {
            "env_var": self._check_env_var,
            "git_config": self._check_git_config,
            "path_exists": self._check_path_exists,
            "binary_exists": self._check_binary_exists,
        }
        handler = dispatch.get(prefix)
        if handler is None:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"Unknown source prefix: {prefix}",
            )
        return handler(arg, expected)

    def _check_env_var(self, var_name: str, expected: str) -> DriftResult:
        actual = os.environ.get(var_name)
        if actual is None:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"Environment variable {var_name} is not set",
            )
        if actual == expected:
            return DriftResult(
                verdict=DriftVerdict.MATCH,
                expected=expected,
                actual=actual,
                evidence=f"${var_name} == {expected!r}",
            )
        return DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected=expected,
            actual=actual,
            evidence=f"${var_name}: expected {expected!r}, got {actual!r}",
        )

    def _check_git_config(self, key: str, expected: str) -> DriftResult:
        if shutil.which("git") is None:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence="git binary not found in PATH",
            )
        try:
            result = subprocess.run(
                ["git", "config", "--global", key],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"git config timed out",
            )
        if result.returncode != 0:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence=f"git config --global {key} returned exit code {result.returncode}",
            )
        actual = result.stdout.strip()
        if actual == expected:
            return DriftResult(
                verdict=DriftVerdict.MATCH,
                expected=expected,
                actual=actual,
                evidence=f"git config {key} == {expected!r}",
            )
        return DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected=expected,
            actual=actual,
            evidence=f"git config {key}: expected {expected!r}, got {actual!r}",
        )

    def _check_path_exists(self, path_str: str, expected: str) -> DriftResult:
        expanded = os.path.expanduser(path_str)
        exists = Path(expanded).exists()
        if exists:
            return DriftResult(
                verdict=DriftVerdict.MATCH,
                expected=expected,
                actual=expanded,
                evidence=f"Path {expanded} exists",
            )
        return DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected=expected,
            actual=None,
            evidence=f"Path {expanded} does not exist",
        )

    def _check_binary_exists(self, name: str, expected: str) -> DriftResult:
        path = shutil.which(name)
        if path is not None:
            return DriftResult(
                verdict=DriftVerdict.MATCH,
                expected=expected,
                actual=path,
                evidence=f"Binary {name} found at {path}",
            )
        return DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected=expected,
            actual=None,
            evidence=f"Binary {name} not found in PATH",
        )


class UserSource(VerificationSource):
    """Verification via user prompt. Injectable prompt_fn for testing."""

    def __init__(self, prompt_fn=None):
        if prompt_fn is None:
            self._prompt_fn = self._default_prompt
        else:
            self._prompt_fn = prompt_fn

    def can_check(self, source_id: str) -> bool:
        return source_id == "user_confirm"

    def check(self, source_id: str, expected: str) -> DriftResult:
        response = self._prompt_fn(expected)
        if response is None:
            return DriftResult(
                verdict=DriftVerdict.UNVERIFIABLE,
                expected=expected,
                actual=None,
                evidence="User declined to verify",
            )
        if response == expected:
            return DriftResult(
                verdict=DriftVerdict.MATCH,
                expected=expected,
                actual=response,
                evidence="User confirmed value",
            )
        return DriftResult(
            verdict=DriftVerdict.CONTRADICTION,
            expected=expected,
            actual=response,
            evidence=f"User provided different value: {response!r}",
        )

    @staticmethod
    def _default_prompt(expected: str) -> str | None:
        try:
            response = input(f"Is '{expected}' still correct? [y/N/new value]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if response.lower() == "y":
            return expected
        if response.lower() in ("n", ""):
            return None
        return response
