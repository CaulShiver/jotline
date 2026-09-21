from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from dataclasses import replace
import json
from jotline.filesystem import fs as os
import tracemalloc
import zipfile
from uuid import uuid4

import pytest
from jotline import history
from jotline.store import ConflictError, Vault


def test_revisions_preserve_latest_deleted_notes_and_workspace(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('# first\n\nCafé\r\n', workspace='work')
    vault.save(note)
    first = note.original
    note.body = '# second'
    note.starred = True
    vault.save(note)
    revisions = vault.history(note.id)
    assert len(revisions) == 2
    assert vault.read_revision(note.id, revisions[-1].id).original == first
    assert vault.read_revision(note.id, revisions[0].id).starred
    assert not vault.history_notes('default')
    vault.file(note.id).unlink()
    saved = vault.history_notes('work')[0]
    assert saved.body == '# second'
    recovered = vault.recovery(saved)
    assert recovered.id != note.id
    assert recovered.workspace == 'work'
    assert vault.read(recovered.id).body == '# second'


def test_unchanged_save_and_minute_retention(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new('first')
    count = 0
    def stamp():
        nonlocal count
        count += 1
        return f'20260910T1200{count:02}000000-12345678'
    monkeypatch.setattr(history, 'stamp', stamp)
    vault.save(note)
    original = note.original
    vault.save(note)
    assert note.original == original
    assert len(vault.history(note.id)) == 1
    for index in range(8):
        note.body = str(index)
        vault.save(note)
    entries = vault.history(note.id)
    assert len(entries) == 3
    assert vault.read_revision(note.id, entries[1].id).body == '6'
    assert vault.read_revision(note.id, entries[-1].id).body == 'first'
    assert vault.read_revision(note.id, entries[0].id).body == '7'
    monkeypatch.setattr(history, 'HISTORY_LIMIT', 2)
    for minute in range(1, 5):
        monkeypatch.setattr(history, 'stamp', lambda minute=minute: f'20260910T12{minute:02}00000000-12345678')
        note.body = f'minute {minute}'
        vault.save(note)
    assert len(vault.history(note.id)) == 2


def test_backup_contains_local_data_manifest_and_no_unsafe_files(tmp_path):
    vault = Vault(tmp_path / 'vault')
    (vault.path / 'plain.md').write_bytes(b'# Plain\r\n')
    (vault.path / '.jotline-settings.json').write_text('{"theme":"nord"}')
    templates = vault.path / '.jotline-templates'
    templates.mkdir()
    (templates / 'meeting.md').write_text('# {{date}}')
    outside = tmp_path / 'private'
    outside.write_text('private')
    (vault.path / 'unsafe.md').symlink_to(outside)
    if hasattr(os, 'mkfifo'):
        os.mkfifo(vault.path / 'pipe.md')
    else:
        (vault.path / 'pipe.md').mkdir()
    backup = vault.backup()
    with zipfile.ZipFile(backup) as archive:
        assert archive.read('plain.md') == b'# Plain\r\n'
        assert archive.read('.jotline-templates/meeting.md') == b'# {{date}}'
        assert json.loads(archive.read('.jotline-settings.json')) == {'theme': 'nord'}
        skipped = json.loads(archive.read('jotline-backup-manifest.json'))['skipped']
        assert {item['path'] for item in skipped} == {'unsafe.md', 'pipe.md'}
        assert all('.jotline-history' not in name and '.jotline-backups' not in name for name in archive.namelist())
    assert vault.warnings


def test_daily_backup_once_and_manual_retention(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    (tmp_path / 'legacy.md').write_text('before')
    note = vault.new('new')
    vault.save(note)
    archives = list((tmp_path / '.jotline-backups').glob('*.zip'))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        assert archive.read('legacy.md') == b'before'
    note.body = 'next'
    vault.save(note)
    assert list((tmp_path / '.jotline-backups').glob('*.zip')) == archives
    monkeypatch.setattr(history, 'BACKUP_LIMIT', 3)
    for _ in range(5):
        vault.backup()
    assert len(list((tmp_path / '.jotline-backups').glob('*.zip'))) == 3
    assert archives[0].exists()


def test_unsafe_history_directory_is_skipped_with_warning(tmp_path):
    # History behind a symlink is never followed. The note itself lives in the
    # vault root, so refusing the save protected nothing and lost the text.
    vault = Vault(tmp_path / 'vault')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (vault.path / '.jotline-history').symlink_to(outside, target_is_directory=True)
    note = vault.new('data')
    vault.save(note)
    assert vault.file(note.id).exists()
    assert not list(outside.iterdir())
    assert any('history is not being kept' in item for item in vault.warnings)


def test_unsafe_backup_directory_is_skipped_with_warning(tmp_path):
    # A backup that cannot be written safely must not hold the note hostage.
    vault = Vault(tmp_path / 'vault')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (vault.path / '.jotline-backups').symlink_to(outside, target_is_directory=True)
    note = vault.new('data')
    vault.save(note)
    assert vault.file(note.id).exists()
    assert not list(outside.iterdir())
    assert 'Daily backup failed' in vault.backup_warning


def test_failed_replace_or_history_durability_preserves_old_note(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new('first')
    vault.save(note)
    existing = vault.history(note.id)
    baseline = note.original
    note.body = 'second'
    original_link = os.link
    def fail_note(source, target, *args, **kwargs):
        if (str(source).startswith('.jotline-') and not str(source).startswith('.jotline-displaced-')
                and target == vault.file(note.id).name):
            raise OSError('note replacement failed')
        return original_link(source, target, *args, **kwargs)
    monkeypatch.setattr(os, 'link', fail_note)
    with pytest.raises(OSError, match='replacement'):
        vault.save(note)
    assert vault.read(note.id).body == 'first'
    assert note.original == baseline
    assert vault.history(note.id) == existing
    monkeypatch.setattr(os, 'link', original_link)
    monkeypatch.setattr(history, 'sync_directory', lambda path: (_ for _ in ()).throw(OSError('history durability failed')))
    # History that cannot be made durable no longer costs the save; the user is told instead.
    vault.save(note)
    assert vault.read(note.id).body == 'second'
    assert vault.history(note.id) == existing
    assert any('history is not being kept' in item for item in vault.warnings)


def test_conflicting_save_does_not_snapshot_uncommitted_body(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('first')
    vault.save(note)
    stale = replace(note, body='uncommitted')
    note.body = 'second'
    vault.save(note)
    existing = vault.history(note.id)
    with pytest.raises(ConflictError):
        vault.save(stale)
    assert vault.history(note.id) == existing


def test_concurrent_saves_keep_revisions_readable(tmp_path):
    def capture(index):
        return Vault(tmp_path).append_daily(str(index)).id
    with ThreadPoolExecutor(max_workers=5) as pool:
        ids = list(pool.map(capture, range(5)))
    vault = Vault(tmp_path)
    assert len(set(ids)) == 1
    entries = vault.history(ids[0])
    assert set(vault.read_revision(ids[0], entries[0].id).body.splitlines()) >= set(map(str, range(5)))
    assert len(list((tmp_path / '.jotline-backups').glob('*.zip'))) == 1


def test_revision_ids_and_symlink_files_are_rejected(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('first')
    vault.save(note)
    entry = vault.history(note.id)[0]
    with pytest.raises(ValueError):
        vault.read_revision(note.id, '../escape')
    path = tmp_path / '.jotline-history' / note.id / f'{entry.id}.md'
    path.unlink()
    path.symlink_to(vault.file(note.id))
    assert not vault.history(note.id)
    with pytest.raises(OSError):
        vault.read_revision(note.id, entry.id)


def test_malformed_history_timestamp_does_not_block_save(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('before')
    vault.save(note)
    (tmp_path / '.jotline-history' / note.id / '99999999T999999999999-aaaaaaaa.md').write_text('bad timestamp')
    note.body = 'after'
    vault.save(note)
    assert vault.read(note.id).body == 'after'
    assert len(vault.history(note.id)) == 2


def test_note_tempfile_failure_does_not_leave_phantom_revision(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new('before')
    vault.save(note)
    existing = vault.history(note.id)
    note.body = 'after'
    monkeypatch.setattr('jotline.store.create_private_temp',
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError, match='disk full'):
        vault.save(note)
    assert vault.history(note.id) == existing
    assert vault.read(note.id).body == 'before'


def test_backup_warning_survives_note_scan(tmp_path):
    vault = Vault(tmp_path)
    if hasattr(os, 'mkfifo'):
        os.mkfifo(tmp_path / 'pipe.md')
    else:
        (tmp_path / 'pipe.md').mkdir()
    vault.backup()
    vault.notes()
    assert 'skipped 1' in vault.backup_warning


def test_corrupt_newest_revision_does_not_block_save_or_older_recovery(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('first', workspace='work')
    vault.save(note)
    note.body = 'second'
    vault.save(note)
    newest = vault.history(note.id)[0]
    revision_path = tmp_path / '.jotline-history' / note.id / f'{newest.id}.md'
    revision_path.write_bytes(b'\xff')
    vault.file(note.id).unlink()
    recovered = vault.history_notes('work')
    assert recovered and recovered[0].body == 'first'
    assert any('skipped corrupt revision' in warning or newest.id in warning for warning in vault.warnings)


def test_corrupt_newest_revision_does_not_wedge_future_save(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('first')
    vault.save(note)
    folder = tmp_path / '.jotline-history' / note.id
    (folder / '20991231T235959999999-aaaaaaaa.md').write_bytes(b'\xff')
    note.body = 'second'
    vault.save(note)
    assert vault.read(note.id).body == 'second'
    assert any('skipped corrupt revision' in warning for warning in vault.warnings)


def test_invalid_daily_backup_is_retained_and_replaced(tmp_path):
    vault = Vault(tmp_path)
    folder = tmp_path / '.jotline-backups'
    folder.mkdir()
    daily = folder / 'daily-{}.zip'.format(history.date.today().isoformat())
    daily.write_bytes(b'not a zip')
    note = vault.new('data')
    vault.save(note)
    with zipfile.ZipFile(daily) as archive:
        assert 'jotline-backup-manifest.json' in archive.namelist()
    quarantined = list(folder.glob('.invalid-*.zip'))
    assert len(quarantined) == 1 and quarantined[0].read_bytes() == b'not a zip'
    assert 'Invalid daily backup retained' in vault.backup_warning


@pytest.mark.parametrize('manifest_only,manifest', [
    (True, {"created": "now", "skipped": [], "scope": "notes"}),
    (False, None),
    (False, {"created": "now"}),
])
def test_structurally_incomplete_daily_backup_is_replaced(tmp_path, manifest_only, manifest):
    vault = Vault(tmp_path)
    (tmp_path / 'plain.md').write_text('data')
    folder = tmp_path / '.jotline-backups'
    folder.mkdir()
    daily = folder / f'daily-{history.date.today().isoformat()}.zip'
    with zipfile.ZipFile(daily, 'w') as archive:
        if not manifest_only:
            archive.writestr('plain.md', b'data')
        archive.writestr('jotline-backup-manifest.json', json.dumps(manifest))
    vault.backup_warning = ''
    history.backup(vault, automatic=True)
    valid, reason = history.validate_backup(daily)
    assert valid, reason
    assert list(folder.glob('.invalid-*.zip'))


def test_backup_template_bytes_count_toward_aggregate_budget(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    (tmp_path / 'plain.md').write_text('123456')
    templates = tmp_path / '.jotline-templates'
    templates.mkdir()
    (templates / 'large.md').write_text('abcdefghij')
    monkeypatch.setattr(history, 'MAX_BACKUP_BYTES', 12)
    archive_path = vault.backup()
    with zipfile.ZipFile(archive_path) as archive:
        assert 'plain.md' in archive.namelist()
        assert '.jotline-templates/large.md' not in archive.namelist()
        skipped = json.loads(archive.read('jotline-backup-manifest.json'))['skipped']
    assert any(item['path'] == '.jotline-templates/large.md' for item in skipped)


@pytest.mark.skipif(os.name == 'nt', reason='Windows pins directories against rename; covered by native tests')
def test_history_stays_on_pinned_vault_during_root_swap(tmp_path, monkeypatch):
    original = tmp_path / 'vault'
    vault = Vault(original)
    note = vault.new('first')
    vault.save(note)
    note.body = 'second'
    moved = tmp_path / 'moved-vault'
    original_temp = history.create_private_temp
    swapped = False

    def swap(directory, prefix):
        nonlocal swapped
        if prefix == '.revision-' and not swapped:
            swapped = True
            original.rename(moved)
            original.mkdir()
        return original_temp(directory, prefix)

    monkeypatch.setattr(history, 'create_private_temp', swap)
    vault.save(note)
    assert Vault(moved).read(note.id).body == 'second'
    assert not (original / f'{note.id}.md').exists()


@pytest.mark.skipif(os.name == 'nt', reason='Windows pins directories against rename; covered by native tests')
def test_backup_stays_on_pinned_folder_during_folder_swap(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    (tmp_path / 'plain.md').write_text('data')
    backups = tmp_path / '.jotline-backups'
    retained = tmp_path / 'retained-backups'
    original_temp = history.create_private_temp

    def swap(directory, prefix):
        if prefix == '.backup-' and backups.exists() and not retained.exists():
            backups.rename(retained)
            backups.mkdir()
        return original_temp(directory, prefix)

    monkeypatch.setattr(history, 'create_private_temp', swap)
    vault.backup()
    assert not list(backups.iterdir())
    archive, = retained.glob('manual-*.zip')
    with zipfile.ZipFile(archive) as opened:
        assert opened.read('plain.md') == b'data'


@pytest.mark.skipif(os.name == 'nt', reason='Windows pins directories against rename; covered by native tests')
def test_history_browsing_stays_on_pinned_vault_during_root_swap(tmp_path, monkeypatch):
    original = tmp_path / 'vault'
    vault = Vault(original)
    trusted = vault.new('trusted history', workspace='work')
    vault.save(trusted)
    trusted.body = 'trusted latest'
    vault.save(trusted)

    replacement = tmp_path / 'replacement'
    attacker_vault = Vault(replacement)
    attacker = attacker_vault.new('attacker history', workspace='work')
    attacker.id = trusted.id
    attacker_vault.save(attacker)
    attacker.body = 'attacker latest'
    attacker_vault.save(attacker)

    retained = tmp_path / 'retained'
    original_ids = history.history_note_ids

    def swap_after_enumeration(selected, *, vault_directory=None):
        result = original_ids(selected, vault_directory=vault_directory)
        if original.exists():
            original.rename(retained)
            replacement.rename(original)
        return result

    monkeypatch.setattr(history, 'history_note_ids', swap_after_enumeration)
    recovered = vault.history_notes('work')
    assert recovered
    assert all('attacker' not in note.body for note in recovered)
    assert any('trusted' in note.body for note in recovered)


def test_backup_temp_failure_closes_template_descriptor(tmp_path, monkeypatch, resource_count):
    vault = Vault(tmp_path)
    templates = tmp_path / '.jotline-templates'
    templates.mkdir()
    (templates / 'custom.md').write_text('template')
    before = resource_count()
    monkeypatch.setattr(history, 'create_private_temp',
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError('disk full')))
    for _ in range(16):
        with pytest.raises(OSError, match='disk full'):
            vault.backup()
    assert resource_count() == before


@pytest.mark.parametrize('error_type', [FileNotFoundError, PermissionError, OSError])
def test_history_stat_only_ignores_disappeared_revisions(tmp_path, fault_entry_stat, error_type):
    vault = Vault(tmp_path)
    note = vault.new('first')
    vault.save(note)
    note.body = 'second'
    vault.save(note)
    revisions = vault.history(note.id)
    assert len(revisions) == 2

    def fail():
        raise error_type('injected stat failure')

    fault_entry_stat(history.os, revisions[0].id + '.md', fail)
    if error_type is FileNotFoundError:
        assert vault.history(note.id) == revisions[1:]
    else:
        with pytest.raises(error_type, match='injected stat failure'):
            vault.history(note.id)


@pytest.mark.skipif(os.name == 'nt' or getattr(os, 'geteuid', lambda: 0)() == 0,
                    reason='Requires POSIX permissions and an unprivileged user')
def test_history_permission_error_propagates(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('saved')
    vault.save(note)
    folder = tmp_path / '.jotline-history' / note.id
    folder.chmod(0o400)
    try:
        with pytest.raises(PermissionError):
            vault.history(note.id)
    finally:
        folder.chmod(0o700)


def test_daily_backup_survives_concurrent_prune(tmp_path, monkeypatch, fault_entry_stat):
    vault = Vault(tmp_path)
    prune = history._prune_backups
    raced = []

    def prune_with_race(vault, folder, keep_name):
        stale = tmp_path / '.jotline-backups' / 'daily-2020-01-01.zip'
        stale.write_bytes(b'stale archive')

        def disappear():
            stale.unlink()
            raced.append(True)

        fault_entry_stat(history.os, stale.name, disappear)
        prune(vault, folder, keep_name)

    monkeypatch.setattr(history, '_prune_backups', prune_with_race)
    note = vault.new('saved despite concurrent pruning')
    vault.save(note)
    assert raced == [True]
    assert vault.backup_warning == ''
    assert vault.read(note.id).body == note.body
    archives = list((tmp_path / '.jotline-backups').glob('daily-*.zip'))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        assert archive.testzip() is None
        assert note.id + '.md' in archive.namelist()


def test_a_clock_that_steps_backwards_does_not_delete_the_newest_revisions(tmp_path, monkeypatch):
    # Survivors were ranked by the wall-clock stamp inside the revision ID, so
    # after DST ends or an NTP correction the revisions just written sorted
    # below the old ones and were pruned away while stale ones were retained.
    vault = Vault(tmp_path)
    note = vault.new("Draft 0\n")
    vault.save(note)
    base = datetime(2026, 11, 1, 1, 26, 0)
    clock = {"now": base}

    def stepping_clock():
        moment = clock["now"]
        clock["now"] = moment + timedelta(seconds=61)
        return moment.strftime("%Y%m%dT%H%M%S%f") + "-" + uuid4().hex[:8]

    monkeypatch.setattr(history, "stamp", stepping_clock)
    for draft in range(1, 35):
        note.body = f"Draft {draft}\n"
        vault.save(note)

    clock["now"] = base - timedelta(hours=1)  # Local time repeats the hour.
    for draft in range(35, 45):
        note.body = f"Draft {draft}\n"
        vault.save(note)

    # A snapshot records the text a save is about to overwrite, so the last
    # draft written is the live note rather than a revision.
    folder = tmp_path / ".jotline-history" / note.id
    kept = [path.read_text() for path in folder.glob("*.md")]
    for draft in range(35, 44):
        assert any(f"Draft {draft}\n" in text for text in kept), draft


def test_a_revision_left_half_written_by_a_crash_is_not_a_plaintext_leak(tmp_path):
    # A crash during a revision write leaves a .revision-* temp holding the
    # whole note. It carries no revision ID, so the purge that runs when a note
    # is encrypted never saw it, and no pruning pass covered this folder.
    pytest.importorskip("cryptography")
    secret = "ZQPLATNTXT dosage 200mg"
    vault = Vault(tmp_path)
    vault.setup_encryption("correct horse battery", n=2 ** 10)
    vault.unlock("correct horse battery")
    note = vault.new(f"{secret} therapy\n")
    vault.save(note)
    note.body += "more\n"
    vault.save(note)

    orphan = tmp_path / ".jotline-history" / note.id / (".revision-" + "a" * 32)
    orphan.write_text(f"{secret} therapy\nmore\n")

    note.encrypted = True
    vault.save(note)
    remaining = [path for path in tmp_path.rglob("*")
                 if path.is_file() and secret.encode() in path.read_bytes()]
    assert remaining == []


def test_encrypting_a_note_as_the_first_write_of_the_day_keeps_its_text_out_of_the_backup(tmp_path):
    # The daily backup ran before the sealed file was published, so the day's
    # first save archived the note in the clear at the moment the user asked
    # for it to be sealed.
    pytest.importorskip("cryptography")
    secret = "ZQPLATNTXT dosage 200mg"
    vault = Vault(tmp_path)
    vault.setup_encryption("correct horse battery", n=2 ** 10)
    vault.unlock("correct horse battery")
    note = vault.new(f"{secret} therapy\n")
    vault.save(note)
    for archive in (tmp_path / ".jotline-backups").glob("daily-*.zip"):
        archive.unlink()  # That save was yesterday's; today's first write is the encrypt.

    note.encrypted = True
    vault.save(note)
    daily = next((tmp_path / ".jotline-backups").glob("daily-*.zip"))
    with zipfile.ZipFile(daily) as archive:
        assert archive.testzip() is None
        archived = archive.read(f"{note.id}.md").decode()
    assert secret not in archived
    assert vault.parse_note(note.id, archived, vault.cipher).body == f"{secret} therapy\n"
    assert vault.read(note.id).body == f"{secret} therapy\n"


def test_backup_validation_does_not_inflate_a_declared_manifest_into_memory(tmp_path):
    # The manifest was captured whole, bounded only by MAX_BACKUP_BYTES, so a
    # few hundred kilobytes of deflate on disk cost hundreds of megabytes of
    # memory before the archive was rejected.
    bomb = tmp_path / "daily-2026-09-21.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("note.md", b"data")
        archive.writestr("jotline-backup-manifest.json", b" " * (128 * 1024 * 1024))
    assert bomb.stat().st_size < 256 * 1024
    tracemalloc.start()
    try:
        valid, reason = history.validate_backup(bomb)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert (valid, reason) == (False, "manifest exceeds validation limit")
    assert peak < 4 * history.MAX_MANIFEST_BYTES
