from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class MemoryType(Enum):
    PREF = "pref"
    FACT = "fact"
    POLICY = "policy"
    ENV = "env"
    WORKFLOW = "workflow"


class Source(Enum):
    USER = "user"
    TOOL = "tool"
    INFERRED = "inferred"
    DOC = "doc"


class Status(Enum):
    ACTIVE = "active"
    SUSPECT = "suspect"
    DEPRECATED = "deprecated"


class VerifyMode(Enum):
    AUTO = "auto"
    HUMAN = "human"
    EXTERNAL = "external"


class Impact(Enum):
    LOW = "low"
    MED = "med"
    HIGH = "high"


@dataclass
class Scope:
    kind: str  # "global", "machine", "repo"
    qualifier: str | None = None  # hostname for machine, path for repo

    @classmethod
    def parse(cls, s: str) -> Scope:
        if ":" in s:
            kind, qualifier = s.split(":", 1)
            return cls(kind=kind, qualifier=qualifier)
        return cls(kind=s)

    def __str__(self) -> str:
        if self.qualifier is not None:
            return f"{self.kind}:{self.qualifier}"
        return self.kind


@dataclass
class MemoryItem:
    id: str
    type: MemoryType
    scope: Scope
    key: str
    value: str
    src: Source
    status: Status
    last_verified: date | str  # date or "never"
    ttl_days: int
    verify_mode: VerifyMode
    impact: Impact
    ref: str | None = None
