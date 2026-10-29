"""Retiring an old readable filename must not discard a racing writer."""
import pytest

from jotline import store
from jotline.cli_doctor import doctor_report
from jotline.history import DISPLACED_PREFIX


def _readable_note(tmp_path, *, blocked_history=False):
    if blocked_history:
        (tmp_path / ".jotline-history").write_text("history is unavailable")
    vault = store.Vault(tmp_path)
    vault.readable_filenames = True
    note = vault.new("Original title")
    vault.save(note)
    return vault, note, vault.file(note.id)


def test_retitle_keeps_external_edit_when_history_warning_already_exists(tmp_path, monkeypatch):
    vault, note, old_path = _readable_note(tmp_path, blocked_history=True)
    assert any("history is not being kept" in warning for warning in vault.sticky_warnings)
    external = note.original.replace("Original title", "External writer's only copy")
    publish = store.publish_new

    def publish_then_edit(directory, source, target):
        publish(directory, source, target)
        old_path.write_text(external)

    monkeypatch.setattr(store, "publish_new", publish_then_edit)
    note.body = "New title"
    vault.save(note)

    assert vault.read(note.id).body == "New title"
    candidates = [old_path, *tmp_path.glob(f"{DISPLACED_PREFIX}*")]
    assert any(path.is_file() and path.read_text() == external for path in candidates)
    assert any("retained" in warning or "kept" in warning for warning in vault.sticky_warnings)
    assert not any("was preserved in note history" in warning for warning in vault.warnings)
    report = doctor_report(vault, "")
    assert report["ancillary"]["displaced"]["count"] == 1


def test_retitle_does_not_unlink_a_file_created_after_the_retirement_read(tmp_path, monkeypatch):
    vault, note, old_path = _readable_note(tmp_path)
    external = note.original.replace("Original title", "Late external writer's only copy")
    publish = store.publish_new
    read = store.read_regular_at
    published = False
    raced = False

    def observe_publication(directory, source, target):
        nonlocal published
        publish(directory, source, target)
        published = True

    def read_then_edit(directory, name, *args, **kwargs):
        nonlocal raced
        raw = read(directory, name, *args, **kwargs)
        if published and not raced and (name == old_path.name or name.startswith(DISPLACED_PREFIX)):
            raced = True
            old_path.write_text(external)
        return raw

    monkeypatch.setattr(store, "publish_new", observe_publication)
    monkeypatch.setattr(store, "read_regular_at", read_then_edit)
    note.body = "New title"
    vault.save(note)

    assert raced
    assert old_path.is_file() and old_path.read_text() == external
    assert vault.read(note.id).body == "New title"


@pytest.mark.parametrize("timing", ["before", "after"])
def test_retitle_preserves_external_replacement_around_displacement(tmp_path, monkeypatch, timing):
    vault, note, old_path = _readable_note(tmp_path)
    external = note.original.replace("Original title", "Concurrent replacement")
    replace = store.replace_at
    raced = False

    def replace_around_edit(directory, source, target):
        nonlocal raced
        if source == old_path.name:
            raced = True
            if timing == "before":
                old_path.write_text(external)
            replace(directory, source, target)
            if timing == "after":
                old_path.write_text(external)
        else:
            replace(directory, source, target)

    monkeypatch.setattr(store, "replace_at", replace_around_edit)
    note.body = "New title"
    vault.save(note)
    assert raced
    assert vault.read(note.id).body == "New title"
    if timing == "before":
        assert any(vault.read_revision(note.id, revision.id).body == "Concurrent replacement"
                   for revision in vault.history(note.id))
    else:
        assert old_path.read_text() == external


def test_retitle_does_not_follow_a_racing_symlink(tmp_path, monkeypatch):
    vault, note, old_path = _readable_note(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.write_text("Do not read or replace me")
    publish = store.publish_new

    def publish_then_link(directory, source, target):
        publish(directory, source, target)
        old_path.unlink()
        old_path.symlink_to(outside)

    monkeypatch.setattr(store, "publish_new", publish_then_link)
    note.body = "New title"
    vault.save(note)
    assert outside.read_text() == "Do not read or replace me"
    displaced = list(tmp_path.glob(f"{DISPLACED_PREFIX}*"))
    assert len(displaced) == 1 and displaced[0].is_symlink()
    assert vault.read(note.id).body == "New title"
    assert any(displaced[0].name in warning for warning in vault.sticky_warnings)


def test_retirement_uses_pinned_directory_after_vault_path_swap(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    vault, note, old_path = _readable_note(root)
    retained = tmp_path / "retained"
    replace = store.replace_at

    def swap_path(directory, source, target):
        if source == old_path.name:
            root.rename(retained)
            root.mkdir()
            (root / old_path.name).write_text("Outside replacement")
        replace(directory, source, target)

    monkeypatch.setattr(store, "replace_at", swap_path)
    note.body = "New title"
    vault.save(note)
    assert (root / old_path.name).read_text() == "Outside replacement"
    assert store.Vault(retained).read(note.id).body == "New title"
    assert not (retained / old_path.name).exists()


@pytest.mark.parametrize("readable", [False, True])
def test_encrypting_preserves_a_concurrent_plaintext_edit(tmp_path, monkeypatch, readable):
    pytest.importorskip("cryptography")
    vault = store.Vault(tmp_path)
    vault.setup_encryption("correct horse", n=2**10)
    vault.readable_filenames = readable
    note = vault.new("Original title")
    vault.save(note)
    old_path = vault.file(note.id)
    external = note.original.replace("Original title", "Only external plaintext copy")
    publish = store.publish_new

    def publish_then_edit_original(directory, source, target):
        publish(directory, source, target)
        original = old_path if readable else next(tmp_path.glob(f"{DISPLACED_PREFIX}*"))
        original.write_text(external)

    monkeypatch.setattr(store, "publish_new", publish_then_edit_original)
    vault.set_encrypted(note.id, "default", True)
    assert vault.read(note.id).encrypted
    displaced = list(tmp_path.glob(f"{DISPLACED_PREFIX}*"))
    assert len(displaced) == 1 and displaced[0].read_text() == external
    assert any("unencrypted" in warning and displaced[0].name in warning for warning in vault.sticky_warnings)
    assert doctor_report(vault, "")["ancillary"]["displaced"]["files"] == [displaced[0].name]
    assert all(vault.read_revision(note.id, revision.id).encrypted for revision in vault.history(note.id))
