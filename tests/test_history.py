from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import zipfile

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
    os.mkfifo(vault.path / 'pipe.md')
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


@pytest.mark.parametrize('folder', ['.jotline-history', '.jotline-backups'])
def test_reject_unsafe_storage_directory(tmp_path, folder):
    vault = Vault(tmp_path / 'vault')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (vault.path / folder).symlink_to(outside, target_is_directory=True)
    note = vault.new('data')
    with pytest.raises(OSError):
        vault.save(note)
    assert not vault.file(note.id).exists()
    assert not list(outside.iterdir())


def test_failed_replace_or_history_durability_preserves_old_note(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = vault.new('first')
    vault.save(note)
    existing = vault.history(note.id)
    baseline = note.original
    note.body = 'second'
    original_replace = os.replace
    def fail_note(source, target):
        if target == vault.file(note.id):
            raise OSError('note replacement failed')
        return original_replace(source, target)
    monkeypatch.setattr(os, 'replace', fail_note)
    with pytest.raises(OSError, match='replacement'):
        vault.save(note)
    assert vault.read(note.id).body == 'first'
    assert note.original == baseline
    assert vault.history(note.id) == existing
    monkeypatch.setattr(os, 'replace', original_replace)
    monkeypatch.setattr(history, 'sync_directory', lambda path: (_ for _ in ()).throw(OSError('history durability failed')))
    with pytest.raises(OSError, match='durability'):
        vault.save(note)
    assert vault.read(note.id).body == 'first'
    assert vault.history(note.id) == existing


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
    monkeypatch.setattr('tempfile.mkstemp', lambda **kwargs: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError, match='disk full'):
        vault.save(note)
    assert vault.history(note.id) == existing
    assert vault.read(note.id).body == 'before'


def test_backup_warning_survives_note_scan(tmp_path):
    vault = Vault(tmp_path)
    os.mkfifo(tmp_path / 'pipe.md')
    vault.backup()
    vault.notes()
    assert 'skipped 1' in vault.backup_warning
