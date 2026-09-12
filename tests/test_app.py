from textual.widgets import Footer, Input, OptionList, Static, TextArea
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


async def test_compact_terminal_hides_chrome_and_keeps_writing_space(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.query_one('#sidebar').has_class('hidden')
        assert app.query_one('#hint', Static).has_class('hidden')
        assert app.query_one('#connections', Static).has_class('hidden')
        assert app.query_one(Footer).has_class('compact-footer')
        assert 'default' not in str(app.query_one('#status', Static).render())
        assert app.query_one(TextArea).has_focus


async def test_compact_navigation_reveals_search_tags_and_collections(tmp_path):
    vault = Vault(tmp_path)
    tagged = vault.new('# Project note\n#work')
    tagged.collection = 'projects'
    vault.save(tagged)
    app = Jotline(vault)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press('ctrl+f')
        await pilot.pause()
        assert not app.query_one('#sidebar').has_class('hidden')
        assert app.query_one('#search', Input).has_focus
        await pilot.press('escape')
        assert app.query_one('#sidebar').has_class('hidden')
        assert app.query_one(TextArea).has_focus

        await pilot.press('ctrl+t', 'enter')
        await pilot.pause()
        assert not app.query_one('#sidebar').has_class('hidden')
        assert app.query_one('#notes', OptionList).has_focus
        await pilot.press('escape')

        app.command('view:projects')
        await pilot.pause()
        assert not app.query_one('#sidebar').has_class('hidden')
        assert app.query_one('#notes', OptionList).has_focus


async def test_palette_explains_selection_and_empty_filters(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.push_screen(Palette([('new', 'New thought'), ('daily', 'Daily log')]))
        await pilot.pause()
        palette = app.screen
        assert 'Enter run' in str(palette.query_one('#palette-help', Static).render())
        assert '2 results' in str(palette.query_one('#command-count', Static).render())
        palette.query_one('#command-query', Input).value = 'missing'
        await pilot.pause()
        assert 'No matching commands' in str(palette.query_one('#command-count', Static).render())


async def test_compact_palette_scrolls_highlighted_result_into_view(tmp_path):
    app = Jotline(Vault(tmp_path))
    choices = [(str(index), f'Command {index:02}') for index in range(40)]
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(Palette(choices))
        await pilot.pause()
        options = app.screen.query_one('#commands', OptionList)
        await pilot.press(*(['down'] * 20))
        await pilot.pause()
        assert options.highlighted == 20
        assert options.scroll_y > 0


async def test_duplicate_note_choices_include_recovery_context(tmp_path):
    vault = Vault(tmp_path)
    first = vault.new('# Same\nFirst detail')
    first.collection = 'projects'
    vault.save(first)
    second = vault.new('# Same\nSecond detail')
    second.collection = 'areas'
    vault.save(second)
    app = Jotline(vault)
    choices = dict(app.note_choices([first, second]))
    assert 'projects' in choices[first.id]
    assert first.updated[:10] in choices[first.id]
    assert 'First detail' in choices[first.id]
    assert first.id[:8] in choices[first.id]
