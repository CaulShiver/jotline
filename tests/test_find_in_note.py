"""Literal whole-word find and replacement share document-aware boundaries."""
import pytest
from textual.widgets import Input, Static, Switch

from jotline.app import Jotline
from jotline.markdown_editor import literal_matches, literal_pattern
from jotline.store import Vault


@pytest.mark.parametrize(('body', 'query', 'expected'), [
    ('cat scatter catalog cat_ cat2 Cat cat.', 'cat', ['cat', 'Cat', 'cat']),
    ('café caféine décafé café.', 'café', ['café', 'café']),
    ('cafe cafe\u0301 uncafe cafe\u0301ine', 'cafe', ['cafe']),
    ('cafe\u0301 cafe\u0301ine café', 'cafe\u0301', ['cafe\u0301']),
    ('字 汉字 字。 字_ 2字', '字', ['字', '字']),
    ('C++ C++17 aC++ C++/Rust c++', 'C++', ['C++', 'C++', 'c++']),
    ('[a.b] a.b aXb prefixa.b a.bs', 'a.b', ['a.b', 'a.b']),
    ('(a+) (a+)b a(a+) (a+).', '(a+)', ['(a+)', '(a+)']),
    ('cat\ncat\rcat', 'cat', ['cat', 'cat', 'cat']),
    ('xfoo foo foo', 'foo foo', ['foo foo']),
    ('a+++', '++', ['++']),
])
def test_whole_word_boundaries_are_unicode_and_queries_are_literal(body, query, expected):
    matches = literal_matches(literal_pattern(query), body, whole_word=True)
    assert [match[0] for match in matches] == expected


def test_default_substring_and_case_sensitive_matching_are_unchanged():
    body = 'cat catalog Cat'
    assert [match[0] for match in literal_matches(literal_pattern('cat'), body)] == ['cat', 'cat', 'Cat']
    assert [match[0] for match in literal_matches(
        literal_pattern('cat', case_sensitive=True), body, whole_word=True)] == ['cat']


def test_only_rejected_matches_allow_overlapping_whole_word_candidates():
    pattern = literal_pattern('foo foo')
    assert [match.span() for match in literal_matches(pattern, 'xfoo foo foo', whole_word=True)] == [(5, 12)]
    assert [match.span() for match in literal_matches(pattern, 'foo foo foo', whole_word=True)] == [(0, 7)]


async def open_find(app, pilot, body, query, replacement=''):
    app.autosave_timer.stop()
    app.editor().load_text(body)
    app.editor().move_cursor((0, 0))
    app.command('find')
    await pilot.pause()
    screen = app.screen
    screen.query_one('#find-query', Input).value = query
    screen.query_one('#replace-value', Input).value = replacement
    screen.query_one('#find-word', Switch).value = True
    await pilot.pause()
    return screen


async def test_whole_word_navigation_case_toggle_and_reverse_selection(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        screen = await open_find(app, pilot, 'cat scatter Cat catalog cat.', 'cat')
        editor = app.editor()
        assert editor.selection == ((0, 0), (0, 3))
        assert 'Match 1 of 3' in str(screen.query_one('#find-status', Static).render())
        await pilot.press('f3')
        assert editor.selected_text == 'Cat'
        editor.move_cursor((0, 15))
        editor.move_cursor((0, 12), select=True)
        await pilot.press('shift+f3')
        assert editor.selection == ((0, 0), (0, 3))
        await pilot.press('shift+f3')
        assert editor.selection == ((0, 24), (0, 27))
        await pilot.press('f3')
        assert editor.selection == ((0, 0), (0, 3))
        screen.query_one('#find-case', Switch).value = True
        await pilot.pause()
        assert 'Match 1 of 2' in str(screen.query_one('#find-status', Static).render())
        await pilot.press('f3')
        assert editor.selection == ((0, 24), (0, 27))


async def test_single_replace_checks_context_and_undo(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        screen = await open_find(app, pilot, 'catalog cat', 'cat', r'\1')
        editor = app.editor()
        # A matching selection alone is insufficient: it is inside catalog.
        editor.move_cursor((0, 3))
        editor.move_cursor((0, 0), select=True)
        screen.replace_matches()
        assert editor.text == r'catalog \1'
        await pilot.press('escape', 'ctrl+z')
        assert editor.text == 'catalog cat'


async def test_replace_all_combines_literal_words_case_and_one_undo(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        original = 'C++ C++ish C++ c++'
        screen = await open_find(app, pilot, original, 'C++', r'\1')
        screen.query_one('#find-case', Switch).value = True
        await pilot.pause()
        screen.replace_matches(all_matches=True)
        assert app.editor().text == r'\1 C++ish \1 c++'
        assert 'Replaced 2 matches' in str(screen.query_one('#find-status', Static).render())
        await pilot.press('escape', 'ctrl+z')
        assert app.editor().text == original


@pytest.mark.parametrize('all_matches', [False, True])
async def test_whole_word_overlap_navigation_and_replacement_agree(tmp_path, all_matches):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        screen = await open_find(app, pilot, 'xfoo foo foo', 'foo foo', 'bar')
        assert app.editor().selection == ((0, 5), (0, 12))
        assert 'Match 1 of 1' in str(screen.query_one('#find-status', Static).render())
        screen.replace_matches(all_matches=all_matches)
        assert app.editor().text == 'xfoo bar'
        await pilot.press('escape', 'ctrl+z')
        assert app.editor().text == 'xfoo foo foo'


async def test_no_whole_word_matches_do_not_replace_a_partial_selection(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        screen = await open_find(app, pilot, 'catalog', 'cat', 'dog')
        editor = app.editor()
        editor.move_cursor((0, 0))
        editor.move_cursor((0, 3), select=True)
        before = editor.selection
        screen.replace_matches()
        assert editor.text == 'catalog' and editor.selection == before
        assert 'No matches' in str(screen.query_one('#find-status', Static).render())
        screen.replace_matches(all_matches=True)
        assert editor.text == 'catalog' and editor.selection == before
        assert 'Replaced 0 matches' in str(screen.query_one('#find-status', Static).render())
        screen.query_one('#find-query', Input).value = ''
        await pilot.pause()
        screen.replace_matches(all_matches=True)
        assert editor.text == 'catalog' and editor.selection == before


async def test_whole_word_replace_limits_count_only_eligible_matches(tmp_path, monkeypatch):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        screen = await open_find(app, pilot, 'cat catalog', 'cat', 'dogs')
        monkeypatch.setattr('jotline.screens.EDIT_LIMIT_BYTES', 12)
        screen.replace_matches(all_matches=True)
        assert app.editor().text == 'dogs catalog'


@pytest.mark.parametrize('all_matches', [False, True])
async def test_whole_word_replace_rejection_preserves_selection(tmp_path, monkeypatch, all_matches):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        screen = await open_find(app, pilot, 'cat catalog', 'cat', 'longer')
        before = app.editor().selection
        monkeypatch.setattr('jotline.screens.EDIT_LIMIT_BYTES', 12)
        screen.replace_matches(all_matches=all_matches)
        assert app.editor().text == 'cat catalog' and app.editor().selection == before
        assert 'Not replaced' in str(screen.query_one('#find-status', Static).render())


@pytest.mark.parametrize('size', [(60, 20), (80, 24)])
async def test_whole_word_option_is_keyboard_reachable_in_small_terminals(tmp_path, size):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=size) as pilot:
        screen = await open_find(app, pilot, 'cat catalog', 'cat')
        screen.query_one('#find-word', Switch).value = False
        screen.query_one('#find-query', Input).focus()
        await pilot.press('tab', 'tab', 'tab')
        option = screen.query_one('#find-word', Switch)
        assert option.has_focus
        assert option.region.right <= screen.size.width
        assert 0 <= option.region.y < screen.size.height
        await pilot.press('space')
        assert screen.whole_word
        assert 'Match 1 of 1' in str(screen.query_one('#find-status', Static).render())
        await pilot.press('escape')
        assert app.editor().has_focus
