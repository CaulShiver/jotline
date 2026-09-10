"""Regression cases from the storage review; all paths are temporary vaults."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
import os
import stat
from threading import Barrier
import time

import pytest

from jotline import store
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


def test_atomic_replace_failure_keeps_file_and_baseline(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("original")
    vault.save(note)
    original = note.original
    note.body = "replacement"

    def fail_replace(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        vault.save(note)
    assert vault.read(note.id).body == "original"
    assert note.original == original
    assert not list(tmp_path.glob(".jotline-*"))


def test_settings_save_repairs_invalid_utf8_regular_file(tmp_path):
    path = tmp_path / ".jotline-settings.json"
    path.write_bytes(b"\xff\xfe")
    settings, warning = Settings.load(path)
    assert warning
    settings.theme = "nord"
    settings.save(path)
    assert Settings.load(path) == (settings, "")


def test_directory_fsync_failure_does_not_create_false_conflict(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("first")
    vault.save(note)
    fsync = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
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
