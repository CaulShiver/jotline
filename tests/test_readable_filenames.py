"""Readable filenames: the ID stays the note, the slug is only where it sits."""
import json
import os
from datetime import date
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from jotline.filename_migration import migrate_filenames
from jotline.filenames import set_header_id
from jotline.history import DISPLACED_PREFIX
from jotline.links import resolve_link_targets
from jotline.settings import Settings
from jotline.store import ConflictError, Vault, wiki_link

pytest.importorskip("cryptography")


def run_cli(vault: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "jotline", "--vault", os.fsencode(vault), *args],
        capture_output=True, check=False, timeout=30)


def saved(vault: Vault, body: str, note_id: str | None = None):
    note = vault.new(body)
    if note_id is not None:
        note.id = note_id
    vault.save(note)
    return note


def names(vault: Vault) -> set[str]:
    return {path.name for path in vault.path.glob("*.md")}


def test_setting_off_keeps_the_id_as_the_filename(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    raw = (tmp_path / f"{note.id}.md").read_text()
    assert names(vault) == {f"{note.id}.md"}
    assert "\nid:" not in raw
    assert vault.file(note.id).name == f"{note.id}.md"


def test_setting_on_publishes_a_slug_and_keeps_the_id(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    note = saved(vault, "Buy milk")
    filename = f"buy-milk--{note.id[:6]}.md"
    assert names(vault) == {filename}
    raw = (tmp_path / filename).read_text()
    assert f'"id": "{note.id}"' in raw or json.loads(
        raw.split("id: ", 1)[1].split("\n", 1)[0]) == note.id
    assert vault.read(note.id).id == note.id
    assert vault.read(note.id).title == "Buy milk"
    assert wiki_link(note) == f"[[{note.id}|Buy milk]]"


def test_unchanged_save_does_not_rename_until_the_note_changes(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    vault.readable_filenames = True
    again = vault.read(note.id)
    vault.save(again)
    assert names(vault) == {f"{note.id}.md"}
    again.body += "\nWhole milk.\n"
    vault.save(again)
    assert names(vault) == {f"buy-milk--{note.id[:6]}.md"}
    assert vault.read(note.id).body.endswith("Whole milk.\n")


def test_retitle_renames_the_file_and_leaves_history_on_the_id(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    note = saved(vault, "Buy milk")
    note_id = note.id
    note.body = "Oat milk\n"
    vault.save(note)
    assert names(vault) == {f"oat-milk--{note_id[:6]}.md"}
    assert note.id == note_id
    assert (tmp_path / ".jotline-history" / note_id).is_dir()
    assert not (tmp_path / ".jotline-history").joinpath(f"oat-milk--{note_id[:6]}").exists()
    assert vault.read(note_id).title == "Oat milk"


def test_title_collision_lengthens_the_short_id(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    first_id = "a1b2c3" + "11" * 13
    second_id = "a1b2c3" + "22" * 13
    first = saved(vault, "Buy milk", first_id)
    second = saved(vault, "Buy milk", second_id)
    assert (tmp_path / f"buy-milk--{first.id[:6]}.md").is_file()
    assert (tmp_path / f"buy-milk--{second.id[:8]}.md").is_file()
    assert vault.read(first.id).id == first.id
    assert vault.read(second.id).id == second.id


def test_daily_hand_placed_and_non_latin_titles(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    daily = vault.daily("# {{date}}\n\n", when=date(2026, 10, 12))
    vault.save(daily)
    assert daily.id == "daily-2026-10-12"
    assert (tmp_path / "daily-2026-10-12.md").is_file()
    (tmp_path / "todo.md").write_text("# By hand\n")
    todo = next(note for note in vault.notes() if note.id == "todo")
    todo.body += "\n"
    vault.save(todo)
    assert (tmp_path / "todo.md").is_file()
    foreign = saved(vault, "牛奶")
    assert (tmp_path / f"note--{foreign.id[:6]}.md").is_file()


def test_links_and_cli_still_resolve_the_id(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    target = saved(vault, "Buy milk")
    source = saved(vault, f"See {wiki_link(target)}\n")
    matches = resolve_link_targets(vault.notes(), target.id)
    assert [note.id for note in matches] == [target.id]
    assert source.id != target.id
    filename = f"buy-milk--{target.id[:6]}"
    for reference in (target.id, target.id[:8], filename, "Buy milk"):
        result = run_cli(tmp_path, "export", reference)
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith(b"Buy milk")
    ambiguous = run_cli(tmp_path, "export", "a")
    assert ambiguous.returncode == 1


def test_short_prefix_is_refused_when_two_notes_share_it(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    saved(vault, "Buy milk", "a1b2c3" + "11" * 13)
    saved(vault, "Oat milk", "a1b2c3" + "22" * 13)
    ambiguous = run_cli(tmp_path, "export", "a1b2c3")
    assert ambiguous.returncode == 1
    assert b"matches" in ambiguous.stderr
    opened = run_cli(tmp_path, "export", "a1b2c322")
    assert opened.returncode == 0
    assert opened.stdout.startswith(b"Oat milk")


def test_migrate_dry_run_writes_nothing_and_a_real_run_is_reversible(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    before = (tmp_path / f"{note.id}.md").read_text()
    updated = note.updated
    (tmp_path / "todo.md").write_text("# By hand\n")
    settings = Settings()
    before_zips = {path.name for path in tmp_path.glob(".jotline-backups/*")}
    dry = migrate_filenames(vault, settings, dry_run=True)
    assert dry.ok and dry.backup is None and dry.readable_filenames is None
    assert (tmp_path / f"{note.id}.md").read_text() == before
    assert (tmp_path / "todo.md").is_file()
    assert settings.readable_filenames is False
    assert {path.name for path in tmp_path.glob(".jotline-backups/*")} == before_zips

    report = migrate_filenames(vault, settings)
    assert report.ok and report.backup and report.readable_filenames is True
    assert settings.readable_filenames is True
    slug = f"buy-milk--{note.id[:6]}.md"
    assert names(vault) == {slug, "todo.md"}
    assert vault.read(note.id).updated == updated
    with zipfile.ZipFile(report.backup) as archive:
        assert f"{note.id}.md" in archive.namelist()
        assert slug not in archive.namelist()
    later = vault.backup()
    with zipfile.ZipFile(later) as archive:
        assert slug in archive.namelist()
        assert f"{note.id}.md" not in archive.namelist()

    again = migrate_filenames(vault, settings)
    assert again.ok and names(vault) == {slug, "todo.md"}

    reverted = migrate_filenames(vault, settings, revert=True)
    assert reverted.ok and reverted.readable_filenames is False
    assert names(vault) == {f"{note.id}.md", "todo.md"}
    restored = (tmp_path / f"{note.id}.md").read_text()
    assert "\nid:" not in restored
    assert vault.read(note.id).title == "Buy milk"


def test_migrate_conflict_aborts_before_backup(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    raw = (tmp_path / f"{note.id}.md").read_text()
    other = tmp_path / f"buy-bread--{note.id[:6]}.md"
    other.write_text(set_header_id(raw, note.id).replace("Buy milk", "Buy bread"))
    settings = Settings()
    before_zips = {path.name for path in tmp_path.glob(".jotline-backups/*")}
    report = migrate_filenames(vault, settings)
    assert not report.ok and report.backup is None
    assert settings.readable_filenames is False
    assert (tmp_path / f"{note.id}.md").read_text() == raw
    assert other.is_file()
    assert {path.name for path in tmp_path.glob(".jotline-backups/*")} == before_zips
    listed = vault.notes()
    assert len([item for item in listed if item.id == note.id]) == 1
    assert any("more than one file" in warning for warning in vault.warnings)


def test_cli_migrate_and_a_foreign_workspace_name(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    dry = run_cli(tmp_path, "--workspace", "not-a-workspace", "filenames", "migrate", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert b"Dry run" in dry.stdout
    assert (tmp_path / f"{note.id}.md").is_file()
    migrated = run_cli(tmp_path, "filenames", "migrate", "--json")
    assert migrated.returncode == 0, migrated.stderr
    payload = json.loads(migrated.stdout)
    assert payload["ok"] is True and payload["readable_filenames"] is True
    assert (tmp_path / f"buy-milk--{note.id[:6]}.md").is_file()
    blocked = run_cli(tmp_path, "filenames", "migrate", "--dry-run", "--json")
    assert blocked.returncode == 0


def test_encrypted_notes_stay_opaque_and_round_trip(tmp_path):
    vault = Vault(tmp_path)
    vault.setup_encryption("correct horse", n=2**10)
    vault.readable_filenames = True
    note = saved(vault, "Client Sam\nsecret bench")
    slug = f"client-sam--{note.id[:6]}.md"
    assert (tmp_path / slug).is_file()
    vault.set_encrypted(note.id, "default", True)
    sealed = tmp_path / f"{note.id}.md"
    assert sealed.is_file()
    assert not (tmp_path / slug).exists()
    raw = sealed.read_text()
    assert "Client Sam" not in raw and "secret" not in raw
    archive = vault.backup()
    with zipfile.ZipFile(archive) as zipped:
        assert f"{note.id}.md" in zipped.namelist()
        assert all("client-sam" not in name for name in zipped.namelist())
        assert b"Client Sam" not in zipped.read(f"{note.id}.md")
    vault.cipher = None
    locked = vault.read(note.id)
    assert locked.locked and "Client" not in locked.title
    assert "secret" not in sealed.read_text()
    vault.unlock("correct horse")
    assert "secret bench" in vault.read(note.id).body
    vault.set_encrypted(note.id, "default", False)
    assert (tmp_path / slug).is_file()
    assert not sealed.exists()
    assert "secret bench" in (tmp_path / slug).read_text()


def test_duplicate_files_prefer_the_newer_slug_without_deleting(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    note = saved(vault, "Buy milk")
    slug = f"buy-milk--{note.id[:6]}.md"
    older = (tmp_path / f"{note.id}.md")
    older.write_text((tmp_path / slug).read_text().replace(
        note.updated, "2001-01-01T00:00:00+00:00"))
    vault.invalidate_cache()
    chosen = vault.read(note.id)
    assert chosen.filename == slug
    assert chosen.title == "Buy milk"
    listed = vault.notes()
    assert [item.filename for item in listed if item.id == note.id] == [slug]
    assert older.is_file() and (tmp_path / slug).is_file()
    assert any("more than one file" in warning for warning in vault.warnings)


def test_recovery_copy_gets_its_own_id(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    note = saved(vault, "Buy milk")
    copy = vault.recovery(note)
    assert copy.id != note.id
    assert copy.recovery_of == note.id
    assert copy.filename == f"buy-milk--{copy.id[:6]}.md"
    assert (tmp_path / copy.filename).is_file()
    assert (tmp_path / f"buy-milk--{note.id[:6]}.md").is_file()


def test_external_edit_is_still_a_conflict(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    note = saved(vault, "Buy milk")
    path = vault.file(note.id)
    path.write_text(path.read_text().replace("Buy milk", "Changed outside"))
    note.body += "\nlocal\n"
    with pytest.raises(ConflictError):
        vault.save(note)
    assert "Changed outside" in path.read_text()
    assert "\nlocal\n" not in path.read_text()


def test_a_short_id_that_is_not_a_prefix_still_opens_and_warns(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    raw = set_header_id((tmp_path / f"{note.id}.md").read_text(), note.id)
    (tmp_path / f"{note.id}.md").unlink()
    (tmp_path / "buy-milk--ffffff.md").write_text(raw)
    assert vault.notes()[0].id == note.id
    assert any("does not match" in warning for warning in vault.warnings)
    assert vault.read(note.id).title == "Buy milk"


def test_displaced_original_returns_as_the_id_file(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    note = saved(vault, "Buy milk")
    slug = vault.file(note.id)
    content = slug.read_text()
    displaced = tmp_path / f"{DISPLACED_PREFIX}{note.id}.abc123"
    displaced.write_text(content)
    assert vault.recover_displaced() == []
    assert slug.is_file()
    slug.unlink()
    vault._recovered_displaced = False
    assert vault.recover_displaced() == [note.id]
    assert (tmp_path / f"{note.id}.md").read_text() == content
    assert not slug.exists()
    assert not displaced.exists()
