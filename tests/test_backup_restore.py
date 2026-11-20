import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

import pytest
from textual.widgets import Input

from jotline import backup_restore
from jotline.app import Jotline
from jotline.backup_restore import check_destination, preview_backup, restore_backup
from jotline.modal import Palette, TextPrompt
from jotline.recovery_ui import BackupRestorePreview
from jotline.settings import Settings
from jotline.store import Vault


def write_zip(target: Path, *entries: tuple[str | zipfile.ZipInfo, str]) -> None:
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(backup_restore.MANIFEST, json.dumps({
            "created": "2026-09-12T12:00:00+00:00", "scope": "vault", "skipped": [],
        }))
        for name, content in entries:
            archive.writestr(name, content)


def test_preview_and_restore_preserve_vault_files_without_touching_current_notes(tmp_path):
    vault = Vault(tmp_path / "current")
    prior = vault.new("# Prior\r\n\r\nCafé", workspace="work")
    vault.save(prior)
    Settings(theme="nord").save(vault.path / ".jotline-settings.json")
    templates = vault.path / ".jotline-templates"
    templates.mkdir()
    (templates / "meeting.md").write_bytes(b"Meeting\r\n")
    (vault.path / "unsafe.md").symlink_to(vault.file(prior.id))
    original = vault.file(prior.id).read_bytes()
    backup = vault.backup()
    prior.body = "# Current version"
    vault.save(prior)
    current = vault.file(prior.id).read_bytes()

    target = tmp_path / "Recovered notes"
    preview = preview_backup(backup)
    assert preview.notes == preview.templates == preview.skipped == 1
    assert preview.settings and not preview.key
    assert "unsafe.md" in preview.describe()
    assert "Café" not in preview.describe()
    assert check_destination(target, vault.path) == target
    assert not target.exists()

    assert restore_backup(preview, target, vault.path) == target
    assert (target / vault.file(prior.id).name).read_bytes() == original
    assert (target / ".jotline-settings.json").read_bytes() == (vault.path / ".jotline-settings.json").read_bytes()
    assert (target / ".jotline-templates" / "meeting.md").read_bytes() == b"Meeting\r\n"
    assert not (target / ".jotline-history").exists()
    assert not (target / ".jotline-backups").exists()
    assert not (target / "unsafe.md").exists()
    assert stat.S_IMODE(target.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE((target / vault.file(prior.id).name).stat().st_mode) & 0o077 == 0
    assert vault.file(prior.id).read_bytes() == current


def test_restore_carries_wrapped_key_and_preserves_encrypted_note(tmp_path):
    pytest.importorskip("cryptography")
    vault = Vault(tmp_path / "current")
    vault.setup_encryption("test passphrase", n=2**10)
    note = vault.new("Private content")
    note.encrypted = True
    vault.save(note)
    preview = preview_backup(vault.backup())
    assert preview.key
    recovered = Vault(restore_backup(preview, tmp_path / "recovered", vault.path), create=False)
    assert recovered.read(note.id).locked
    assert recovered.file(note.id).read_bytes() == vault.file(note.id).read_bytes()
    recovered.unlock("test passphrase")
    assert recovered.read(note.id).body == "Private content"


@pytest.mark.parametrize("member", ("../escape.md", "/absolute.md", ".jotline-templates/../escape.md",
                                    ".jotline-history/old.md", ".jotline-templates//note.md"))
def test_preview_refuses_entries_outside_backup_layout(tmp_path, member):
    source = tmp_path / "unsafe.zip"
    write_zip(source, (member, "Other file"))
    with pytest.raises(ValueError, match="backup entry"):
        preview_backup(source)


def test_preview_refuses_link_duplicate_corrupt_and_oversize_members(tmp_path, monkeypatch):
    source = tmp_path / "input.zip"
    link = zipfile.ZipInfo("link.md")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    write_zip(source, (link, "note.md"))
    with pytest.raises(ValueError, match="Unsafe backup entry"):
        preview_backup(source)

    with pytest.warns(UserWarning, match="Duplicate"):
        write_zip(source, ("note.md", "First"), ("note.md", "Second"))
    with pytest.raises(ValueError, match="Duplicate backup entry"):
        preview_backup(source)

    write_zip(source, ("note.md", "Unlike any other ZIP text"))
    source.write_bytes(source.read_bytes().replace(b"Unlike any other ZIP text", b"Xnlike any other ZIP text"))
    with pytest.raises(ValueError, match="Invalid backup ZIP"):
        preview_backup(source)

    monkeypatch.setattr(backup_restore, "MAX_NOTE_BYTES", 4)
    write_zip(source, ("note.md", "First"))
    with pytest.raises(ValueError, match="entry exceeds"):
        preview_backup(source)


def test_restore_refuses_existing_nested_or_aliased_targets(tmp_path):
    active = tmp_path / "active"
    active.mkdir()
    existing = tmp_path / "empty"
    existing.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(active, target_is_directory=True)
    broken_alias = tmp_path / "missing-alias"
    broken_alias.symlink_to(tmp_path / "missing-path")
    for destination in (active, active / "nested", existing, alias / "nested", broken_alias):
        with pytest.raises((OSError, ValueError)):
            check_destination(destination, active)
    assert not list(active.iterdir())
    assert not list(existing.iterdir())
    assert broken_alias.is_symlink()


def test_restore_does_not_publish_when_archive_or_destination_changes(tmp_path, monkeypatch):
    source = tmp_path / "backup.zip"
    active = tmp_path / "active"
    destination = tmp_path / "copy"
    write_zip(source, ("note.md", "First"))
    preview = preview_backup(source)
    replacement = tmp_path / "replacement.zip"
    write_zip(replacement, ("note.md", "Other"))
    replacement.replace(source)
    with pytest.raises(ValueError, match="changed since"):
        restore_backup(preview, destination, active)
    assert not destination.exists()

    publish = backup_restore.rename_noreplace

    def other_process_creates_target(*args, **kwargs):
        destination.mkdir()
        (destination / "keep.md").write_text("Leave me alone", encoding="utf-8")
        publish(*args, **kwargs)

    monkeypatch.setattr(backup_restore, "rename_noreplace", other_process_creates_target)
    with pytest.raises(ValueError, match="already exists"):
        restore_backup(preview_backup(source), destination, active)
    assert not active.exists()
    assert list(destination.iterdir()) == [destination / "keep.md"]
    assert not list(tmp_path.glob(".jotline-restore-*"))


def test_restore_syncs_parent_after_publishing(tmp_path, monkeypatch):
    source = tmp_path / "backup.zip"
    target = tmp_path / "restored"
    write_zip(source, ("note.md", "Recovered"))
    fsync = os.fsync
    synced = []

    def check_sync(fd):
        if os.path.samestat(os.fstat(fd), tmp_path.stat()):
            synced.append((target / "note.md").is_file())
        fsync(fd)

    monkeypatch.setattr(backup_restore.os, "fsync", check_sync)
    restore_backup(preview_backup(source), target, tmp_path / "current")
    assert synced == [True]


def test_cli_can_preview_and_restore_copied_zip_without_an_active_vault(tmp_path):
    active = tmp_path / "missing current vault"
    archive = tmp_path / "copied.zip"
    destination = tmp_path / "Recovered notes"
    write_zip(archive, ("note.md", "# Recovered"))

    def run(*args):
        return subprocess.run([sys.executable, "-m", "jotline", "restore-backup", str(archive),
                               "--vault", str(active), *args], capture_output=True, text=True, check=False)

    preview = run("--to", str(destination))
    assert preview.returncode == 0, preview.stderr
    assert "Markdown notes: 1" in preview.stdout
    assert "No files written" in preview.stdout
    assert not destination.exists()
    assert run("--apply").returncode == 2
    result = run("--to", str(destination), "--apply")
    assert result.returncode == 0, result.stderr
    assert f"jotline --vault '{destination}'" in result.stdout
    assert (destination / "note.md").read_text(encoding="utf-8") == "# Recovered"
    assert run("--to", str(destination), "--apply").returncode == 1
    assert not active.exists()


async def test_app_can_preview_cancel_and_restore_into_a_separate_vault(tmp_path):
    vault = Vault(tmp_path / "current")
    Settings(walkthrough_shown=True).save(vault.path / ".jotline-settings.json")
    note = vault.new("# Backup version")
    vault.save(note)
    old = vault.file(note.id).read_bytes()
    backup = vault.backup()
    note.body = "# Current version"
    vault.save(note)
    current = vault.file(note.id).read_bytes()
    destination = tmp_path / "current-restored"
    app = Jotline(vault)

    async with app.run_test() as pilot:
        async def open_preview():
            await pilot.press("ctrl+p")
            assert isinstance(app.screen, Palette)
            app.screen.query_one(Input).value = "Restore backup to a new vault"
            await pilot.pause()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen.heading == "Choose a backup to restore"
            app.screen.query_one(Input).value = backup.name
            await pilot.pause()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, TextPrompt)
            assert app.screen.query_one(Input).value == str(destination)
            await pilot.press("enter")
            assert isinstance(app.screen, BackupRestorePreview)
            assert app.screen.preview.notes == 1
            assert app.screen.focused.id == "restore-cancel"
            assert not destination.exists()

        await open_preview()
        await pilot.press("escape")
        assert not destination.exists()
        await open_preview()
        await pilot.press("tab", "enter")
        await app.workers.wait_for_complete()
        assert (destination / vault.file(note.id).name).read_bytes() == old
        assert app.vault is vault
        assert vault.file(note.id).read_bytes() == current
