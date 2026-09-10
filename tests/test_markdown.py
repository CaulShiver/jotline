import pytest
from textual.widgets import Markdown, TextArea

from jotline.app import Jotline, MarkdownPreview
from jotline.store import Vault


@pytest.mark.parametrize('style,expected', [
    ('bold', '**café**'), ('italic', '*café*'), ('code', '`café`'),
    ('heading', '## café'), ('list', '- café'), ('quote', '> café'),
])
async def test_format_selection_saves_and_can_undo(tmp_path, style, expected):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('café')
        editor.move_cursor((0, 4))
        editor.move_cursor((0, 0), select=True)  # Reverse selections work too.
        app.command('format:' + style)
        assert editor.text == expected
        assert app.save_current()
        assert app.vault.read(app.current.id).body == expected
        await pilot.press('ctrl+z')
        assert editor.text == 'café'


async def test_format_placeholder_line_boundary_and_backticks(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one('#editor', TextArea)
        app.command('format:bold')
        assert editor.text == '**text**'
        assert editor.selected_text == 'text'
        await pilot.press('x')
        assert editor.text == '**x**'
        editor.load_text('first\nsecond\nthird')
        editor.move_cursor((0, 0))
        editor.move_cursor((2, 0), select=True)
        app.command('format:quote')
        assert editor.text == '> first\n> second\nthird'
        editor.load_text('`literal`')
        editor.move_cursor((0, 0))
        editor.move_cursor((0, 9), select=True)
        app.command('format:code')
        assert editor.text == '`` `literal` ``'


async def test_preview_renders_unsaved_markdown_and_preserves_editor(tmp_path, monkeypatch):
    body = '# Heading\n\n**bold** and *italic*\n\n- item\n\n> quote\n\n```python\nx = 1\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n[link](https://example.com)'
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 35)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert(body)
        editor.move_cursor((0, 2))
        selection = editor.selection
        current = app.current.id
        await pilot.press('ctrl+p')
        await pilot.press(*'preview rendered')
        await pilot.press('enter')
        await pilot.pause()
        assert isinstance(app.screen, MarkdownPreview)
        assert len(app.screen.query('MarkdownH1')) == 1
        assert len(app.screen.query('MarkdownFence')) == 1
        assert len(app.screen.query('MarkdownTable')) == 1
        assert len(app.screen.query('MarkdownBlockQuote')) == 1
        opened = []
        monkeypatch.setattr(app, 'open_url', opened.append)
        markdown = app.screen.query_one(Markdown)
        markdown.post_message(Markdown.LinkClicked(markdown, 'https://example.com'))
        await pilot.press('ctrl+n', 'ctrl+p')
        assert isinstance(app.screen, MarkdownPreview)
        assert app.current.id == current
        assert opened == []
        await pilot.press('escape')
        assert editor.has_focus
        assert editor.text == body
        assert editor.selection == selection
        assert app.save_current()
        assert app.vault.read(current).body == body


async def test_large_preview_keeps_editable_buffer(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        editor = app.query_one('#editor', TextArea)
        body = ('é' * 100 + '\n') * 1310
        editor.load_text(body)
        app.action_preview()
        assert not isinstance(app.screen, MarkdownPreview)
        assert editor.text == body
        assert app.save_current()
