from datetime import date
import zipfile
import subprocess
import sys

from textual.widgets import Input, TextArea

from jotline.app import Jotline, Palette, RevisionPreview
from jotline.store import Vault
from jotline.templates import Templates


async def test_template_creation_reuse_and_source_preserve_writing(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        body = '# Plan {{date}}\n{{workspace}}\n- [ ] Next'
        editor.insert(body)
        app.command('save-template')
        await pilot.pause()
        app.screen.query_one(Input).value = 'my-plan'
        await pilot.press('enter')
        assert Templates(tmp_path).read('my-plan') == body
        assert editor.text == body
        app.switch_workspace('work')
        editor.insert('Keep before template')
        app.use_template('my-plan')
        assert app.current.workspace == 'work'
        assert app.current.body == body.replace('{{date}}', date.today().isoformat()).replace('{{workspace}}', 'work')
        assert any(n.body == 'Keep before template' for n in app.vault.search(workspace='work'))
        app.use_template('meeting', source=True)
        assert '{{date}}' in editor.text
        assert app.save_current()


async def test_template_load_conflict_keeps_current_note(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('Original')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test():
        app.load_id(note.id)
        external = vault.read(note.id)
        external.body = 'External'
        vault.save(external)
        app.query_one('#editor', TextArea).load_text('Unsaved')
        app.use_template('meeting')
        assert app.current.id == note.id
        assert app.query_one('#editor', TextArea).text == 'Unsaved'


async def test_history_preview_cancel_restore_and_deleted_note(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('First version')
    vault.save(note)
    first = vault.history(note.id)[0].id
    note.body = 'Latest version'
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.query_one('#editor', TextArea).insert('Keep unfinished')
        current = app.current.id
        app.preview_revision(note.id, first)
        await pilot.pause()
        assert isinstance(app.screen, RevisionPreview)
        assert app.screen.query_one('#revision-text', TextArea).text == 'First version'
        await pilot.press('ctrl+n', 'escape')
        assert app.current.id == current
        assert app.query_one('#editor', TextArea).text == 'Keep unfinished'
        app.preview_revision(note.id, first)
        await pilot.pause()
        await pilot.click('#restore-revision')
        assert app.current.body == 'First version'
        assert app.current.id != note.id
        assert vault.read(note.id).body == 'Latest version'
        assert vault.read(current).body == 'Keep unfinished'
        vault.file(note.id).unlink()
        app.browse_history()
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        assert any(key == note.id for key, _ in app.screen.choices)
        await pilot.press('escape')


async def test_history_does_not_open_other_workspace_content(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('Work only', workspace='work')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test():
        app.preview_revision(note.id, vault.history(note.id)[0].id)
        assert not isinstance(app.screen, RevisionPreview)
        assert not vault.history_notes('default')


async def test_manual_backup_includes_current_buffer_and_templates(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        app.query_one('#editor', TextArea).insert('Current writing')
        app.save_template('writing')
        app.action_backup()
        archives = list((tmp_path / '.jotline-backups').glob('manual-*.zip'))
        assert len(archives) == 1
        with zipfile.ZipFile(archives[0]) as archive:
            assert b'Current writing' in archive.read(app.current.id + '.md')
            assert archive.read('.jotline-templates/writing.md') == b'Current writing'


def test_cli_backup_command(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('Local copy')
    vault.save(note)
    result = subprocess.run([sys.executable, '-m', 'jotline', '--vault', str(tmp_path), 'backup'],
                            text=True, capture_output=True, check=True)
    with zipfile.ZipFile(result.stdout.strip()) as archive:
        assert b'Local copy' in archive.read(note.id + '.md')
