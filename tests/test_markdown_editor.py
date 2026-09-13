from dataclasses import replace

import pytest
from textual.widgets import Markdown, TextArea

from jotline.app import Jotline, MarkdownPreview, Palette
from jotline.markdown_editor import (MarkdownEditor, continuation, format_table, headings, highlight_markdown,
                                     table_bounds, toggle_lines)
from jotline.settings import Settings
from jotline.store import Vault


def names(highlights, row):
    return {name for _, _, name in highlights.get(row, [])}


def test_highlighting_covers_blocks_inline_and_skips_fenced_code():
    lines = ['# Title', 'Some **bold**, *italic*, ~~gone~~ and `code` #tag', '- [x] done', '> quoted',
             '```python', 'x = **not bold**', '```', '[site](https://example.com) [[abc|Note]]', '---',
             '| a | b |']
    highlights = highlight_markdown(lines)
    assert {'heading', 'heading.marker'} <= names(highlights, 0)
    assert {'bold', 'italic', 'strikethrough', 'inline_code', 'md.tag'} <= names(highlights, 1)
    assert {'list.marker', 'md.task.done', 'md.done'} <= names(highlights, 2)
    assert 'md.quote' in names(highlights, 3)
    assert names(highlights, 5) == {'md.code'}
    assert {'link.label', 'link.uri', 'md.wikilink'} <= names(highlights, 7)
    assert names(highlights, 8) == {'md.rule'}
    assert 'md.table' in names(highlights, 9)


def test_highlight_ranges_are_utf8_bytes():
    [(start, end, name)] = [h for h in highlight_markdown(['café **déjà**'])[0] if h[2] == 'bold']
    assert (start, end) == (len('café '.encode()), len('café **déjà**'.encode()))


def test_code_span_contents_are_not_emphasis():
    assert 'bold' not in names(highlight_markdown(['`**literal**`']), 0)


@pytest.mark.parametrize('line,expected', [
    ('- item', ('- ', False)),
    ('  * item', ('  * ', False)),
    ('9. item', ('10. ', False)),
    ('3) item', ('4) ', False)),
    ('- [x] done', ('- [ ] ', False)),
    ('> quote', ('> ', False)),
    ('> - nested', ('> - ', False)),
    ('- ', ('', True)),
    ('1. ', ('', True)),
    ('- [ ] ', ('', True)),
    ('> ', ('', True)),
    ('plain text', None),
    ('-not a list', None),
])
def test_continuation(line, expected):
    assert continuation(line, len(line)) == expected


def test_toggle_lines_replaces_and_removes_markers():
    assert toggle_lines(['## Title'], 'h1') == ['# Title']
    assert toggle_lines(['# Title'], 'h1') == ['Title']
    assert toggle_lines(['- a', '- b'], 'numbered') == ['1. a', '2. b']
    assert toggle_lines(['1. a', '2. b'], 'numbered') == ['a', 'b']
    assert toggle_lines(['a', '', 'b'], 'task') == ['- [ ] a', '', '- [ ] b']
    assert toggle_lines(['- [ ] a'], 'task') == ['a']
    assert toggle_lines(['  - a'], 'bullet') == ['  a']
    assert toggle_lines(['> a', '> b'], 'quote') == ['a', 'b']


def test_format_table_aligns_columns_and_keeps_alignment():
    table = ['|Name|Qty|', '|:-|-:|', '|Café|12|', '|x|']
    assert format_table(table) == [
        '| Name | Qty |',
        '| :--- | --: |',
        '| Café |  12 |',
        '| x    |     |',
    ]
    assert table_bounds(['text', *table, ''], 2) == (1, 4)
    assert table_bounds(['a | b'], 0) is None


def test_headings_skip_fenced_code():
    assert headings(['# One', '```', '# not', '```', '### Three ###']) == [(0, 1, 'One'), (4, 3, 'Three')]


async def test_enter_continues_and_ends_lists(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        assert isinstance(editor, MarkdownEditor)
        await pilot.press(*'- first', 'enter', *'second', 'enter', 'enter')
        assert editor.text == '- first\n- second\n'
        editor.load_text('1. one')
        editor.move_cursor(editor.document.end)
        await pilot.press('enter', 'x')
        assert editor.text == '1. one\n2. x'
        editor.load_text('```\n- code')
        editor.move_cursor(editor.document.end)
        await pilot.press('enter')
        assert editor.text == '```\n- code\n'
        await pilot.press('ctrl+z')
        assert editor.text == '```\n- code'


async def test_list_continuation_can_be_turned_off(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.save_settings(replace(app.settings, smart_lists=False, markdown_highlighting=False))
        editor = app.query_one('#editor', TextArea)
        await pilot.press(*'- a', 'enter')
        assert editor.text == '- a\n'
        assert not editor._highlights
    loaded, warning = Settings.load(app.settings_path)
    assert not warning and not loaded.smart_lists and not loaded.markdown_highlighting


async def test_editor_highlights_with_theme_colours(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.load_text('# Heading')
        await pilot.pause()
        assert editor.theme == MarkdownEditor.THEME_NAME
        assert names(editor._highlights, 0) >= {'heading'}
        first = editor._themes[MarkdownEditor.THEME_NAME].syntax_styles['heading']
        app.theme = 'nord'
        await pilot.pause()
        assert editor._themes[MarkdownEditor.THEME_NAME].syntax_styles['heading'] != first


def select(editor, start, end):
    editor.move_cursor(start)
    editor.move_cursor(end, select=True)


@pytest.mark.parametrize('style,formatted', [
    ('bold', '**word**'), ('italic', '*word*'), ('strike', '~~word~~'), ('code', '`word`'),
])
async def test_inline_formats_toggle_off(tmp_path, style, formatted):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        editor = app.query_one('#editor', TextArea)
        editor.load_text('word')
        select(editor, (0, 0), (0, 4))
        app.command('format:' + style)
        assert editor.text == formatted and editor.selected_text == 'word'
        app.command('format:' + style)
        assert editor.text == 'word' and editor.selected_text == 'word'
        if style == 'code':
            return  # Selected backticks are quoted literally; see test_markdown.py.
        select(editor, (0, 0), (0, 4))
        app.command('format:' + style)
        select(editor, (0, 0), (0, len(formatted)))
        app.command('format:' + style)
        assert editor.text == 'word'


async def test_italic_does_not_strip_half_of_bold(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        editor = app.query_one('#editor', TextArea)
        editor.load_text('**word**')
        select(editor, (0, 2), (0, 6))
        app.command('format:italic')
        assert editor.text == '***word***'
        app.command('format:bold')
        assert editor.text == '*word*'


async def test_links_images_rules_and_code_blocks(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        editor = app.query_one('#editor', TextArea)
        editor.load_text('Jotline')
        select(editor, (0, 0), (0, 7))
        app.command('format:link')
        assert editor.text == '[Jotline](url)' and editor.selected_text == 'url'
        editor.load_text('https://example.com')
        select(editor, (0, 0), (0, 19))
        app.command('format:image')
        assert editor.text == '![alt text](https://example.com)' and editor.selected_text == 'alt text'
        editor.load_text('a = 1\nb = 2')
        select(editor, (0, 0), (1, 5))
        app.command('format:codeblock')
        assert editor.text == '```\na = 1\nb = 2\n```'
        select(editor, (0, 0), (3, 3))
        app.command('format:codeblock')
        assert editor.text == 'a = 1\nb = 2'
        editor.load_text('Above')
        editor.move_cursor((0, 5))
        app.command('format:rule')
        assert editor.text == 'Above\n\n---\n\n'
        editor.load_text('- a\n- b')
        select(editor, (0, 0), (1, 3))
        app.command('format:indent')
        assert editor.text == '  - a\n  - b'
        app.command('format:outdent')
        assert editor.text == '- a\n- b'


async def test_heading_levels_and_numbered_lists_via_palette(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        editor = app.query_one('#editor', TextArea)
        editor.load_text('Title')
        app.command('format:h1')
        assert editor.text == '# Title'
        app.command('format:h3')
        assert editor.text == '### Title'
        editor.load_text('a\nb')
        select(editor, (0, 0), (1, 1))
        app.command('format:numbered')
        assert editor.text == '1. a\n2. b'
        app.command('format:task')
        assert editor.text == '- [ ] a\n- [ ] b'


async def test_table_insert_then_tidy(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        editor = app.query_one('#editor', TextArea)
        app.command('format:table')
        assert editor.text.splitlines()[:2] == ['| Column | Column |', '| ------ | ------ |']
        assert editor.selected_text == 'Column'
        editor.load_text('|a|bb|\n|-|-|\n|ccc|d|')
        editor.move_cursor((2, 1))
        app.command('format:table')
        assert editor.text == '| a   | bb  |\n| --- | --- |\n| ccc | d   |'
        assert app.save_current()
        assert app.vault.read(app.current.id).body == editor.text


async def test_outline_jumps_to_heading(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.load_text('# One\n\ntext\n\n## Two\n')
        app.command('outline')
        await pilot.pause()
        assert isinstance(app.screen, Palette)
        await pilot.press(*'two', 'enter')
        await pilot.pause()
        assert editor.cursor_location == (4, 0)
        assert editor.has_focus


async def test_live_preview_follows_typing(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(140, 40)) as pilot:
        editor = app.query_one('#editor', TextArea)
        pane = app.query_one('#live-preview')
        assert not pane.display
        app.command('live-preview')
        await pilot.pause()
        assert pane.display and editor.has_focus
        await pilot.press(*'# Live', 'enter', 'enter', *'- [ ] task')
        await pilot.pause(0.5)
        await pilot.pause()
        assert len(pane.query('MarkdownH1')) == 1
        assert '☐ task' in app._live_preview_text
        app.command('live-preview')
        await pilot.pause()
        assert not pane.display


async def test_live_preview_falls_back_to_full_preview_when_narrow(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(70, 30)) as pilot:
        app.command('live-preview')
        await pilot.pause()
        assert isinstance(app.screen, MarkdownPreview)
        assert not app.live_preview


async def test_preview_shows_checkboxes_and_link_titles(tmp_path):
    vault = Vault(tmp_path)
    target = vault.new('# Target note')
    vault.save(target)
    app = Jotline(vault)
    async with app.run_test(size=(100, 35)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.load_text(f'- [ ] open\n- [x] done\n\nSee [[{target.id}]]')
        app.action_preview()
        await pilot.pause()
        assert isinstance(app.screen, MarkdownPreview)
        source = app.screen.body
        assert '☐ open' in source and '☒ done' in source and 'See Target note' in source
        assert app.screen.query_one(Markdown)
