import pytest
from jotline.app import Jotline
from jotline.outliner import Outline
from jotline.outliner_ui import OutlinerScreen
from jotline.store import Vault


@pytest.mark.parametrize('body', [
    '', '- Parent\n  - Child\n    - Grandchild\n- Other\n',
    '# Heading\n\nParagraph\ncontinued.\n\n- [x] Task\n  continuation\n',
    '- Parent\r\n  - Child\r\n- Other\r\n',
    '```md\n- literal\n```\n\n- Real',
    '- Code\n  ```md\n  - literal\n  ```\n  - Real child',
    '- ```md\n  - literal\n  ```\n- Next',
    '- Parent\n\t- Child\n',
])
def test_loading_preserves_markdown_exactly(body):
    assert Outline(body).text == body


def test_fenced_bullets_are_not_blocks():
    outline = Outline('- Code\n  ```md\n  - literal\n  ```\n  - Child\n- Other')
    assert len(list(outline.walk())) == 3
    assert outline.roots[0].children[0].content == 'Child'


def test_move_indent_and_outdent_carry_descendants():
    outline = Outline('- First\n- Parent\n  - Child\n    - Grandchild\n- Last')
    parent = outline.roots[1]
    assert outline.indent(parent)
    assert outline.text == '- First\n  - Parent\n    - Child\n      - Grandchild\n- Last'
    assert outline.outdent(parent)
    assert outline.text == '- First\n- Parent\n  - Child\n    - Grandchild\n- Last'
    assert outline.move(parent, 1)
    assert outline.text == '- First\n- Last\n- Parent\n  - Child\n    - Grandchild'


def test_outdent_keeps_other_children_with_their_parent():
    outline = Outline('- Parent\n  - First\n    - Grandchild\n  - Second\n- Other')
    assert outline.outdent(outline.roots[0].children[0])
    assert outline.text == '- Parent\n  - Second\n- First\n  - Grandchild\n- Other'


async def open_outline(app, pilot, text):
    app.editor().load_text(text)
    await pilot.pause()
    app.action_outliner()
    await pilot.pause()
    assert isinstance(app.screen, OutlinerScreen)
    return app.screen


async def test_fold_focus_edit_autosave_and_return_preserve_hidden_text(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 35)) as pilot:
        screen = await open_outline(app, pilot, '- Parent\n  - Secret child\n- Other')
        await pilot.press('ctrl+space')
        assert screen.current.collapsed
        assert not screen.nodes[screen.current].is_expanded
        await pilot.press('alt+right')
        assert screen.zoomed is screen.current
        await pilot.press('f2', '!', 'ctrl+s')
        await pilot.pause()
        assert app.vault.read(app.current.id).body == '- Parent!\n  - Secret child\n- Other'
        await pilot.press('alt+left', 'escape', 'escape')
        assert not isinstance(app.screen, OutlinerScreen)
        assert app.editor().text == '- Parent!\n  - Secret child\n- Other'


async def test_enter_splits_block_and_shift_enter_stays_inside_block(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 35)) as pilot:
        screen = await open_outline(app, pilot, '- First second\n  - Child\n- Other')
        screen.action_edit_block()
        screen.block_editor().move_cursor((0, 6))
        await pilot.press('enter')
        assert app.editor().text == '- First \n  - Child\n- second\n- Other'
        await pilot.press('end', 'shift+enter', *'continuation')
        assert app.editor().text == '- First \n  - Child\n- second\n  continuation\n- Other'
        assert len(screen.outline.roots) == 3


async def test_keyboard_branch_operations_and_global_undo(tmp_path):
    app = Jotline(Vault(tmp_path))
    original = '- First\n- Parent\n  - Child\n- Last'
    async with app.run_test(size=(110, 35)) as pilot:
        await open_outline(app, pilot, original)
        await pilot.press('down', 'tab')
        assert app.editor().text == '- First\n  - Parent\n    - Child\n- Last'
        await pilot.press('shift+tab', 'alt+shift+down')
        assert app.editor().text == '- First\n- Last\n- Parent\n  - Child'
        await pilot.press('ctrl+z')
        assert app.editor().text == original
        await pilot.press('ctrl+y')
        assert app.editor().text == '- First\n- Last\n- Parent\n  - Child'


async def test_new_note_tasks_and_empty_child_outdent(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 35)) as pilot:
        await open_outline(app, pilot, '')
        await pilot.press('f2', *'Parent', 'enter', 'tab')
        assert app.editor().text == '- Parent\n\n  - '
        await pilot.press('enter')
        assert app.editor().text == '- Parent\n\n- '
        await pilot.press(*'Task', 'ctrl+enter')
        assert app.editor().text == '- Parent\n\n- [ ] Task'
        await pilot.press('ctrl+enter')
        assert app.editor().text == '- Parent\n\n- [x] Task'


async def test_switch_blocks_keeps_edits_and_does_not_add_undo_entries(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 35)) as pilot:
        screen = await open_outline(app, pilot, '- First\n- Second')
        await pilot.press('f2', '!', 'ctrl+tab', 'down', 'f2', '?', 'ctrl+tab', 'up')
        assert screen.block_editor().text == 'First!'
        assert app.editor().text == '- First!\n- Second?'
        await pilot.press('ctrl+z')
        assert app.editor().text == '- First!\n- Second'


async def test_read_only_outline_cannot_mutate_source(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 35)) as pilot:
        app.editor().read_only = True
        await open_outline(app, pilot, '- First\n- Second')
        await pilot.press('down', 'tab', 'ctrl+enter', 'alt+shift+up', 'f2', 'x', 'enter')
        assert app.editor().text == '- First\n- Second'


async def test_open_close_does_not_modify_existing_markdown(tmp_path):
    app = Jotline(Vault(tmp_path))
    original = '# Title\n\n- Parent\n  - Child\n\nLast paragraph.\n'
    async with app.run_test(size=(70, 24)) as pilot:
        screen = await open_outline(app, pilot, original)
        screen.action_collapse_all()
        screen.action_expand_all()
        screen.action_done()
        await pilot.pause()
        assert app.editor().text == original


def test_numbered_and_tab_indentation_survive_restructure_and_reload():
    outline = Outline('10. First\n11. Second\n\t- Child')
    second = outline.roots[1]
    assert outline.indent(second)
    assert outline.text == '10. First\n\n    11. Second\n        - Child'
    reloaded = Outline(outline.text)
    assert reloaded.roots[0].children[0].children[0].content == 'Child'
    assert outline.outdent(second)
    assert outline.text == '10. First\n\n11. Second\n    - Child'


async def test_block_selection_edit_and_undo_do_not_touch_children(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 35)) as pilot:
        screen = await open_outline(app, pilot, '- Parent\n  - Hidden child\n- Other')
        await pilot.press('ctrl+space', 'f2', 'f7', *'Replacement')
        assert app.editor().text == '- Replacement\n  - Hidden child\n- Other'
        await pilot.press('ctrl+z')
        # Textual checkpoints a selection replacement separately from the
        # subsequent typing, just as it does in the full Markdown editor.
        assert '  - Hidden child\n- Other' in app.editor().text
        await pilot.press('ctrl+z')
        assert screen.block_editor().text == 'Parent'
        assert app.editor().text == '- Parent\n  - Hidden child\n- Other'
        await pilot.press('ctrl+y', 'ctrl+y')
        assert app.editor().text == '- Replacement\n  - Hidden child\n- Other'


async def test_crlf_outline_edit_and_move_keep_line_endings(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 35)) as pilot:
        await open_outline(app, pilot, '- First\r\n- Parent\r\n  - Child')
        await pilot.press('down', 'f2', '!', 'tab')
        assert app.editor().text == '- First\r\n  - Parent!\r\n    - Child'
        await pilot.press('ctrl+s')
        assert app.vault.read(app.current.id).body == app.editor().text


async def test_delete_focused_branch_and_undo_restore_descendants(tmp_path):
    app = Jotline(Vault(tmp_path))
    original = '- Parent\n  - Child\n- Other'
    async with app.run_test(size=(110, 35)) as pilot:
        screen = await open_outline(app, pilot, original)
        await pilot.press('alt+right', 'ctrl+space', 'ctrl+shift+backspace')
        assert app.editor().text == '- Other'
        assert screen.zoomed is None
        await pilot.press('ctrl+z')
        assert app.editor().text == original
