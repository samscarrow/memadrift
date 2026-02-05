from memadrift.models import (
    Impact,
    MemoryItem,
    MemoryType,
    Scope,
    Source,
    Status,
    VerifyMode,
)
from datetime import date


class TestScope:
    def test_parse_global(self):
        s = Scope.parse("global")
        assert s.kind == "global"
        assert s.qualifier is None

    def test_parse_machine(self):
        s = Scope.parse("machine:devbox")
        assert s.kind == "machine"
        assert s.qualifier == "devbox"

    def test_parse_repo(self):
        s = Scope.parse("repo:/home/sam/projects/memadrift")
        assert s.kind == "repo"
        assert s.qualifier == "/home/sam/projects/memadrift"

    def test_roundtrip_global(self):
        assert str(Scope.parse("global")) == "global"

    def test_roundtrip_machine(self):
        assert str(Scope.parse("machine:devbox")) == "machine:devbox"

    def test_roundtrip_repo_with_colons(self):
        """Colons in qualifier are preserved."""
        scope_str = "repo:/path/with:colon"
        assert str(Scope.parse(scope_str)) == scope_str

    def test_qualifier_with_multiple_colons(self):
        s = Scope.parse("machine:host:extra:stuff")
        assert s.kind == "machine"
        assert s.qualifier == "host:extra:stuff"


class TestEnums:
    def test_memory_type_values(self):
        assert set(m.value for m in MemoryType) == {
            "pref", "fact", "policy", "env", "workflow"
        }

    def test_source_values(self):
        assert set(s.value for s in Source) == {
            "user", "tool", "inferred", "doc"
        }

    def test_status_values(self):
        assert set(s.value for s in Status) == {
            "active", "suspect", "deprecated"
        }

    def test_verify_mode_values(self):
        assert set(v.value for v in VerifyMode) == {
            "auto", "human", "external"
        }

    def test_impact_values(self):
        assert set(i.value for i in Impact) == {"low", "med", "high"}


class TestMemoryItem:
    def test_create_item(self):
        item = MemoryItem(
            id="mem_ABCDEFGH",
            type=MemoryType.ENV,
            scope=Scope.parse("global"),
            key="env.editor",
            value="vim",
            src=Source.TOOL,
            status=Status.ACTIVE,
            last_verified=date(2025, 1, 15),
            ttl_days=30,
            verify_mode=VerifyMode.AUTO,
            impact=Impact.LOW,
        )
        assert item.key == "env.editor"
        assert item.value == "vim"

    def test_ref_default_none(self):
        item = MemoryItem(
            id="mem_ABCDEFGH",
            type=MemoryType.ENV,
            scope=Scope.parse("global"),
            key="env.editor",
            value="vim",
            src=Source.TOOL,
            status=Status.ACTIVE,
            last_verified=date(2025, 1, 15),
            ttl_days=30,
            verify_mode=VerifyMode.AUTO,
            impact=Impact.LOW,
        )
        assert item.ref is None

    def test_ref_explicit_value(self):
        item = MemoryItem(
            id="mem_ABCDEFGH",
            type=MemoryType.ENV,
            scope=Scope.parse("global"),
            key="env.editor",
            value="vim",
            src=Source.TOOL,
            status=Status.ACTIVE,
            last_verified=date(2025, 1, 15),
            ttl_days=30,
            verify_mode=VerifyMode.AUTO,
            impact=Impact.LOW,
            ref="archive.md#mem_ABCDEFGH",
        )
        assert item.ref == "archive.md#mem_ABCDEFGH"

    def test_last_verified_never(self):
        item = MemoryItem(
            id="mem_ABCDEFGH",
            type=MemoryType.PREF,
            scope=Scope.parse("global"),
            key="user.name",
            value="Sam",
            src=Source.USER,
            status=Status.ACTIVE,
            last_verified="never",
            ttl_days=90,
            verify_mode=VerifyMode.HUMAN,
            impact=Impact.MED,
        )
        assert item.last_verified == "never"
