from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class KeyDef:
    canonical_key: str
    type: str
    sources: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)


class Schema:
    def __init__(self, keys: list[KeyDef]):
        self._keys: dict[str, KeyDef] = {}
        self._alias_map: dict[str, str] = {}
        for kd in keys:
            self._keys[kd.canonical_key] = kd
            self._alias_map[kd.canonical_key] = kd.canonical_key
            for alias in kd.aliases:
                self._alias_map[alias] = kd.canonical_key

    @classmethod
    def load(cls, path: Path | str) -> Schema:
        path = Path(path)
        data = yaml.safe_load(path.read_text())
        keys = []
        for key_name, defn in (data.get("keys") or {}).items():
            keys.append(
                KeyDef(
                    canonical_key=key_name,
                    type=defn.get("type", "string"),
                    sources=defn.get("sources", []),
                    aliases=defn.get("aliases", []),
                )
            )
        return cls(keys)

    def resolve(self, key: str) -> str | None:
        canonical = self._alias_map.get(key)
        return canonical

    def get(self, key: str) -> KeyDef | None:
        canonical = self.resolve(key)
        if canonical is None:
            return None
        return self._keys.get(canonical)

    def sources_for(self, key: str) -> list[str]:
        kd = self.get(key)
        if kd is None:
            return []
        return kd.sources
