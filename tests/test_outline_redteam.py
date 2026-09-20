"""Synthetic regressions for outliner data preservation and hidden selections."""
import pytest

from jotline.app import Jotline
from jotline.modal import Palette
from jotline.outliner import Outline
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
