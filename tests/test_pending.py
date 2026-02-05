import json

from memadrift.pending import add_to_queue, read_queue, remove_from_queue, write_queue


class TestReadQueue:
    def test_read_empty_nonexistent(self, tmp_path):
        result = read_queue(tmp_path / "queue.json")
        assert result == []

    def test_read_empty_file(self, tmp_path):
        path = tmp_path / "queue.json"
        path.write_text("")
        result = read_queue(path)
        assert result == []


class TestWriteReadRoundtrip:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "queue.json"
        entries = [
            {
                "item_id": "mem_AAAAAAAA",
                "key": "env.editor",
                "current_value": "vim",
                "verify_mode": "auto",
                "source_file": "MEMORY.md",
                "queued_at": "2025-01-15T00:00:00+00:00",
                "evidence": "no source found",
            }
        ]
        write_queue(entries, path)
        loaded = read_queue(path)
        assert len(loaded) == 1
        assert loaded[0]["item_id"] == "mem_AAAAAAAA"


class TestAddToQueue:
    def test_add_new(self, tmp_path):
        path = tmp_path / "queue.json"
        add_to_queue(
            item_id="mem_AAAAAAAA",
            key="env.editor",
            current_value="vim",
            verify_mode="auto",
            source_file="MEMORY.md",
            evidence="no source",
            path=path,
        )
        entries = read_queue(path)
        assert len(entries) == 1
        assert entries[0]["item_id"] == "mem_AAAAAAAA"
        assert "queued_at" in entries[0]

    def test_add_dedup(self, tmp_path):
        path = tmp_path / "queue.json"
        add_to_queue(
            item_id="mem_AAAAAAAA",
            key="env.editor",
            current_value="vim",
            verify_mode="auto",
            source_file="MEMORY.md",
            evidence="first",
            path=path,
        )
        add_to_queue(
            item_id="mem_AAAAAAAA",
            key="env.editor",
            current_value="vim",
            verify_mode="auto",
            source_file="MEMORY.md",
            evidence="second",
            path=path,
        )
        entries = read_queue(path)
        assert len(entries) == 1
        # Keeps the first one
        assert entries[0]["evidence"] == "first"

    def test_add_multiple_different(self, tmp_path):
        path = tmp_path / "queue.json"
        add_to_queue("mem_AAAAAAAA", "k1", "v1", "auto", "f.md", "e1", path)
        add_to_queue("mem_BBBBBBBB", "k2", "v2", "human", "f.md", "e2", path)
        entries = read_queue(path)
        assert len(entries) == 2


class TestRemoveFromQueue:
    def test_remove_found(self, tmp_path):
        path = tmp_path / "queue.json"
        add_to_queue("mem_AAAAAAAA", "k", "v", "auto", "f.md", "e", path)
        removed = remove_from_queue("mem_AAAAAAAA", path)
        assert removed is True
        assert read_queue(path) == []

    def test_remove_not_found(self, tmp_path):
        path = tmp_path / "queue.json"
        add_to_queue("mem_AAAAAAAA", "k", "v", "auto", "f.md", "e", path)
        removed = remove_from_queue("mem_ZZZZZZZZ", path)
        assert removed is False
        assert len(read_queue(path)) == 1
