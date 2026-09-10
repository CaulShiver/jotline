from textual.widgets import Input, TextArea
from jotline.app import Jotline, Palette
from jotline.store import Vault


async def test_capture_switch_and_reopen(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.press('h', 'e', 'l', 'l', 'o')
        await pilot.press('ctrl+n')
        assert vault.notes()[0].body == 'hello'
        assert app.query_one(TextArea).text == ''
        await pilot.press('ctrl+o')
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        await pilot.press('enter')
        await pilot.pause()
        assert app.query_one(TextArea).text == 'hello'
        await pilot.press('ctrl+b')
        assert app.query_one('#sidebar').has_class('hidden')
        await pilot.press('ctrl+f')
        assert app.query_one('#search', Input).has_focus
        assert not app.query_one('#sidebar').has_class('hidden')


async def test_daily_palette_tasks_and_quit(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press('ctrl+d')
        await pilot.pause()
        assert app.current.id.startswith('daily-')
        editor = app.query_one(TextArea)
        editor.insert('Call Sam')
        app.command('task')
        await pilot.pause()
        assert '- [ ] Call Sam' in editor.text
        app.command('task')
        await pilot.pause()
        assert '- [x] Call Sam' in editor.text
        await pilot.press('ctrl+p')
        await pilot.press(*'move note to resources')
        await pilot.press('enter')
        await pilot.pause()
        assert app.current.collection == 'resources'
        await pilot.press('ctrl+q')
    assert vault.notes()[0].collection == 'resources'
    assert '- [x] Call Sam' in vault.notes()[0].body


async def test_conflict_blocks_navigation_and_recovery_preserves_text(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('Original')
    vault.save(note)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.load_id(note.id)
        external = vault.read(note.id)
        external.body = 'External'
        vault.save(external)
        app.query_one(TextArea).load_text('My unsaved writing')
        app.action_new()
        assert app.current.id == note.id
        assert app.query_one(TextArea).text == 'My unsaved writing'
        app.command('recovery')
        await pilot.pause()
        assert app.current.id != note.id
        assert vault.read(note.id).body == 'External'
        assert vault.read(app.current.id).body == 'My unsaved writing'


async def test_link_insertion_and_backlink_navigation(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new('# Target')
    vault.save(target)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.query_one(TextArea).insert('# Source\n\n')
        await pilot.pause()
        app.command('link')
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause()
        app.action_save()
        assert f'[[{target.id}|Target]]' in app.current.body
        source_id = app.current.id
        app.command('follow')
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause()
        assert app.current.id == target.id
        app.command('backlinks')
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause()
        assert app.current.id == source_id
