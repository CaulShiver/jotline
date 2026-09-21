from datetime import date, datetime
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
from textual.widgets import TextArea

from jotline import filesystem

from jotline.app import Jotline, Palette
from jotline.bench import CI_BUDGET_SECONDS, CI_NOTE_COUNT, measure_vault, populate_synthetic_vault, verdict
from jotline.cli_doctor import doctor_report
from jotline.history import BACKUP_LIMIT, DISPLACED_PREFIX, STALE_BACKUP_SECONDS
from jotline.recovery_ui import HealthScreen
from jotline.store import Vault


def run_cli(vault: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "jotline", "--vault", str(vault), *args],
        capture_output=True, check=False, timeout=30)


def test_recovery_copy_keeps_body_and_records_source(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("# Idea\n\nKeep this draft exactly.")
    vault.save(note)
    recovered = vault.recovery(note)
    stored = vault.read(recovered.id)
    assert stored.body == "# Idea\n\nKeep this draft exactly."
    assert stored.recovery_of == note.id
    assert stored.collection == "inbox"
    assert stored.id != note.id
    assert [copy.id for copy in vault.recoveries()] == [recovered.id]
    reloaded = Vault(tmp_path).read(recovered.id)
    assert reloaded.recovery_of == note.id


def test_recovery_of_a_recovery_copy_keeps_the_original_source(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("draft")
    vault.save(note)
    first = vault.recovery(note)
    second = vault.recovery(first)
    assert second.recovery_of == note.id


def test_doctor_and_cli_list_recovery_copies(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("keep me")
    vault.save(note)
    recovered = vault.recovery(note)
    listed = run_cli(tmp_path, "recoveries")
    assert listed.returncode == 0, listed.stderr.decode()
    assert recovered.id.encode() in listed.stdout
    assert note.id.encode() in listed.stdout
    payload = json.loads(run_cli(tmp_path, "recoveries", "--json").stdout)
    assert payload[0]["recovery_of"] == note.id
    report = doctor_report(vault, "")
    assert report["ancillary"]["recoveries"]["count"] == 1
    assert recovered.id in report["ancillary"]["recoveries"]["ids"]


def test_doctor_warns_about_displaced_conflict_files(tmp_path):
    vault = Vault(tmp_path)
    leftover = tmp_path / (DISPLACED_PREFIX + "abcd")
    leftover.write_text("original body")
    report = doctor_report(vault, "")
    assert report["ancillary"]["displaced"]["count"] == 1
    assert leftover.name in report["ancillary"]["displaced"]["files"]
    assert any("displaced" in item for item in report["warnings"])
    doctor = run_cli(tmp_path, "doctor")
    assert doctor.returncode == 1
    assert leftover.name.encode() in doctor.stderr


def test_doctor_warns_when_notes_exist_without_a_valid_backup(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new("needs a backup")
    vault.save(note)
    for path in (tmp_path / ".jotline-backups").glob("*.zip"):
        path.unlink()
    report = doctor_report(vault, "")
    assert any("no valid local ZIP" in item for item in report["warnings"])


def test_doctor_warns_when_the_newest_backup_is_stale(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("aging backup")
    vault.save(note)
    archive = next((tmp_path / ".jotline-backups").glob("*.zip"))
    stale = time.time() - STALE_BACKUP_SECONDS - 60
    os.utime(archive, (stale, stale))
    report = doctor_report(vault, "")
    assert any("newest valid archive is from" in item for item in report["warnings"])
    when = datetime.fromtimestamp(stale).date().isoformat()
    assert any(when in item for item in report["warnings"])


def test_backups_lists_and_fails_on_invalid_zips(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("backed up")
    vault.save(note)
    healthy = run_cli(tmp_path, "backups")
    assert healthy.returncode == 0, healthy.stderr.decode()
    assert b"ok\t" in healthy.stdout
    broken = tmp_path / ".jotline-backups" / "manual-20260912T000000000000-abcdef12.zip"
    broken.write_text("not a zip")
    listed = run_cli(tmp_path, "backups")
    assert listed.returncode == 1
    assert b"invalid\t" in listed.stdout
    payload = json.loads(run_cli(tmp_path, "backups", "--json").stdout)
    names = {item["name"] for item in payload}
    assert broken.name in names
    assert any(item["name"] == broken.name and item["valid"] is False for item in payload)


def test_empty_vault_doctor_does_not_demand_a_backup(tmp_path):
    healthy = run_cli(tmp_path, "doctor")
    assert healthy.returncode == 0, healthy.stderr.decode()
    assert b"Recovery copies: 0" in healthy.stdout
    assert b"Last valid backup: none" in healthy.stdout
    assert b"Warnings: 0" in healthy.stdout


def test_ci_synthetic_vault_stays_under_the_search_bar(tmp_path):
    vault = Vault(tmp_path)
    hub = populate_synthetic_vault(vault, CI_NOTE_COUNT, body_words=12)
    timings = measure_vault(vault, hub)
    assert timings[0].hits == CI_NOTE_COUNT
    assert timings[1].hits == len([n for n in vault.notes() if "unique-token-beta" in n.body])
    assert timings[2].hits >= CI_NOTE_COUNT // 3 - 1
    slowest = max(item.seconds for item in timings)
    assert slowest <= CI_BUDGET_SECONDS, (timings, verdict(CI_NOTE_COUNT, timings))
    assert "Do not add an index" in verdict(500, [
        type(timings[0])(item.label, 0.01, item.hits) for item in timings])
    assert "missed the 1.00s bar" in verdict(2000, [
        type(timings[0])(item.label, 1.5, item.hits) for item in timings])


async def test_health_and_recovery_copy_commands(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new("# Keep\n\nDraft text")
    vault.save(note)
    recovered = vault.recovery(note)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.command("doctor")
        await pilot.pause()
        assert isinstance(app.screen, HealthScreen)
        text = app.screen.query_one("#health-text", TextArea).text
        assert "Recovery copies: 1" in text
        assert "Last valid backup:" in text
        await pilot.press("escape")
        app.command("recoveries")
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        assert app.screen.heading == "Recovery copies"
        assert recovered.id in dict(app.screen.choices)
        await pilot.press("enter")
        await pilot.pause()
        assert app.current.id == recovered.id
        assert app.editor().text == "# Keep\n\nDraft text"


def test_a_crash_between_moving_the_note_aside_and_publishing_gets_the_note_back(tmp_path):
    # A save moves the note aside, then publishes the new text under its name.
    # Killed in between, the only copy of the note was left under a hidden name
    # that nothing lists, so the note was gone from the app with no warning.
    vault = Vault(tmp_path)
    note = vault.new("Important\n\nORIGINAL TEXT\n")
    vault.save(note)
    crash = """
import os, pathlib, signal, sys
from jotline.store import Vault
vault = Vault(pathlib.Path(sys.argv[1]))
note = vault.read(sys.argv[2])
import jotline.filesystem as filesystem
filesystem.fs.link = lambda *a, **k: os.kill(os.getpid(), signal.SIGKILL)
note.body = "NEW TEXT\\n"
vault.save(note)
"""
    killed = subprocess.run([sys.executable, "-c", crash, str(tmp_path), note.id],
                            capture_output=True)
    assert killed.returncode == -signal.SIGKILL
    assert not (tmp_path / f"{note.id}.md").exists()  # The save really was interrupted.

    reopened = Vault(tmp_path)
    assert [found.id for found in reopened.notes()] == [note.id]
    assert reopened.read(note.id).body == "Important\n\nORIGINAL TEXT\n"
    assert any("Recovered note" in warning for warning in reopened.warnings)


def test_a_save_survives_a_filesystem_with_neither_links_nor_exclusive_rename(tmp_path, monkeypatch):
    # Hard links are refused on FAT, SMB and shared folders; several of those
    # also reject renameat2's flags, which the restore path relied on. Both
    # refused, the note was deterministically lost on its first overwrite.
    vault = Vault(tmp_path)
    note = vault.new("Important\n\nORIGINAL TEXT\n")
    vault.save(note)

    def no_links(*args, **kwargs):
        raise OSError(errno.EPERM, "Operation not permitted")

    def no_flags(source, target, **kwargs):
        raise OSError(errno.EINVAL, "Invalid argument", str(target))

    monkeypatch.setattr(filesystem.fs, "link", no_links)
    monkeypatch.setattr(filesystem, "rename_noreplace", no_flags)
    edited = vault.read(note.id)
    edited.body = "NEW TEXT\n"
    with pytest.raises(OSError):
        vault.save(edited)

    monkeypatch.undo()
    reopened = Vault(tmp_path)
    assert [found.id for found in reopened.notes()] == [note.id]
    assert reopened.read(note.id).body == "Important\n\nORIGINAL TEXT\n"


def test_recovery_leaves_a_displaced_file_whose_note_is_still_there(tmp_path):
    # A save that finished can leave the displaced original behind as litter.
    # Putting that back would overwrite the note with its previous text.
    vault = Vault(tmp_path)
    note = vault.new("Current text\n")
    vault.save(note)
    litter = tmp_path / f"{DISPLACED_PREFIX}{note.id}.{'0' * 32}"
    litter.write_text("stale previous text")
    assert vault.recover_displaced() == []
    assert litter.exists()
    assert "Current text" in vault.read(note.id).body


def test_recovery_ignores_a_displaced_name_that_does_not_say_which_note_it_is(tmp_path):
    vault = Vault(tmp_path)
    leftover = tmp_path / (DISPLACED_PREFIX + "abcd")
    leftover.write_text("original body")
    assert vault.recover_displaced() == []
    assert leftover.exists()


def test_recovery_refuses_to_publish_a_symlink_as_a_note(tmp_path):
    vault = Vault(tmp_path)
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("not a note")
    (tmp_path / f"{DISPLACED_PREFIX}{'a' * 32}.{'0' * 32}").symlink_to(secret)
    assert vault.recover_displaced() == []
    assert not (tmp_path / f"{'a' * 32}.md").exists()


def test_quarantined_backups_are_bounded_and_reported(tmp_path):
    # An invalid daily archive is set aside as .invalid-*.zip so a fresh one can
    # be written. Nothing pruned those and nothing listed them, so a vault whose
    # daily archive kept failing validation grew a hidden pile of them.
    vault = Vault(tmp_path)
    folder = tmp_path / ".jotline-backups"
    folder.mkdir()
    note = vault.new("data")
    seen = []
    for round_ in range(BACKUP_LIMIT + 3):
        (folder / f"daily-{date.today().isoformat()}.zip").write_bytes(b"not a zip %d" % round_)
        note.body = f"data {round_}"
        vault.save(note)
        seen.extend(path.name for path in folder.glob(".invalid-*.zip") if path.name not in seen)
    kept = sorted(path.name for path in folder.glob(".invalid-*.zip"))
    assert len(seen) == BACKUP_LIMIT + 3
    assert kept == sorted(seen[-BACKUP_LIMIT:])
    report = doctor_report(vault, "")
    assert sorted(report["ancillary"]["backups"]["quarantined"]) == kept
    for name in kept:
        assert any(name in item and "failing validation" in item for item in report["warnings"])
    doctor = run_cli(tmp_path, "doctor")
    assert kept[0].encode() in doctor.stderr


def test_a_note_still_saves_when_its_history_cannot_be_written(tmp_path):
    # A file at .jotline-history made every save of every note fail. The daily
    # backup was already allowed to fail without holding the note hostage;
    # history was not, and what got lost was the text being saved.
    vault = Vault(tmp_path)
    (tmp_path / ".jotline-history").write_text("a sync tool put a file here")
    note = vault.new("Text that must not be lost\n")
    vault.save(note)
    assert vault.read(note.id).body == "Text that must not be lost\n"
    note.body = "Edited\n"
    vault.save(note)
    assert vault.read(note.id).body == "Edited\n"
    assert any("history is not being kept" in item for item in vault.warnings)
    # The condition outlasts a refresh, so the health report still says so.
    report = doctor_report(vault, "")
    assert any("history is not being kept" in item for item in report["warnings"])
    assert (tmp_path / ".jotline-history").read_text() == "a sync tool put a file here"
