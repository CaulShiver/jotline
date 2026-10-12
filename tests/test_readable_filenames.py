"""Readable filenames: the ID stays the note, the slug is only where it sits."""
import json
import os
from datetime import date
from pathlib import Path
import pty
import select
import subprocess
import sys
import time
import zipfile

import pytest
from textual.widgets import Select, Switch

from jotline.app import Jotline
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


def run_filenames_at_terminal(vault: Path, *args: str, answer: str = "") -> tuple[int, str]:
    """Run filenames with a real terminal. ``answer`` is typed when the prompt appears."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-m", "jotline", "--vault", str(vault), "filenames", *args],
        stdin=slave, stdout=slave, stderr=slave, close_fds=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"})
    os.close(slave)
    output = bytearray()
    sent = not answer
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                while select.select([master], [], [], 0)[0]:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break
                    output.extend(chunk)
                break
            ready, _, _ = select.select([master], [], [], 0.2)
            if not ready:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            output.extend(chunk)
            if not sent and b"Proceed?" in output:
                os.write(master, answer.encode())
                sent = True
        else:
            proc.kill()
            proc.wait(timeout=5)
            raise AssertionError(f"filenames command timed out: {output!r}")
    finally:
        if proc.poll() is None:
            proc.wait(timeout=5)
        os.close(master)
    return proc.returncode, output.decode(errors="replace")


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
    migrated = run_cli(tmp_path, "filenames", "migrate", "--json", "--yes")
    assert migrated.returncode == 0, migrated.stderr
    payload = json.loads(migrated.stdout)
    assert payload["ok"] is True and payload["readable_filenames"] is True
    assert (tmp_path / f"buy-milk--{note.id[:6]}.md").is_file()
    blocked = run_cli(tmp_path, "filenames", "migrate", "--dry-run", "--json")
    assert blocked.returncode == 0


def test_filenames_outside_a_terminal_refuse_unless_yes(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    opaque = tmp_path / f"{note.id}.md"
    slug = tmp_path / f"buy-milk--{note.id[:6]}.md"

    migrate = run_cli(tmp_path, "filenames", "migrate")
    assert migrate.returncode == 1
    assert b"Dry run" in migrate.stdout
    assert b"buy-milk" in migrate.stdout
    assert b"Refusing to rename note files without a terminal" in migrate.stderr
    assert b"--yes" in migrate.stderr
    assert opaque.is_file() and not slug.exists()
    assert Settings.load(tmp_path / ".jotline-settings.json")[0].readable_filenames is False

    forced = run_cli(tmp_path, "filenames", "migrate", "--yes")
    assert forced.returncode == 0, forced.stderr
    assert slug.is_file() and not opaque.exists()
    assert Settings.load(tmp_path / ".jotline-settings.json")[0].readable_filenames is True

    revert = run_cli(tmp_path, "filenames", "revert")
    assert revert.returncode == 1
    assert b"Dry run" in revert.stdout
    assert b"Refusing to rename note files without a terminal" in revert.stderr
    assert slug.is_file() and not opaque.exists()
    assert Settings.load(tmp_path / ".jotline-settings.json")[0].readable_filenames is True

    forced_back = run_cli(tmp_path, "filenames", "revert", "--yes")
    assert forced_back.returncode == 0, forced_back.stderr
    assert opaque.is_file() and not slug.exists()
    assert Settings.load(tmp_path / ".jotline-settings.json")[0].readable_filenames is False


def test_filenames_in_a_terminal_rename_only_after_yes(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    opaque = tmp_path / f"{note.id}.md"
    slug = tmp_path / f"buy-milk--{note.id[:6]}.md"

    declined, declined_output = run_filenames_at_terminal(tmp_path, "migrate", answer="n\n")
    assert declined == 0, declined_output
    assert "Proceed? A backup is written first. [y/N]" in declined_output
    assert "Nothing was changed." in declined_output
    assert opaque.is_file() and not slug.exists()

    accepted, accepted_output = run_filenames_at_terminal(tmp_path, "migrate", answer="y\n")
    assert accepted == 0, accepted_output
    assert "Readable filenames are on." in accepted_output
    assert slug.is_file() and not opaque.exists()

    declined_back, declined_back_output = run_filenames_at_terminal(tmp_path, "revert", answer="\n")
    assert declined_back == 0, declined_back_output
    assert "Nothing was changed." in declined_back_output
    assert slug.is_file() and not opaque.exists()

    accepted_back, accepted_back_output = run_filenames_at_terminal(tmp_path, "revert", answer="yes\n")
    assert accepted_back == 0, accepted_back_output
    assert "Readable filenames are off." in accepted_back_output
    assert opaque.is_file() and not slug.exists()

    again, again_output = run_filenames_at_terminal(tmp_path, "migrate", "--yes")
    assert again == 0, again_output
    assert "Proceed?" not in again_output
    assert slug.is_file() and not opaque.exists()


async def test_settings_switch_does_not_turn_on_readable_filenames(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    opaque = tmp_path / f"{note.id}.md"
    backups = {path.name for path in tmp_path.glob(".jotline-backups/*")}
    app = Jotline(vault)
    async with app.run_test(size=(110, 40)) as pilot:
        app.command("settings")
        await pilot.pause()
        app.screen.query_one("#pref-readable_filenames", Switch).value = True
        app.screen.query_one("#pref-theme", Select).value = "nord"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.settings.readable_filenames is False
        assert vault.readable_filenames is False
        assert app.settings.theme == "nord"
        messages = [item.message for item in app._notifications]
        assert any("Nothing was renamed." in message and "jotline filenames migrate" in message
                   for message in messages)
    assert opaque.is_file()
    assert not list(tmp_path.glob("buy-milk--*.md"))
    assert {path.name for path in tmp_path.glob(".jotline-backups/*")} == backups
    stored, _warning = Settings.load(tmp_path / ".jotline-settings.json")
    assert stored.readable_filenames is False
    assert stored.theme == "nord"


async def test_settings_keeps_readable_filenames_that_migration_already_turned_on(tmp_path):
    vault = Vault(tmp_path)
    vault.readable_filenames = True
    note = saved(vault, "Buy milk")
    Settings(readable_filenames=True).save(tmp_path / ".jotline-settings.json")
    slug = tmp_path / f"buy-milk--{note.id[:6]}.md"
    assert slug.is_file()
    app = Jotline(vault)
    async with app.run_test(size=(110, 40)) as pilot:
        assert app.settings.readable_filenames is True
        app.command("settings")
        await pilot.pause()
        assert app.screen.query_one("#pref-readable_filenames", Switch).value is True
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.settings.readable_filenames is True
        messages = [item.message for item in app._notifications]
        assert any(message == "Settings saved. Startup choices apply next launch." for message in messages)
        assert not any("jotline filenames migrate" in message for message in messages)
        app.command("settings")
        await pilot.pause()
        app.screen.query_one("#pref-readable_filenames", Switch).value = False
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.settings.readable_filenames is False
        assert vault.readable_filenames is False
    assert slug.is_file()
    stored, _warning = Settings.load(tmp_path / ".jotline-settings.json")
    assert stored.readable_filenames is False


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
