from textual.widgets import Static, Switch, TextArea

from jotline.app import FindInNote, Jotline, Palette
from jotline.preferences import Preferences
from jotline.settings import Settings
from jotline.store import Vault


async def test_late_editor_event_after_shutdown_keeps_saved_note(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.query_one('#editor', TextArea).insert('save before shutdown')
        await pilot.press('ctrl+q')
    # A queued Changed message may arrive after shutdown has removed the editor.
    app.edited()
    assert app.current.body == 'save before shutdown'
    assert vault.read(app.current.id).body == 'save before shutdown'


async def test_palette_blocks_global_shortcuts(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        original = app.current.id
        await pilot.press('ctrl+p')
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        stack_size = len(app.screen_stack)

        await pilot.press('ctrl+n', 'ctrl+p')
        await pilot.pause()

        assert app.current.id == original
        assert len(app.screen_stack) == stack_size
        assert isinstance(app.screen, Palette)


async def test_default_collection_is_visible_and_labeled(tmp_path):
    Settings(default_collection='projects').save(tmp_path / '.jotline-settings.json')
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.collection == 'projects'
        assert str(app.query_one('#collection', Static).render()).startswith('PROJECTS')
        assert str(app.query_one('#note-heading', Static).render()).endswith('/ projects')

        await pilot.press('x', 'ctrl+s')
        await pilot.pause()
        assert vault.notes()[0].collection == 'projects'
        assert str(app.query_one('#collection', Static).render()).startswith('PROJECTS')


async def test_focus_on_start_does_not_change_current_session(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        app.command('settings')
        await pilot.pause()
        assert isinstance(app.screen, Preferences)
        app.screen.query_one('#pref-focus_on_start', Switch).value = True
        await pilot.press('ctrl+s')
        await pilot.pause()

        assert app.settings.focus_on_start
        assert not app.focused_writing
        assert not app.query_one('#sidebar').has_class('hidden')


async def test_preferences_reports_missing_number_in_plain_language(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        app.command('settings')
        await pilot.pause()
        app.screen.query_one('#pref-sidebar_width').value = ''
        app.screen.action_save()

        assert 'Sidebar width is required' in str(
            app.screen.query_one('#preferences-error', Static).render()
        )


async def test_link_picker_captures_pending_edit_as_dirty(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new('# Target')
    vault.save(target)
    app = Jotline(vault)
    async with app.run_test(size=(100, 30)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('unsaved')
        app.command('link')

        assert app.current.body == 'unsaved'
        assert app.dirty
        await pilot.press('escape', 'ctrl+q')

    assert any(note.body == 'unsaved' for note in vault.notes())


async def test_refresh_keeps_dirty_buffer_and_detects_conflict(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('# Original')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test(size=(100, 30)) as pilot:
        app.load_id(note.id)
        app.query_one('#editor', TextArea).load_text('# Local edit')
        external = vault.read(note.id)
        external.body = '# External edit'
        vault.save(external)

        app.command('refresh')
        await pilot.pause()

        assert app.query_one('#editor', TextArea).text == '# Local edit'
        assert app.current.body == '# Local edit'
        assert app.dirty
        assert not app.save_current()
        assert vault.read(note.id).body == '# External edit'


async def test_refresh_loads_clean_current_note_and_new_listing(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('# Original')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test(size=(100, 30)) as pilot:
        app.load_id(note.id)
        external = vault.read(note.id)
        external.body = '# Updated elsewhere'
        vault.save(external)
        added = vault.new('# Added elsewhere')
        vault.save(added)

        app.command('refresh')
        await pilot.pause()

        assert app.query_one('#editor', TextArea).text == '# Updated elsewhere'
        assert not app.dirty
        assert app.query_one('#notes').get_option(added.id) is not None


async def test_refresh_deleted_current_note_requires_recovery(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('# Kept in editor')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test(size=(100, 30)) as pilot:
        app.load_id(note.id)
        vault.file(note.id).unlink()

        app.command('refresh')
        await pilot.pause()

        assert app.query_one('#editor', TextArea).text == '# Kept in editor'
        assert app.dirty
        assert 'recovery available' in str(app.query_one('#status', Static).render())
        assert not app.save_current()


async def test_find_within_note_cycles_matches_and_returns_focus(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.load_text('Alpha beta alpha')
        editor.move_cursor((0, 0))
        app.command('find')
        await pilot.pause()
        assert isinstance(app.screen, FindInNote)

        await pilot.press(*'alpha')
        await pilot.pause()
        assert editor.selected_text == 'Alpha'
        await pilot.press('enter')
        await pilot.pause()
        assert editor.selection.start == (0, 11)
        await pilot.press('shift+f3')
        await pilot.pause()
        assert editor.selection.start == (0, 0)
        await pilot.press('escape')
        await pilot.pause()
        assert editor.has_focus


async def test_find_starts_at_cursor_on_later_line_with_unicode(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.load_text('café first\nignore\nCAFÉ third')
        editor.move_cursor((1, 3))
        app.command('find')
        await pilot.pause()

        await pilot.press(*'café')
        await pilot.pause()
        assert editor.selected_text == 'CAFÉ'
        assert editor.selection.start == (2, 0)
        context = app.screen.query_one('#find-context', Static).render()
        assert 'Line 3' in str(context)
        assert 'CAFÉ third' in str(context)


async def test_search_and_collection_view_restore_visible_hints(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        app.action_focus_mode()
        assert app.query_one('#hint').has_class('hidden')

        app.action_search()
        assert not app.query_one('#hint').has_class('hidden')
        app.action_focus_mode()
        app.command('view:projects')
        assert not app.query_one('#hint').has_class('hidden')


async def test_daily_read_error_keeps_current_editor(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        actual = app.vault.file('daily-' + __import__('datetime').date.today().isoformat())
        actual.write_text('---\njotline: 1\ncollection: "invalid"\n---\nbad', encoding='utf-8')
        app.query_one('#editor', TextArea).load_text('keep me')
        await pilot.pause()
        current_id = app.current.id
        app.action_daily()
        await pilot.pause()

        assert app.query_one('#editor', TextArea).text == 'keep me'
        assert app.current.id == current_id
