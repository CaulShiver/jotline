"""Synthetic regressions for outliner data preservation and hidden selections."""
import pytest

from textual.widgets import TextArea

from jotline.app import Jotline
from jotline.modal import Palette
from jotline.outliner import Block, Outline, dedent_line
from jotline.store import Vault


def outline_app(tmp_path, text):
    vault = Vault(tmp_path)
    note = vault.new(text)
    vault.save(note)
    return Jotline(vault, initial_note=note), note


async def test_restore_folded_grandparent_keeps_selection_visible(tmp_path):
    app, _ = outline_app(tmp_path, '- Grandparent\n  - Parent\n    - Child\n- Other')
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        screen.action_fold()
        screen.action_search()
        await pilot.pause()
        app.screen.dismiss(screen.outline.roots[0].children[0].children[0].uid)
        await pilot.pause()
        screen.action_restore_folds()
        assert screen.current is screen.outline.roots[0]
        assert screen.current in screen.view().blocks
        screen.action_extend(1)


@pytest.mark.parametrize('navigation', ['load_id', 'new', 'daily'])
async def test_navigation_saves_inline_edit_before_changed_event(tmp_path, navigation):
    app, note = outline_app(tmp_path, '- First')
    other = app.vault.new('- Other')
    app.vault.save(other)
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        screen.action_edit_block()
        screen.block_editor().insert_checked('!')
        if navigation == 'load_id':
            app.load_id(other.id)
        else:
            getattr(app, 'action_' + navigation)()
        await pilot.pause()
        assert app.vault.read(note.id).body == '- First!'
        assert app.current.id != note.id


async def test_save_flushes_inline_editor_below_palette(tmp_path):
    app, note = outline_app(tmp_path, '- First')
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        screen.action_edit_block()
        app.push_screen(Palette([('save', 'Save')], 'Commands'))
        await pilot.pause()
        screen.block_editor().insert_checked('!')
        assert app.save_current()
        assert app.vault.read(note.id).body == '- First!'


@pytest.mark.parametrize('action', ['home', 'restore_folds'])
async def test_limit_rejected_edit_survives_view_commands_and_blocks_navigation(tmp_path, monkeypatch, action):
    original = '- First\n- Other'
    app, note = outline_app(tmp_path, original)
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        monkeypatch.setattr('jotline.outliner_ui.EDIT_LIMIT_BYTES', len(original.encode()))
        screen.search_folds = {}
        screen.action_edit_block()
        screen.block_editor().insert_checked('!')
        await pilot.pause()
        getattr(screen, 'action_' + action)()
        assert screen.block_editor().text == 'First!'
        app.action_new()
        assert app.current.id == note.id
        assert screen.block_editor().text == 'First!'
        assert app.vault.read(note.id).body == original


@pytest.mark.parametrize('clipboard', ['- A\r\n- B\n- C', '- A\r- B\r- C'])
async def test_outline_paste_accepts_mixed_and_cr_only_newlines(tmp_path, clipboard):
    app, _ = outline_app(tmp_path, '- First')
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        app.copy_to_clipboard(clipboard)
        app.screen.action_paste_outline()
        assert app.editor().text == '- First\n- A\n- B\n- C'


@pytest.mark.parametrize('text', ['    - A\n    - B', '\t- A\n\t- B',
                                  '    1. A\n    2. B'])
def test_duplicate_opaque_code_preserves_every_raw_line(text):
    outline = Outline(text)
    clone = outline.duplicate(outline.roots[0])
    assert '\n'.join(clone.source_lines()) == text
    assert clone.uid != outline.roots[0].uid


@pytest.mark.parametrize('text, normalized', [
    ('- A\r\n- B\n- C', '- A\r\n- B\r\n- C'),
    ('- A\n- B\r\n- C', '- A\n- B\n- C'),
    ('- A\r- B', '- A\r- B'),
])
def test_outline_parser_uses_commonmark_newline_boundaries(text, normalized):
    outline = Outline(text)
    assert [block.content for block in outline.roots] == ['A', 'B', 'C'][:len(outline.roots)]
    assert outline.text == normalized


@pytest.mark.parametrize('text, labels', [
    ('- - ONE\n  - TWO', ['- ONE\n- TWO']),
    ('- - - ONE\n    - TWO\n- Other', ['- - ONE\n  - TWO', 'Other']),
    ('- Parent\n  - - Child\n    - Other\n  - Sibling',
     ['Parent', '- Child\n- Other', 'Sibling']),
])
def test_same_line_nested_lists_remain_opaque_without_overlapping_rows(text, labels):
    outline = Outline(text)
    assert outline.text == text
    assert [block.content for block in outline.walk()] == labels
    assert all(block.lines for block in outline.walk())
    assert len(set(outline.rows().values())) == len(list(outline.walk()))


async def test_delayed_layout_tolerates_editor_removed_during_teardown(tmp_path):
    app, note = outline_app(tmp_path, '- Parent\n  - Child')
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        # Child removal can finish before the parent processes its unmount.
        # A queued call_after_refresh must be harmless in that interval.
        await screen.block_editor().remove()
        assert screen.is_mounted
        screen.position_editor()
        assert app.editor().text == note.body


async def test_a_refused_structural_edit_does_not_leave_the_tree_ahead_of_the_note(tmp_path, monkeypatch):
    # The size guard refuses the write but the operation stayed in the live
    # tree, so block_rows described a note that did not exist. Every later
    # block edit was then written at a row belonging to a different block.
    original = '- AAAA\n- BBBB\n- CCCC'
    app, note = outline_app(tmp_path, original)
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        monkeypatch.setattr('jotline.outliner_ui.EDIT_LIMIT_BYTES', len(original.encode()))
        screen.action_duplicate()
        await pilot.pause()
        assert screen.outline.text == original  # The tree matches the refused note.

        monkeypatch.undo()
        screen.choose(screen.outline.roots[1])  # Move to the BBBB block.
        screen.action_edit_block()
        editor = screen.block_editor()
        editor.select_all()
        editor.replace('X', *sorted((editor.selection.start, editor.selection.end)))
        await pilot.pause(0.3)
        assert app.editor().text == '- AAAA\n- X\n- CCCC'
        assert 'CCCC' in app.editor().text


async def test_an_external_change_commits_the_open_block_before_re_deriving(tmp_path):
    # Re-deriving the outline reloads the block editor from the note, so a path
    # that re-derives without committing first throws away what was typed.
    app, note = outline_app(tmp_path, '- First\n- Second')
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        screen.action_edit_block()
        editor = screen.block_editor()
        with editor.prevent(TextArea.Changed):
            editor.insert_checked('IMPORTANT')
        app.editor().replace('\n- Third', app.editor().document.end, app.editor().document.end)
        screen.update_save_status()
        await pilot.pause()
        assert 'IMPORTANT' in app.editor().text or 'IMPORTANT' in editor.text


async def test_a_block_operation_does_not_rewrite_a_tab_as_spaces(tmp_path):
    # Indentation was rebuilt as spaces on every block operation, including
    # ones that reindent nothing. A tab inside a fenced code block is content,
    # so a Makefile recipe line in a note quietly stopped working.
    note = '- Build steps\n  ```make\n  all:\n  \techo hi\n  ```\n- Ship it'
    app, opened = outline_app(tmp_path, note)
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        app.screen.action_task()
        await pilot.pause(0.3)
        assert app.editor().text == '- [ ] Build steps\n  ```make\n  all:\n  \techo hi\n  ```\n- Ship it'


def test_dedenting_only_touches_the_columns_it_removes():
    assert dedent_line('  \techo hi', 2) == '\techo hi'
    assert dedent_line('  \techo hi', 0) == '  \techo hi'
    assert dedent_line('    echo hi', 2) == '  echo hi'
    assert dedent_line('\techo hi', 2) == '  echo hi'  # A straddling tab leaves spaces.
    assert dedent_line('  echo hi', 4) == '  echo hi'  # Less indentation than asked for.


MAKEFILE = '- Notes\n- Build steps\n  ```make\n  all:\n  \techo hi\n  ```'
NESTED_MAKEFILE = '- Notes\n  - Build steps\n    ```make\n    all:\n    \techo hi\n    ```'


def test_indent_then_outdent_restores_a_makefile_recipe_line():
    # Reindenting rebuilt every leading whitespace run as spaces, so the one
    # operation that really changes a block's indentation still turned the
    # recipe's tab into spaces. Only the item's own indentation is rewritten;
    # whitespace past its content column is content and stays verbatim.
    outline = Outline(MAKEFILE)
    outline.indent(outline.roots[1])
    assert outline.text == NESTED_MAKEFILE
    outline.outdent(outline.roots[0].children[0])
    assert outline.text == MAKEFILE


def test_outdenting_keeps_a_tab_inside_a_fenced_code_block():
    outline = Outline(NESTED_MAKEFILE)
    outline.outdent(outline.roots[0].children[0])
    assert outline.text == MAKEFILE


def test_shifting_rewrites_only_the_indentation_columns():
    # A tab straddling the content column is indentation up to that column and
    # content past it, so what the block's content measures does not change.
    block = Block(['- x', '\t\techo hi'])
    content = block.content
    block.shift(2)
    assert block.lines == ['  - x', '      \techo hi']
    assert block.content == content
    block.shift(-2)
    assert block.lines == ['- x', '    \techo hi']
    assert block.content == content


async def test_indent_and_outdent_keep_a_tab_in_the_note(tmp_path):
    app, opened = outline_app(tmp_path, MAKEFILE)
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        screen.selection = {screen.outline.roots[1].uid}
        screen.action_indent()
        await pilot.pause(0.3)
        assert app.editor().text == NESTED_MAKEFILE
        screen.action_outdent()
        await pilot.pause(0.3)
        assert app.editor().text == MAKEFILE
