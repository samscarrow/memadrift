import re

from memadrift.ids import generate_id

ID_PATTERN = re.compile(r"^mem_[A-Z2-7]{8}$")


class TestGenerateId:
    def test_format(self):
        """ID matches expected format."""
        result = generate_id("env", "global", "env.editor")
        assert ID_PATTERN.match(result), f"ID {result!r} doesn't match pattern"

    def test_deterministic(self):
        """Same inputs always produce same ID."""
        id1 = generate_id("env", "global", "env.editor")
        id2 = generate_id("env", "global", "env.editor")
        assert id1 == id2

    def test_different_type(self):
        """Different type produces different ID."""
        id1 = generate_id("env", "global", "env.editor")
        id2 = generate_id("pref", "global", "env.editor")
        assert id1 != id2

    def test_different_scope(self):
        """Different scope produces different ID."""
        id1 = generate_id("env", "global", "env.editor")
        id2 = generate_id("env", "machine:devbox", "env.editor")
        assert id1 != id2

    def test_different_key(self):
        """Different key produces different ID."""
        id1 = generate_id("env", "global", "env.editor")
        id2 = generate_id("env", "global", "env.shell")
        assert id1 != id2

    def test_stability(self):
        """ID is stable — known input produces known output."""
        result = generate_id("env", "global", "env.editor")
        # Just verify it's consistent, not what the exact value is
        assert result == generate_id("env", "global", "env.editor")
        assert len(result) == 12  # "mem_" (4) + 8 chars

    def test_prefix(self):
        """All IDs start with 'mem_'."""
        result = generate_id("pref", "machine:laptop", "user.name")
        assert result.startswith("mem_")
