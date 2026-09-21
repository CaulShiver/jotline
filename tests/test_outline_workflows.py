from jotline.app import Jotline
from jotline.modal import Palette
from jotline.outliner import Outline
from jotline.outliner_ui import OutlinerScreen
from jotline.settings import Settings
from jotline.store import Vault


async def open_outline(app, pilot, text):
    app.editor().load_text(text)
    await pilot.pause()
    app.action_outliner()
    await pilot.pause()
    return app.screen


async def test_enter_at_start_preserves_original_branch_and_undo(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- Parent\n  - Child\n- Other')
        screen.action_edit_block(False)
        await pilot.press('enter')
        assert app.editor().text == '- \n- Parent\n  - Child\n- Other'
        assert screen.current.content == ''
        await pilot.press('ctrl+z')
        assert app.editor().text == '- Parent\n  - Child\n- Other'


async def test_inline_navigation_wrap_unicode_and_resize(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(55, 25)) as pilot:
        text = '- ' + '漢🙂 wrapping ' * 10 + '\n- Next\n- Last'
        screen = await open_outline(app, pilot, text)
        screen.action_edit_block(False)
        assert screen.block_editor().wrapped_document.height > 1
        await pilot.press('down')
        assert screen.current is screen.outline.roots[0]
        screen.action_edit_block()
        await pilot.press('down')
        assert screen.current.content == 'Next'
        await pilot.press('up')
        assert screen.current is screen.outline.roots[0]
        await pilot.resize_terminal(90, 30)
        await pilot.pause()
        assert screen.block_editor().region.x > screen.view().region.x
        assert screen.block_editor().region.y >= screen.view().region.y
        assert app.editor().text == text


async def test_bulk_selection_indent_move_group_duplicate(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- A\n- B\n- C\n- D')
        screen.selection = {b.uid for b in screen.outline.roots[1:3]}
        screen.action_indent()
        assert app.editor().text == '- A\n  - B\n  - C\n- D'
        screen.action_outdent()
        assert app.editor().text == '- A\n- B\n- C\n- D'
        screen.action_move_up()
        assert app.editor().text == '- B\n- C\n- A\n- D'
        screen.action_move_up()
        assert app.editor().text == '- B\n- C\n- A\n- D'
        screen.action_group()
        assert app.editor().text == '- Group\n  - B\n  - C\n- A\n- D'
        screen.action_duplicate()
        assert len(screen.outline.roots) == 4
        assert [b.content for b in screen.outline.roots[1].children] == ['B', 'C']


async def test_search_hidden_result_restore_folds_and_navigation_history(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- Parent\n  - Secret\n- Other')
        screen.action_collapse_all()
        screen.action_search()
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        app.screen.dismiss(screen.outline.roots[0].children[0].uid)
        await pilot.pause()
        assert screen.current.content == 'Secret'
        assert not screen.current.parent.collapsed
        screen.action_zoom()
        screen.action_nav_back()
        assert screen.zoomed is None
        screen.action_restore_folds()
        assert screen.outline.roots[0].collapsed
        assert screen.current is screen.outline.roots[0]


async def test_fold_focus_and_caret_restored_on_reopen(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- Parent\n  - Child\n- Other')
        screen.action_zoom()
        screen.action_fold()
        uid = screen.current.uid
        screen.action_edit_block(False)
        screen.block_editor().move_cursor((0, 3))
        screen.action_done()
        await pilot.pause()
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        assert screen.current.content == 'Parent'
        assert screen.zoomed is screen.current
        assert screen.current.collapsed
        assert screen.block_editor().cursor_location == (0, 3)
        assert screen.current.uid != uid  # session identities never leak to notes


async def test_structural_text_paste_reconciles_and_preserves_parent_tail(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- Parent\n  - Child\n\n  Tail\n- Other')
        screen.choose(screen.outline.roots[0].children[0])
        screen.action_delete_branch()
        assert app.editor().text == '- Parent\n\n  Tail\n- Other'
        app.copy_to_clipboard('- New\n  - Sub')
        screen.action_paste_outline()
        assert [b.content for b in screen.current.children] == ['Sub']
        assert [(b.content, bool(b.parent)) for b in screen.outline.walk()] == [
            (b.content, bool(b.parent)) for b in Outline(app.editor().text).walk()]
        app.copy_to_clipboard('\n- Literal')
        screen.action_paste_text()
        # Pasting writes into the block editor, whose Changed message carries the
        # text back to the note when the queue next runs. Commit it here rather
        # than hope one pause pumps that message, so the assertion below waits
        # for the write-back instead of racing it.
        screen.flush()
        await pilot.pause()
        assert '\\- Literal' in app.editor().text


async def test_settling_commits_an_unfinished_block_edit_instead_of_dropping_it(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- Parent\n  - Child\n- Other')
        app.copy_to_clipboard('- New\n  - Sub')
        screen.action_paste_outline()
        app.copy_to_clipboard('\n- Literal')
        screen.action_paste_text()
        assert screen.block_editor().text == 'New\n\\- Literal'
        # A structural change leaves the tree waiting to be re-derived from the
        # note. That re-derivation reloads the block from the note, so it has to
        # take the editor's text with it; settling used to reload over the top
        # and lose whatever had not been committed yet.
        screen.settle()
        assert screen.block_editor().text == 'New\n\\- Literal'
        assert '\\- Literal' in app.editor().text


async def test_source_changes_and_note_navigation_stay_synchronized(tmp_path):
    vault = Vault(tmp_path)
    other = vault.new('- Different')
    vault.save(other)
    app = Jotline(vault)
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- First')
        app.action_format_markdown('bold')
        await pilot.pause()
        assert '**' in app.editor().text
        app.load_id(other.id)
        await pilot.pause()
        assert app.screen is screen
        assert screen.current.content == 'Different'
        screen.action_edit_block()
        await pilot.press('!')
        assert app.editor().text == '- Different!'
        await pilot.press('ctrl+d')
        await pilot.pause()
        assert app.current.id.startswith('daily-')
        assert screen.outline.text == app.editor().text


async def test_menu_continuation_works_without_shift_enter_and_custom_shortcut(tmp_path):
    Settings(outline_hotkeys={'new_child': 'f6'}).save(tmp_path / '.jotline-settings.json')
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- Parent')
        await pilot.press('f6', *'Child')
        assert screen.current.parent.content.strip() == 'Parent'
        await pilot.press('ctrl+p')
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        app.screen.dismiss('continuation')
        await pilot.pause()
        await pilot.press(*'Second line')
        assert screen.current.content == 'Child\nSecond line'


async def test_block_reference_and_duplicate_do_not_share_anchor(tmp_path):
    vault = Vault(tmp_path)
    note = vault.new('- Target\n  - Child\n- Ref')
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        screen.action_reference()
        target = app.clipboard[2:-2]
        assert target.startswith(note.id + '#^')
        screen.action_duplicate()
        assert '^' not in screen.outline.roots[1].content
        app.follow_wiki_target(target)
        assert screen.current.content.startswith('Target ^')
        assert screen.current.children[0].content == 'Child'


async def test_startup_preference_and_read_only_commands(tmp_path):
    Settings(outliner_on_start=True).save(tmp_path / '.jotline-settings.json')
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, OutlinerScreen)
        screen = app.screen
        source = app.editor().text
        app.editor().read_only = True
        screen.block_editor().read_only = True
        for action in ('group', 'duplicate', 'delete_branch', 'paste_outline', 'new_child', 'reference', 'merge'):
            getattr(screen, 'action_' + action)()
        assert app.editor().text == source


async def test_terminal_paste_defaults_to_literal_and_preserves_children(tmp_path):
    from textual import events
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- Parent\n  - Child')
        screen.action_edit_block()
        await screen.block_editor()._on_paste(events.Paste('\n- literal'))
        await pilot.pause()
        assert screen.outline.roots[0].children[0].content == 'Child'
        assert '\\- literal' in app.editor().text


async def test_custom_app_shortcuts_and_override_existing_outline_key(tmp_path):
    Settings(hotkeys={'commands': 'f9'}, outline_hotkeys={'new_child': 'f2'}).save(tmp_path / '.jotline-settings.json')
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        screen = await open_outline(app, pilot, '- Parent')
        await pilot.press('f2', *'Child', 'f9')
        await pilot.pause()
        assert screen.current.content == 'Child'
        assert isinstance(app.screen, Palette)
