import pytest
from types import SimpleNamespace
from textual.widgets import Input, Static, TextArea

from jotline.app import Jotline
from jotline.search import compile_query
from jotline.store import Vault


@pytest.mark.parametrize('value', ['20260912', '2026-W37-6', '2026-w37-6'])
@pytest.mark.parametrize('field', ['created-after', 'created-before', 'updated-after', 'updated-before'])
def test_date_filters_reject_non_calendar_formats(value, field):
    with pytest.raises(ValueError, match='YYYY-MM-DD'):
        compile_query(field + ':' + value)


def test_date_filters_keep_inclusive_calendar_boundaries():
    note = SimpleNamespace(created='2026-09-12T12:00:00', updated='2026-09-12T12:00:00')
    for field in ('created', 'updated'):
        assert compile_query(f'{field}-after:2026-09-12 {field}-before:2026-09-12')(note)
        assert not compile_query(f'{field}-after:2026-09-13')(note)
        assert not compile_query(f'{field}-before:2026-09-11')(note)


async def test_find_navigation_uses_document_order_for_backward_selection(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        editor = app.query_one('#editor', TextArea)
        editor.load_text('cat cat cat')
        editor.move_cursor((0, 7))
        editor.move_cursor((0, 4), select=True)
        assert app.select_editor_match('cat', reverse=True) == (1, 3)
        editor.move_cursor((0, 7))
        editor.move_cursor((0, 4), select=True)
        assert app.select_editor_match('cat') == (3, 3)
        selection = editor.selection
        assert app.select_editor_match('') is None
        assert editor.selection == selection


async def test_rejected_single_replace_preserves_text_selection_and_status(tmp_path, monkeypatch):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.autosave_timer.stop()
        editor = app.query_one('#editor', TextArea)
        editor.load_text('cat cat')
        editor.move_cursor((0, 0))
        app.command('find')
        await pilot.pause()
        app.screen.query_one('#find-query', Input).value = 'cat'
        app.screen.query_one('#replace-value', Input).value = 'much longer'
        await pilot.pause()
        before = editor.selection
        monkeypatch.setattr('jotline.screens.EDIT_LIMIT_BYTES', 7)
        app.screen.replace_matches()
        assert editor.text == 'cat cat'
        assert editor.selection == before
        assert 'Not replaced' in str(app.screen.query_one('#find-status', Static).render())


async def test_single_replace_is_literal_and_can_be_undone(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('cat cat')
        editor.move_cursor((0, 0))
        app.command('find')
        await pilot.pause()
        app.screen.query_one('#find-query', Input).value = 'cat'
        app.screen.query_one('#replace-value', Input).value = r'\1'
        await pilot.pause()
        app.screen.replace_matches()
        assert editor.text == r'\1 cat'
        assert editor.selected_text == 'cat'
        await pilot.press('escape', 'ctrl+z')
        assert editor.text == 'cat cat'
