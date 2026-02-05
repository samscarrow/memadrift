from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from memadrift.models import (
    Impact,
    MemoryItem,
    MemoryType,
    Scope,
    Source,
    Status,
    VerifyMode,
)

RECORD_RE = re.compile(
    r"^(mem_[A-Z2-7]{8})\s*\|\s*(\w+)\s*\|\s*scope=(\S+)\s*\|\s*key=(\S+)"
    r"\s*\|\s*value=(.+?)\s*\|\s*src=(\w+)\s*\|\s*status=(\w+)"
    r"\s*\|\s*last_verified=(\S+)\s*\|\s*ttl_days=(\d+)"
    r"\s*\|\s*verify_mode=(\w+)\s*\|\s*impact=(\w+)\s*$"
)


class ParseError(Exception):
    def __init__(self, message: str, line_number: int | None = None):
        self.line_number = line_number
        super().__init__(
            f"Line {line_number}: {message}" if line_number else message
        )


@dataclass
class MemoryFile:
    frontmatter: dict
    items: list[MemoryItem] = field(default_factory=list)
    path: Path | None = None


def _parse_last_verified(s: str) -> date | str:
    if s == "never":
        return "never"
    return date.fromisoformat(s)


def _format_last_verified(v: date | str) -> str:
    if isinstance(v, str):
        return v
    return v.isoformat()


class Parser:
    @staticmethod
    def read(path: Path | str) -> MemoryFile:
        path = Path(path)
        text = path.read_text()
        frontmatter, body = _split_frontmatter(text)
        items = _parse_body(body)
        return MemoryFile(frontmatter=frontmatter, items=items, path=path)

    @staticmethod
    def write(mf: MemoryFile, path: Path | str | None = None, *, backup: bool = True) -> None:
        path = Path(path) if path else mf.path
        if path is None:
            raise ValueError("No path specified for writing")

        if backup and path.exists():
            shutil.copy2(str(path), str(path.with_suffix(path.suffix + ".bak")))

        content = _render(mf)

        # Atomic write: write to temp file in same directory, then rename
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent, prefix=".memadrift_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _split_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break

    if end is None:
        return {}, text

    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    fm = yaml.safe_load(fm_text) or {}
    return fm, body


def _parse_body(body: str) -> list[MemoryItem]:
    items = []
    for lineno, line in enumerate(body.split("\n"), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = RECORD_RE.match(stripped)
        if not m:
            raise ParseError(f"Invalid record: {stripped!r}", line_number=lineno)
        items.append(_match_to_item(m, lineno))
    return items


def _match_to_item(m: re.Match, lineno: int) -> MemoryItem:
    try:
        return MemoryItem(
            id=m.group(1),
            type=MemoryType(m.group(2)),
            scope=Scope.parse(m.group(3)),
            key=m.group(4),
            value=m.group(5),
            src=Source(m.group(6)),
            status=Status(m.group(7)),
            last_verified=_parse_last_verified(m.group(8)),
            ttl_days=int(m.group(9)),
            verify_mode=VerifyMode(m.group(10)),
            impact=Impact(m.group(11)),
        )
    except (ValueError, KeyError) as e:
        raise ParseError(str(e), line_number=lineno) from e


def _render(mf: MemoryFile) -> str:
    parts = []
    # Frontmatter
    if mf.frontmatter:
        parts.append("---")
        parts.append(yaml.dump(mf.frontmatter, default_flow_style=False).rstrip())
        parts.append("---")
        parts.append("")

    # Records
    for item in mf.items:
        parts.append(_render_item(item))

    # Trailing newline
    parts.append("")
    return "\n".join(parts)


def _render_item(item: MemoryItem) -> str:
    return (
        f"{item.id} | {item.type.value} | scope={item.scope} | key={item.key}"
        f" | value={item.value} | src={item.src.value} | status={item.status.value}"
        f" | last_verified={_format_last_verified(item.last_verified)}"
        f" | ttl_days={item.ttl_days} | verify_mode={item.verify_mode.value}"
        f" | impact={item.impact.value}"
    )
