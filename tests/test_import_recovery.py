import json
import subprocess
import sys

import pytest
from textual.app import App
from jotline.importing import preview_import, apply_import
from jotline.import_ui import ImportPreviewScreen
from jotline.recovery_ui import RecoveryScreen
from jotline.store import Vault


def test_drafts_metadata_dates_duplicates_and_originals(tmp_path):
    vault = Vault(tmp_path / 'vault')
    source = tmp_path / 'notes.draftsExport'
    entries = [{'content': 'Meeting', 'uuid': '39EA5821-A1A5-4DE6-AD06-F17381A24D85',
                'folder': 1, 'flagged': True, 'tags': ['work', 'two words'],
                'created_at': '2020-02-24T13:45:57Z', 'modified_at': '2020-02-24T13:46:04Z'}]
    source.write_text(json.dumps(entries))
    plan = preview_import(vault, source, workspace='work')
    assert plan.ready == 1 and not vault.notes()
    result = apply_import(vault, plan)
    assert not result.errors
    note = vault.read(result.imported[0])
    assert note.collection == 'archive' and note.starred and note.workspace == 'work'
    assert note.created == entries[0]['created_at'] and note.updated == entries[0]['modified_at']
    assert '#work' in note.body and 'two words' in note.body
    assert source.read_text() == json.dumps(entries)
    assert preview_import(vault, source, workspace='work').ready == 0
    copy = apply_import(vault, preview_import(vault, source, workspace='work', duplicates='copy'))
    assert len(copy.imported) == 1 and copy.imported[0] != note.id


def test_folder_preview_symlinks_duplicates_and_partial_failure(tmp_path, monkeypatch):
    vault = Vault(tmp_path / 'vault')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a.md').write_text('one')
    (source / 'b.txt').write_text('one')
    (source / 'c.md').write_text('three')
    (source / 'sub').mkdir()
    (source / 'sub' / 'd.md').write_text('four')
    plan = preview_import(vault, source, recursive=True)
    assert plan.ready == 3 and len(plan.items) == 4
    save = vault.save
    def fail_one(note, **kwargs):
        if note.body == 'three':
            raise OSError('Disk full')
        save(note, **kwargs)
    monkeypatch.setattr(vault, 'save', fail_one)
    result = apply_import(vault, plan)
    assert len(result.imported) == 2 and result.skipped == 1 and len(result.errors) == 1
    assert len(list(source.glob('*.md'))) == 2


def test_outside_files_keep_a_jotline_header_in_their_body(tmp_path):
    vault = Vault(tmp_path / 'vault')
    source = tmp_path / 'handed-over'
    source.mkdir()
    header = ('---\njotline: 1\ncollection: "archive"\nstarred: true\n'
              'created: "2001-01-01T00:00:00+00:00"\nupdated: "2001-01-02T00:00:00+00:00"\n---\n')
    (source / 'Meeting notes.md').write_text(header + '# Spaced name\n', encoding='utf-8')
    (source / 'notes.txt').write_text('﻿' + header + '# Text file\n', encoding='utf-8')
    plan = preview_import(vault, source)
    assert [item.source for item in plan.items] == ['Meeting notes.md', 'notes.txt']
    apply_import(vault, plan)
    notes = vault.notes()
    assert len(notes) == 2
    for note in notes:
        assert note.body.startswith(header)
        assert note.collection == 'inbox' and not note.starred
        assert not note.created.startswith('2001') and not note.updated.startswith('2001')


def test_folder_import_carries_metadata_from_note_files_only(tmp_path):
    old = Vault(tmp_path / 'old')
    saved = old.new('# Saved by Jotline\n')
    saved.collection, saved.starred = 'projects', True
    old.save(saved)
    # A hand-edited vault can hold a note file written by hand under a name of the user's choosing.
    (old.path / 'todo.md').write_text('---\njotline: 1\ncollection: "areas"\n---\n# Hand written\n', encoding='utf-8')
    new = Vault(tmp_path / 'new')
    plan = preview_import(new, old.path)
    assert sorted(item.source for item in plan.items) == sorted([f'{saved.id}.md (Jotline note)',
                                                                 'todo.md (Jotline note)'])
    apply_import(new, plan)
    got = {note.title: note for note in new.notes()}
    assert (got['Saved by Jotline'].collection, got['Saved by Jotline'].starred) == ('projects', True)
    assert got['Hand written'].collection == 'areas' and got['Hand written'].body == '# Hand written\n'


def test_import_rejects_links(tmp_path):
    vault = Vault(tmp_path / 'vault')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'real.md').write_text('text')
    try:
        (source / 'link.md').symlink_to(source / 'real.md')
        (tmp_path / 'linked-folder').symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip('Symlinks unavailable')
    plan = preview_import(vault, source, recursive=True)
    assert plan.ready == 1 and plan.warnings
    assert preview_import(vault, tmp_path / 'linked-folder').ready == 0
    assert preview_import(vault, tmp_path / 'linked-folder' / 'real.md').ready == 0


def test_invalid_records_reported_without_losing_valid(tmp_path):
    vault = Vault(tmp_path / 'vault')
    source = tmp_path / 'notes.draftsExport'
    source.write_text(json.dumps([{'content': 'good'}, {'content': 4},
                                 {'content': 'bad date', 'created_at': 'yesterday'}]))
    plan = preview_import(vault, source)
    assert plan.ready == 1 and len(plan.warnings) == 2
    assert len(apply_import(vault, plan).imported) == 1


def test_import_timestamp_option_never_updates_existing(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('original')
    vault.save(note)
    note.body = 'changed'
    with pytest.raises(ValueError, match='new notes'):
        vault.save(note, preserve_updated=True)
    assert vault.read(note.id).body == 'original'


def test_cli_folder_preview_then_apply(tmp_path):
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / 'one.md').write_text('One')
    command = [sys.executable, '-m', 'jotline', '--vault', str(tmp_path / 'vault'), 'import', str(folder)]
    preview = subprocess.run(command, capture_output=True, text=True)
    assert preview.returncode == 0 and 'Preview only' in preview.stdout
    assert not Vault(tmp_path / 'vault').notes()
    applied = subprocess.run([*command, '--apply'], capture_output=True, text=True)
    assert applied.returncode == 0 and 'Imported 1' in applied.stdout


@pytest.mark.asyncio
async def test_recovery_dialog_choices_and_literal_text():
    app = App()
    async with app.run_test(size=(90, 40)) as pilot:
        choices = []
        await app.push_screen(RecoveryScreen('my [bold]draft', 'external'), choices.append)
        assert app.screen.query_one('#recovery-local').text == 'my [bold]draft'
        await pilot.click('#preserve-reload')
        assert choices == ['preserve-reload']
        await app.push_screen(RecoveryScreen('mine', None, 'File removed'), choices.append)
        assert app.screen.query_one('#preserve-reload').disabled
        await pilot.press('escape')
        assert choices[-1] is None


@pytest.mark.asyncio
async def test_import_dialog_cancel_does_not_write(tmp_path):
    source = tmp_path / 'source.md'
    source.write_text('import me')
    vault = Vault(tmp_path / 'vault')
    app = App()
    async with app.run_test() as pilot:
        result = []
        await app.push_screen(ImportPreviewScreen(preview_import(vault, source)), result.append)
        await pilot.press('escape')
        assert result == [False] and not vault.notes()


@pytest.mark.asyncio
async def test_recovery_preserves_buffer_before_external_reload(tmp_path):
    from jotline.app import Jotline
    from textual.widgets import TextArea
    vault = Vault(tmp_path)
    note = vault.new('baseline')
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(90, 40)) as pilot:
        app.autosave_timer.stop()
        app.query_one('#editor', TextArea).load_text('unsaved local')
        other = vault.read(note.id)
        other.body = 'external edit'
        vault.save(other)
        app.show_recovery_dialog()
        await pilot.pause()
        await pilot.click('#preserve-reload')
        await pilot.pause()
        assert app.current.id == note.id and app.current.body == 'external edit'
        assert any(n.id != note.id and n.body == 'unsaved local' for n in vault.notes())


@pytest.mark.asyncio
async def test_failed_recovery_leaves_dirty_buffer(tmp_path, monkeypatch):
    from jotline.app import Jotline
    from textual.widgets import TextArea
    vault = Vault(tmp_path)
    note = vault.new('baseline')
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(90, 40)) as pilot:
        app.autosave_timer.stop()
        app.query_one('#editor', TextArea).load_text('unsaved local')
        app.show_recovery_dialog()
        def failure(note):
            raise OSError('Disk full')
        monkeypatch.setattr(vault, 'recovery', failure)
        await pilot.pause()
        await pilot.click('#preserve-reload')
        assert app.query_one('#editor', TextArea).text == 'unsaved local'
        assert app.current.id == note.id and app.dirty


def test_invalid_import_entries_are_bounded(tmp_path, monkeypatch):
    import jotline.importing as importing
    monkeypatch.setattr(importing, 'MAX_IMPORT_ENTRIES', 3)
    source = tmp_path / 'bad.draftsExport'
    source.write_text(json.dumps([None] * 20))
    plan = preview_import(Vault(tmp_path / 'vault'), source)
    assert len(plan.warnings) == 4 and not plan.items


def test_folder_import_warns_and_continues_after_unreadable_entry(tmp_path, fault_entry_stat):
    from jotline.importing import fs

    source = tmp_path / 'source'
    source.mkdir()
    (source / 'unreadable.md').write_text('unreadable', encoding='utf-8')
    (source / 'good.md').write_text('import me', encoding='utf-8')
    vault = Vault(tmp_path / 'vault')

    def fail():
        raise PermissionError('entry cannot be read')

    fault_entry_stat(fs, 'unreadable.md', fail)
    plan = preview_import(vault, source)
    assert plan.ready == 1
    assert any('unreadable.md' in warning and 'entry cannot be read' in warning for warning in plan.warnings)
    result = apply_import(vault, plan)
    assert not result.errors
    assert len(result.imported) == 1
    assert vault.read(result.imported[0]).body == 'import me'
