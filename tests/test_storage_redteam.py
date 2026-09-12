"""Regression cases from the storage review; all paths are temporary vaults."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
import json
from jotline.filesystem import fs as os
import stat
from threading import Barrier
import time

import pytest

from jotline import history, settings as settings_module, store
from jotline.settings import Settings
from jotline.store import ConflictError, Vault, read_regular_file


@pytest.mark.parametrize("body", ["", "   \n\t", "#", "###", "\n  ###  \nbody"])
def test_empty_heading_has_visible_title(tmp_path, body):
    assert Vault(tmp_path).new(body).title == "Untitled"


@pytest.mark.parametrize("kind", ["symlink", "dangling", "fifo", "directory"])
def test_unsafe_note_files_are_skipped_and_never_replaced(tmp_path, kind):
    vault = Vault(tmp_path / "vault")
    path = vault.file("unsafe")
    outside = tmp_path / "outside.md"
    outside.write_text("outside text")
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "dangling":
        path.symlink_to(tmp_path / "missing")
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    before = path.lstat()
    assert vault.notes() == []
    assert len(vault.warnings) == 1
    with pytest.raises(OSError):
        vault.save(replace(vault.new("replacement"), id="unsafe"))
    assert path.lstat().st_ino == before.st_ino
    assert outside.read_text() == "outside text"


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_settings_and_lock_special_files_fail_without_blocking(tmp_path, kind):
    vault = Vault(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text('{"theme": "nord"}')
    settings_path = tmp_path / ".jotline-settings.json"
    if kind == "symlink":
        settings_path.symlink_to(outside)
    else:
        os.mkfifo(settings_path)
    settings, warning = Settings.load(settings_path)
    assert settings == Settings() and warning
    with pytest.raises(OSError):
        settings.save(settings_path)
    settings_path.unlink()
    (tmp_path / ".jotline.lock").unlink()
    lock = tmp_path / ".jotline.lock"
    if kind == "symlink":
        lock.symlink_to(outside)
    else:
        os.mkfifo(lock)
    with pytest.raises(OSError):
        vault.save(vault.new("unsaved"))
    assert outside.read_text() == '{"theme": "nord"}'


def test_contended_lock_times_out_and_can_be_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOCK_TIMEOUT_SECONDS", 0.05)
    vault = Vault(tmp_path)
    note = vault.new("keep this")
    with vault.locked():
        start = time.monotonic()
        with pytest.raises(OSError, match="busy"):
            vault.save(note)
        assert time.monotonic() - start < 1
    assert note.original is None
    vault.save(note)
    assert vault.read(note.id).body == "keep this"


def test_nested_and_incomplete_metadata_leave_originals_untouched(tmp_path):
    vault = Vault(tmp_path)
    deeply_nested = "[" * 10000 + "true" + "]" * 10000
    path = tmp_path / "deep.md"
    raw = "---\njotline: 1\nstarred: " + deeply_nested + "\n---\nkeep me"
    path.write_text(raw)
    (tmp_path / "partial.md").write_text("---\njotline: 1\nstarred: true")
    assert vault.notes() == []
    assert len(vault.warnings) == 2
    assert path.read_text() == raw
    settings_path = tmp_path / ".jotline-settings.json"
    settings_path.write_text('{"unknown":' + deeply_nested + "}")
    settings, warning = Settings.load(settings_path)
    assert settings == Settings() and warning


def test_read_and_write_limits_preserve_existing_note(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("original")
    vault.save(note)
    raw = vault.file(note.id).read_bytes()
    monkeypatch.setattr(store, "MAX_NOTE_BYTES", 512)
    note.body = "x" * 513
    with pytest.raises(ValueError, match="limit"):
        vault.save(note)
    assert vault.file(note.id).read_bytes() == raw
    with (tmp_path / "huge.md").open("wb") as stream:
        stream.truncate(10 * 1024 * 1024 + 1)
    assert len(vault.notes()) == 1
    assert "limit" in vault.warnings[0]


def test_crlf_body_is_exact_and_newline_only_external_edit_conflicts(tmp_path):
    vault = Vault(tmp_path)
    path = vault.file("windows")
    raw = b'---\r\njotline: 1\r\ncollection: "resources"\r\n---\r\n# Title\r\n\r\nBody\r\n'
    path.write_bytes(raw)
    note = vault.read("windows")
    assert note.collection == "resources"
    assert note.body == "# Title\r\n\r\nBody\r\n"
    path.write_bytes(raw.replace(b"\r\n", b"\n"))
    note.body += "my edit"
    with pytest.raises(ConflictError):
        vault.save(note)


@pytest.mark.parametrize("first,second", [("\n", "\r\n"), ("\r\n", "\n")])
def test_mixed_header_newlines_keep_metadata_and_body(tmp_path, first, second):
    vault = Vault(tmp_path)
    raw = "---" + first + "jotline: 1" + second + 'collection: "resources"\n---\nBody\r\n'
    vault.file("mixed").write_bytes(raw.encode())
    note = vault.read("mixed")
    assert note.collection == "resources"
    assert note.body == "Body\r\n"


def test_file_limit_counts_bytes_and_allows_exact_boundary(tmp_path):
    path = tmp_path / "text.md"
    path.write_bytes("éé".encode())
    assert read_regular_file(path, 4) == "éé"
    path.write_bytes("ééx".encode())
    with pytest.raises(ValueError, match="limit"):
        read_regular_file(path, 4)


def test_ancestor_safe_reader_refuses_symlinked_directory(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "note.md").write_text("safe")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    assert read_regular_file(alias / "note.md") == "safe"
    with pytest.raises(OSError):
        read_regular_file(alias / "note.md", ancestor_safe=True)


def test_derived_metadata_budget_is_explicit_and_search_truncates_note(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_DERIVED_ITEMS", 2)
    vault = Vault(tmp_path)
    note = vault.new("#a #b #c")
    vault.save(note)
    assert note.tags == {"a", "b"}
    assert "results were truncated" in note.derived_warnings[0]
    assert [item.id for item in vault.search("#a")] == [note.id]
    assert any("results were truncated" in warning for warning in vault.warnings)


def test_atomic_replace_failure_keeps_file_and_baseline(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("original")
    vault.save(note)
    original = note.original
    note.body = "replacement"

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        vault.save(note)
    assert vault.read(note.id).body == "original"
    assert note.original == original
    assert not [path for path in tmp_path.glob(".jotline-*") if path.is_file()]


@pytest.mark.parametrize("helper", [store.replace_at, history._replace_at])
def test_descriptor_replace_never_retries_by_path(tmp_path, monkeypatch, helper):
    (tmp_path / "source").write_text("source")
    (tmp_path / "target").write_text("target")
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    calls = []

    def reject_keywords(*args, **kwargs):
        calls.append((args, kwargs))
        raise TypeError("dir_fd unsupported")

    monkeypatch.setattr(os, "replace", reject_keywords)
    try:
        with pytest.raises(TypeError, match="dir_fd unsupported"):
            helper(directory, "source", "target")
    finally:
        os.close(directory)
    assert len(calls) == 1
    assert calls[0][1] == {"src_dir_fd": directory, "dst_dir_fd": directory}
    assert (tmp_path / "source").read_text() == "source"
    assert (tmp_path / "target").read_text() == "target"


@pytest.mark.skipif(os.name == 'nt', reason='Windows pins directories against rename; covered by native tests')
def test_private_temp_stays_in_pinned_directory_after_path_swap(tmp_path):
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    directory = os.open(vault_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    pinned_path = tmp_path / "pinned-vault"
    vault_path.rename(pinned_path)
    vault_path.mkdir()
    try:
        fd, name = store.create_private_temp(directory, ".jotline-")
        with os.fdopen(fd, "w") as stream:
            stream.write("private")
        assert (pinned_path / name).read_text() == "private"
        assert not (vault_path / name).exists()
        os.unlink(name, dir_fd=directory)
    finally:
        os.close(directory)


def test_settings_save_repairs_invalid_utf8_regular_file(tmp_path):
    path = tmp_path / ".jotline-settings.json"
    path.write_bytes(b"\xff\xfe")
    settings, warning = Settings.load(path)
    assert warning
    settings.theme = "nord"
    settings.save(path)
    assert Settings.load(path) == (settings, "")


@pytest.mark.skipif(os.name == 'nt', reason='Windows has no directory fsync')
def test_directory_fsync_failure_does_not_create_false_conflict(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("first")
    vault.save(note)
    fsync = os.fsync

    def fail_directory(fd):
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode) and info.st_ino == tmp_path.stat().st_ino:
            raise OSError("directory fsync failed")
        fsync(fd)

    note.body = "second"
    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(OSError, match="directory fsync"):
        vault.save(note)
    assert vault.read(note.id).body == "second"
    monkeypatch.setattr(os, "fsync", fsync)
    vault.save(note)
    assert vault.read(note.id).body == "second"


def test_concurrent_daily_appends_preserve_every_capture(tmp_path):
    barrier = Barrier(8)

    def capture(index):
        barrier.wait()
        return Vault(tmp_path).append_daily(f"capture-{index}", "# {{date}}\n\n").id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(capture, range(8)))
    assert len(set(ids)) == 1
    note = Vault(tmp_path).daily()
    assert note.body.startswith(f"# {date.today().isoformat()}\n\n")
    for index in range(8):
        assert note.body.count(f"capture-{index}") == 1


@pytest.mark.parametrize("prefix", ["line with hard break  \n", "tail spaces  ", "tabs\t", "windows\r\n"])
def test_daily_append_preserves_existing_prefix_exactly(tmp_path, prefix):
    vault = Vault(tmp_path)
    note = vault.daily("")
    note.body = prefix
    vault.save(note)
    saved = vault.append_daily("capture", "")
    assert saved.body.startswith(prefix)
    assert saved.body.endswith("capture\n")


def test_late_external_new_note_collision_is_preserved(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = replace(vault.new("mine"), id="collision")

    def collide(*args, **kwargs):
        vault.file(note.id).write_text("external")
        return tmp_path / "unused.zip"

    monkeypatch.setattr(history, "backup", collide)
    with pytest.raises(ConflictError):
        vault.save(note)
    assert vault.file(note.id).read_text() == "external"
    assert any(vault.read_revision(note.id, item.id).body == "external" for item in vault.history(note.id))


def test_late_external_edit_is_not_overwritten(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("first")
    vault.save(note)
    note.body = "mine"

    def collide(*args, **kwargs):
        vault.file(note.id).write_text("external")
        return tmp_path / "unused.zip"

    monkeypatch.setattr(history, "backup", collide)
    with pytest.raises(ConflictError):
        vault.save(note)
    assert vault.file(note.id).read_text() == "external"


def test_stale_settings_merge_unrelated_fields_and_keep_unknown_keys(tmp_path):
    path = tmp_path / ".jotline-settings.json"
    path.write_text(json.dumps({"theme": "jotline", "sidebar_width": 32, "future": "keep"}))
    first, _ = Settings.load(path)
    second, _ = Settings.load(path)
    first.theme = "nord"
    first.save(path)
    second.sidebar_width = 40
    second.save(path)
    data = json.loads(path.read_text())
    assert data["theme"] == "nord"
    assert data["sidebar_width"] == 40
    assert data["future"] == "keep"


def test_stale_settings_from_missing_file_merge_unrelated_fields(tmp_path):
    path = tmp_path / ".jotline-settings.json"
    first, _ = Settings.load(path)
    second, _ = Settings.load(path)
    first.theme = "nord"
    first.save(path)
    second.sidebar_width = 40
    second.save(path)
    loaded, warning = Settings.load(path)
    assert not warning
    assert loaded.theme == "nord" and loaded.sidebar_width == 40


def test_settings_value_reversion_persists_for_mutation_and_replace(tmp_path):
    path = tmp_path / ".jotline-settings.json"
    Settings(theme="nord").save(path)
    loaded, _ = Settings.load(path)
    loaded.theme = "dracula"
    loaded.save(path)
    loaded.theme = "nord"
    loaded.save(path)
    assert Settings.load(path)[0].theme == "nord"

    changed = replace(loaded, theme="dracula")
    changed.save(path)
    reverted = replace(changed, theme="nord")
    reverted.save(path)
    assert Settings.load(path)[0].theme == "nord"


def test_explicit_save_repairs_oversized_regular_settings(tmp_path, monkeypatch):
    path = tmp_path / ".jotline-settings.json"
    path.write_text("x" * 32)
    monkeypatch.setattr(settings_module, "MAX_SETTINGS_BYTES", 8)
    loaded, warning = Settings.load(path)
    assert warning
    loaded.save(path)
    assert isinstance(json.loads(path.read_text()), dict)


def test_last_moment_external_write_is_preserved_in_history(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("first")
    vault.save(note)
    note.body = "mine"
    original_replace = store.replace_at

    def race(directory, source, target):
        if source == vault.file(note.id).name:
            vault.file(note.id).write_text("last moment external")
        return original_replace(directory, source, target)

    monkeypatch.setattr(store, "replace_at", race)
    vault.save(note)
    assert vault.read(note.id).body == "mine"
    bodies = [vault.read_revision(note.id, revision.id).body for revision in vault.history(note.id)]
    assert "last moment external" in bodies
    assert any("raced with save" in warning for warning in vault.warnings)


def test_failed_publish_and_restore_retains_displaced_original(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new('original')
    vault.save(note)
    note.body = 'replacement'

    monkeypatch.setattr(os, 'link',
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError('link failed')))
    with pytest.raises(OSError, match='link failed'):
        vault.save(note)

    displaced, = tmp_path.glob('.jotline-displaced-*')
    assert 'original' in displaced.read_text()
    assert any(displaced.name in warning for warning in vault.warnings)
