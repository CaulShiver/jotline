from textual.color import Color
from textual.widgets import TextArea

from jotline.app import Jotline, MarkdownPreview, Palette
from jotline.settings import THEMES
from jotline.store import Vault


async def test_mouse_selection_toolbar_format_undo_and_save(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(120, 36)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('hello world')
        await pilot.pause()
        inset = editor.content_region.x - editor.region.x
        await pilot.mouse_down(editor, offset=(inset, 0))
        await pilot.hover(editor, offset=(inset + 5, 0))
        await pilot.mouse_up(editor, offset=(inset + 5, 0))
        assert editor.selected_text == 'hello'
        await pilot.click('#md-bold')
        await pilot.pause()
        assert editor.text == '**hello** world'
        assert editor.has_focus
        await pilot.press('ctrl+z')
        assert editor.text == 'hello world'
        await pilot.press('ctrl+y', 'ctrl+s')
        assert app.vault.read(app.current.id).body == '**hello** world'


async def test_toolbar_more_and_preview_preserve_selection(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(120, 36)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('# Heading\n\nword')
        editor.move_cursor((2, 4))
        editor.move_cursor((2, 0), select=True)
        selection = editor.selection
        await pilot.click('#md-more')
        assert isinstance(app.screen, Palette)
        await pilot.press('escape')
        assert editor.selection == selection
        await pilot.click('#md-preview')
        assert isinstance(app.screen, MarkdownPreview)
        # The click opens a new screen; wait for its Markdown mount/render too.
        await pilot.pause()
        assert len(app.screen.query('MarkdownH1')) == 1
        await pilot.press('escape')
        assert editor.selection == selection
        await pilot.click('#md-italic')
        assert editor.text == '# Heading\n\n*word*'
        assert editor.has_focus


async def test_toolbar_scrolls_into_view_with_keyboard_in_narrow_terminal(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(40, 20)) as pilot:
        editor = app.query_one('#editor', TextArea)
        toolbar = app.query_one('#markdown-toolbar')
        editor.insert('narrow note')
        app.query_one('#md-bold').focus()
        await pilot.press(*(['tab'] * 8))
        preview = app.query_one('#md-preview')
        assert preview.has_focus
        assert preview.region.intersection(toolbar.content_region).width > 0
        assert editor.content_size.height > 5
        await pilot.press('enter')
        assert isinstance(app.screen, MarkdownPreview)
        await pilot.press('escape', 'ctrl+b')
        assert toolbar.has_class('hidden')
        await pilot.press('ctrl+b')
        assert not toolbar.has_class('hidden')


async def test_rendered_selection_keeps_markdown_colours_across_all_themes(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(120, 36)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.load_text('# Heading\nplain text')
        editor.move_cursor((0, 0))
        editor.move_cursor((1, 5), select=True)
        selection = editor.selection
        for name in THEMES:
            app.theme = name
            await pilot.pause()
            assert editor.selection == selection
            # Inspect the rendered heading, not just the registered palette.
            segments = list(editor.render_line(0))
            heading = next(segment for segment in segments if 'Heading' in segment.text)
            style = editor._theme.syntax_styles['heading']
            assert heading.style.color == style.color, name
            assert heading.style.bold, name
            if app.current_theme.ansi:
                assert heading.style.reverse, name
            else:
                background = Color.parse(app.get_css_variables()['background'])
                primary = Color.parse(app.current_theme.primary)
                expected = background.blend(primary, 0.30).rich_color
                if 'jotline-selection-background' in app.current_theme.variables:
                    expected = Color.parse(app.current_theme.variables['jotline-selection-background']).rich_color
                assert heading.style.bgcolor == expected, name
                assert expected != background.rich_color, name
            accent = Color.parse(app.current_theme.accent or app.current_theme.primary)
            if 'jotline-cursor-background' in app.current_theme.variables:
                accent = Color.parse(app.current_theme.variables['jotline-cursor-background'])
            assert editor._theme.cursor_style.bgcolor == accent.rich_color, name
