from dataclasses import replace

from textual.widgets import Static, TextArea

from jotline.action_history import ActionHistory
from jotline.action_ui import ActionEditor
from jotline.app import Jotline, Palette, TextPrompt
from jotline.filesystem import fs
from jotline.recovery_ui import RecoveryScreen
from jotline.store import Vault


async def test_first_action_run_offers_starter_recipes(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.command('actions')
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        assert 'starter recipe' in app.screen.heading
        assert any(key == 'append-and-archive' for key, _ in app.screen.choices)
        assert not app.settings.actions
        await pilot.press('escape')


async def test_visible_actions_and_import_are_keyboard_reachable(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press('ctrl+f')
        await pilot.click('#nav-actions')
        assert isinstance(app.screen, Palette)
        await pilot.press(*'build', 'enter')
        await pilot.pause()
        assert isinstance(app.screen, ActionEditor)
        focused = app.focused
        await pilot.press('tab')
        assert app.focused is not focused
        original_id = app.current.id
        await pilot.press('ctrl+n')
        assert app.current.id == original_id
        await pilot.press('escape')
        await pilot.click('#nav-import')
        assert isinstance(app.screen, TextPrompt)
        await pilot.press('escape')
        assert app.current.id == original_id


async def test_autosave_conflict_opens_comparison_once_and_cancel_keeps_draft(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('original')
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test() as pilot:
        app.autosave_timer.stop()
        app.query_one('#editor', TextArea).load_text('my draft')
        external = vault.read(note.id)
        external.body = 'their edit'
        vault.save(external)
        assert not app.save_current()
        await pilot.pause()
        assert isinstance(app.screen, RecoveryScreen)
        depth = len(app.screen_stack)
        app.autosave()
        assert len(app.screen_stack) == depth
        await pilot.press('escape')
        app.autosave()
        assert not isinstance(app.screen, RecoveryScreen)
        assert app.query_one('#editor', TextArea).text == 'my draft'
        assert app.dirty and vault.read(note.id).body == 'their edit'


async def test_action_committed_warning_updates_editor_and_records_outcome(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    source = vault.new('source')
    vault.save(source)
    app = Jotline(vault, initial_note=source)
    async with app.run_test() as pilot:
        app.autosave_timer.stop()
        app.settings = replace(app.settings, actions={'upper': [{'type': 'uppercase'}]})
        real_save, real_fsync = vault.save, fs.fsync

        def save_then_fail(working):
            baseline = working.original

            def fail_committed(fd):
                if working.original != baseline:
                    raise OSError('directory durability check failed')
                return real_fsync(fd)

            with monkeypatch.context() as context:
                context.setattr(fs, 'fsync', fail_committed)
                real_save(working)

        monkeypatch.setattr(vault, 'save', save_then_fail)
        app.run_local_action('upper')
        await pilot.pause()
        assert app.query_one('#editor', TextArea).text == vault.read(source.id).body == 'SOURCE'
        assert app.current.original == vault.read(source.id).original
        assert not app.dirty
        assert 'durability warning' in str(app.query_one('#status', Static).render())
        assert ActionHistory(tmp_path).read()[-1]['status'] == 'committed-with-warning'


async def test_saved_action_output_uses_storage_limit_not_insertion_reserve(tmp_path, monkeypatch):
    import jotline.workflows as workflows
    vault = Vault(tmp_path)
    note = vault.new('source')
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test() as pilot:
        app.settings = replace(app.settings, actions={'upper': [{'type': 'uppercase'}]})
        monkeypatch.setattr(workflows, 'EDIT_LIMIT_BYTES', 1)
        app.run_local_action('upper')
        await pilot.pause()
        assert app.query_one('#editor', TextArea).text == 'SOURCE'
        assert app.current.body == vault.read(note.id).body == 'SOURCE'
        assert not app.dirty
