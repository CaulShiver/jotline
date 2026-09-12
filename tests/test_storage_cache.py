"""A bounded note cache must retain the same freshness and safety semantics."""
import os

import pytest

from jotline import store
from jotline.store import ConflictError, Vault


def count_reads(vault, monkeypatch):
    reads = []
    original = vault.read

    def counted(note_id):
        reads.append(note_id)
        return original(note_id)

    monkeypatch.setattr(vault, "read", counted)
    return reads


def test_unchanged_searches_reuse_parse_and_refresh_can_force_read(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    (tmp_path / "note.md").write_text("hello #work")
    reads = count_reads(vault, monkeypatch)
    assert len(vault.search("hello")) == 1
    assert len(vault.search("#work")) == 1
    assert reads == ["note"]
    vault.invalidate_cache()
    assert len(vault.search()) == 1
    assert reads == ["note", "note"]


def test_cache_detects_same_size_edit_even_when_mtime_restored(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    path = tmp_path / "note.md"
    path.write_text("alpha")
    clock = [100.0]
    monkeypatch.setattr(store, "monotonic", lambda: clock[0])
    assert vault.notes()[0].body == "alpha"
    signature = store.file_signature(path)
    before = path.stat()
    path.write_text("omega")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    if store.file_signature(path) != signature:
        assert vault.notes()[0].body == "omega"
    else:
        # Native timestamps may share a clock tick. Even when metadata cannot
        # identify the edit, the next scan after the deadline must reread it.
        clock[0] += store.CACHE_TTL_SECONDS
        assert vault.notes()[0].body == "omega"
    vault.invalidate_cache()
    assert vault.notes()[0].body == "omega"


def test_unchanged_signature_expires_from_real_read_not_cache_hit(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    path = tmp_path / "note.md"
    path.write_text("alpha")
    signature = store.file_signature(path)
    clock = [100.0]
    monkeypatch.setattr(store, "file_signature", lambda path: signature)
    monkeypatch.setattr(store, "monotonic", lambda: clock[0])
    reads = count_reads(vault, monkeypatch)
    assert vault.notes()[0].body == "alpha"
    path.write_text("omega")
    for fraction in (0.25, 0.5, 0.75):
        clock[0] = 100.0 + store.CACHE_TTL_SECONDS * fraction
        assert vault.notes()[0].body == "alpha"
    assert reads == ["note"]
    clock[0] = 100.0 + store.CACHE_TTL_SECONDS
    assert vault.notes()[0].body == "omega"
    assert reads == ["note", "note"]
    # Explicit refresh bypasses even an unexpired identical signature.
    path.write_text("delta")
    vault.invalidate_cache()
    assert vault.notes()[0].body == "delta"
    assert reads == ["note", "note", "note"]


def test_cache_tracks_added_deleted_and_atomically_replaced_notes(tmp_path):
    vault = Vault(tmp_path)
    first = tmp_path / "first.md"
    first.write_text("first")
    assert len(vault.notes()) == 1
    (tmp_path / "second.md").write_text("second")
    replacement = tmp_path / "replacement"
    replacement.write_text("changed")
    os.replace(replacement, first)
    assert {n.id: n.body for n in vault.notes()} == {"first": "changed", "second": "second"}
    first.unlink()
    assert [n.id for n in vault.notes()] == ["second"]
    assert "first" not in vault._cache


def test_mutating_returned_notes_does_not_change_cache_or_disk(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("original #work")
    vault.save(note)
    returned = vault.search()[0]
    returned.body = "corrupted #other"
    returned.collection = "trash"
    returned.original = "wrong baseline"
    returned.id = "wrong-id"
    pristine = vault.search("#work")[0]
    assert pristine.id == note.id
    assert pristine.body == "original #work"
    assert pristine.collection == "inbox"
    assert pristine.original == note.original
    assert vault.read(note.id).body == pristine.body


@pytest.mark.parametrize("replacement", ["symlink", "fifo", "malformed"])
def test_cache_never_masks_unsafe_or_malformed_replacements(tmp_path, replacement):
    vault = Vault(tmp_path / "vault")
    path = vault.file("note")
    path.write_text("safe original")
    assert len(vault.notes()) == 1
    path.unlink()
    if replacement == "symlink":
        outside = tmp_path / "outside"
        outside.write_text("private outside")
        path.symlink_to(outside)
    elif replacement == "fifo":
        os.mkfifo(path)
    else:
        path.write_text("---\njotline: 1\nstarred: broken\n---\nbody")
    for _ in range(2):
        assert vault.notes() == []
        assert len(vault.warnings) == 1
    assert "note" not in vault._cache


def test_cache_does_not_weaken_direct_read_or_save_conflicts(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("original")
    vault.save(note)
    cached = vault.notes()[0]
    external = Vault(tmp_path).read(note.id)
    external.body = "external edit"
    Vault(tmp_path).save(external)
    assert vault.read(note.id).body == "external edit"
    cached.body = "local edit"
    with pytest.raises(ConflictError):
        vault.save(cached)
    assert vault.search()[0].body == "external edit"


def test_cache_entry_and_memory_limits_leave_all_notes_searchable(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    for index in range(3):
        (tmp_path / f"note{index}.md").write_text(f"body {index}")
    monkeypatch.setattr(store, "MAX_CACHED_NOTES", 1)
    assert len(vault.search()) == 3
    assert len(vault._cache) == 1
    reads = count_reads(vault, monkeypatch)
    assert len(vault.search()) == 3
    assert len(reads) == 2
    monkeypatch.setattr(store, "MAX_CACHE_BYTES", 0)
    assert len(vault.search()) == 3
    assert not vault._cache
    reads.clear()
    assert len(vault.search()) == 3
    assert len(reads) == 3
