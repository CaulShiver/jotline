from textual.widgets import TextArea, OptionList
from jotline.app import Jotline
from jotline.note_menu import NoteMenu
from jotline.settings import Settings
from jotline.store import Vault


def save(vault, body):
    note = vault.new(body)
    vault.save(note)
    return note


async def test_right_click_moves_clicked_note_and_preserves_open_buffer(tmp_path):
    vault = Vault(tmp_path)
    first, second = save(vault, '# A'), save(vault, '# B')
    Settings(sort_order='title').save(tmp_path / '.jotline-settings.json')
    app = Jotline(vault)
    async with app.run_test(size=(100, 32)) as pilot:
        app.autosave_timer.stop()
        app.load_id(first.id)
        editor = app.query_one('#editor', TextArea)
        editor.insert('unfinished\n', (1, 0))
        before = editor.text
        await pilot.pause()
        await pilot.click('#notes', offset=(3, 3), button=3)
        assert isinstance(app.screen, NoteMenu)
        assert app.screen.title_text == 'B'
        assert app.current.id == first.id
        assert editor.text == before
        await pilot.click('#note-menu-options', offset=(2, 0))
        assert app.screen.title_text == 'Move to collection'
        await pilot.click('#note-menu-options', offset=(2, 0))
        assert vault.read(second.id).collection == 'projects'
        assert vault.read(first.id).body == before
        assert app.current.id == first.id and editor.text == before


async def test_right_click_cancel_blank_space_and_left_click(tmp_path):
    vault = Vault(tmp_path)
    note = save(vault, 'Click me')
    app = Jotline(vault)
    async with app.run_test(size=(100, 32)) as pilot:
        initial = app.current.id
        await pilot.click('#notes', offset=(3, 12), button=3)
        assert not isinstance(app.screen, NoteMenu)
        await pilot.click('#notes', offset=(3, 0), button=3)
        assert isinstance(app.screen, NoteMenu)
        await pilot.press('escape')
        assert app.current.id == initial
        await pilot.click('#notes', offset=(3, 0), button=3)
        await pilot.click(offset=(90, 28))
        assert not isinstance(app.screen, NoteMenu)
        assert vault.read(note.id).collection == 'inbox'
        await pilot.click('#notes', offset=(3, 0))
        assert app.current.id == note.id


async def test_delete_and_restore_from_context_menu(tmp_path):
    vault = Vault(tmp_path)
    note = save(vault, 'Delete me')
    app = Jotline(vault)
    async with app.run_test(size=(80, 24)) as pilot:
        app.load_id(note.id)
        app.show_navigation()
        await pilot.pause()
        await pilot.click('#notes', offset=(2, 0), button=3)
        await pilot.press('end', 'enter')
        assert vault.read(note.id).collection == 'trash'
        assert app.current.id != note.id
        app.show_collection('trash')
        await pilot.pause()
        await pilot.click('#notes', offset=(2, 0), button=3)
        assert ('restore', 'Restore to Inbox') in app.screen.choices
        await pilot.press('end', 'enter')
        assert vault.read(note.id).collection == 'inbox'


async def test_context_workspace_move_and_keyboard_menu(tmp_path):
    vault = Vault(tmp_path)
    note = save(vault, 'Move me')
    Settings(workspace_names=['default', 'work']).save(tmp_path / '.jotline-settings.json')
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.load_id(note.id)
        listing = app.query_one('#notes', OptionList)
        listing.highlighted = 0
        listing.focus()
        await pilot.press('shift+f10')
        assert isinstance(app.screen, NoteMenu)
        await pilot.press('down', 'enter')
        assert app.screen.title_text == 'Move to workspace'
        await pilot.press('enter')
        assert vault.read(note.id).workspace == 'work'
        assert app.current.id != note.id


async def test_context_move_conflict_keeps_both_notes(tmp_path):
    vault = Vault(tmp_path)
    note = save(vault, 'Original')
    app = Jotline(vault)
    async with app.run_test() as pilot:
        await pilot.click('#notes', offset=(2, 0), button=3)
        external = vault.read(note.id)
        external.body = 'Changed outside'
        vault.save(external)
        await pilot.press('end', 'enter')
        assert vault.read(note.id).body == 'Changed outside'
        assert vault.read(note.id).collection == 'inbox'


async def test_context_save_failure_and_daily_workspace_guard(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    note = save(vault, 'Keep')
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.load_id(note.id)
        editor = app.query_one('#editor', TextArea)
        editor.insert('pending')
        before = editor.text
        monkeypatch.setattr(vault, 'save', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
        app.move_context_note(note, collection='trash')
        assert app.current.collection == 'inbox'
        assert editor.text == before
        assert vault.read(note.id).collection == 'inbox'
        monkeypatch.undo()
        assert app.save_current()
        app.action_daily()
        editor.insert('Daily entry')
        assert app.save_current()
        app.show_navigation()
        app.refresh_notes()
        listing = app.query_one('#notes', OptionList)
        listing.focus()
        await pilot.press('shift+f10')
        assert isinstance(app.screen, NoteMenu)
        assert not any(key == 'workspace' for key, _ in app.screen.choices)


async def test_scrolled_row_targets_its_note_and_menu_stays_on_screen(tmp_path):
    vault = Vault(tmp_path)
    notes = [save(vault, f'Note {index:02d}') for index in range(25)]
    Settings(sort_order='title').save(tmp_path / '.jotline-settings.json')
    app = Jotline(vault)
    async with app.run_test(size=(80, 24)) as pilot:
        app.show_navigation()
        await pilot.pause()
        listing = app.query_one('#notes', OptionList)
        listing.highlighted = 24
        listing.scroll_to_highlight()
        await pilot.pause()
        # The last option's second line is at the bottom after scrolling.
        await pilot.click('#notes', offset=(2, listing.size.height - 1), button=3)
        assert isinstance(app.screen, NoteMenu)
        assert app.screen.title_text == 'Note 24'
        panel = app.screen.query_one('#note-menu')
        assert panel.region.bottom <= app.size.height
        await pilot.press('end', 'enter')
        assert vault.read(notes[-1].id).collection == 'trash'
        assert all(vault.read(note.id).collection == 'inbox' for note in notes[:-1])
