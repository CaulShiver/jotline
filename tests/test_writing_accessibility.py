"""Keyboard and visible-control qualification, not screen-reader certification."""
import pytest
from textual.widgets import Button, Input, Label, Static, Switch

from jotline.app import Jotline
from jotline.screens import FindInNote
from jotline.store import Vault


SIZES = [(60, 20), (80, 24), (100, 30)]


async def open_command(pilot, query):
    """Use the discoverable keyboard path, not app.command or widget clicks."""
    await pilot.press("ctrl+p", *query, "enter")
    await pilot.pause()


def assert_control_visible(screen, widget):
    """Check clipping too: an on-screen region may be hidden by its scroll parent."""
    assert widget.visible, widget.id
    assert screen.region.contains_region(widget.region), (widget.id, widget.region, screen.region)
    region = widget.region
    assert region.width and region.height, widget.id
    for x, y in ((region.x, region.y), (region.right - 1, region.bottom - 1)):
        hit, _ = screen.get_widget_at(x, y)
        assert hit is widget or widget in hit.ancestors, (widget.id, (x, y), hit.id)


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("theme", ["jotline", "textual-light"])
async def test_find_controls_are_named_visible_and_keyboard_reachable(tmp_path, size, theme):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=size) as pilot:
        app.autosave_timer.stop()
        app.theme = theme
        app.editor().load_text("cat catalog Cat\ncat")
        app.editor().move_cursor((0, 0))
        await open_command(pilot, "find within")
        screen = app.screen
        assert isinstance(screen, FindInNote)
        query = screen.query_one("#find-query", Input)
        assert query.has_focus
        # IDs are implementation details, not names a user can see or hear.
        expected_names = {
            "find-query": "Find text in this note",
            "replace-value": "Replacement text",
            "find-case": "Match case",
            "find-word": "Match whole words only",
        }
        for control_id, name in expected_names.items():
            assert str(screen.query_one(f"#{control_id}").tooltip) == name
        labels = {str(label.render()) for label in screen.query(Label)}
        assert {"Match case", "Whole word"} <= labels
        buttons = {button.id: str(button.label) for button in screen.query(Button)}
        assert buttons == {
            "replace-one": "Replace", "replace-all": "Replace all", "find-next": "Next",
            "find-previous": "Previous", "find-done": "Done",
        }
        await pilot.press(*"cat")
        assert "Match 1 of 4" in str(screen.query_one("#find-status", Static).render())
        assert "Line 1" in str(screen.query_one("#find-context", Static).render())
        await pilot.press("tab", "tab", "tab")
        whole_word = screen.query_one("#find-word", Switch)
        assert whole_word.has_focus
        assert_control_visible(screen, whole_word)
        await pilot.press("space")
        assert whole_word.value
        assert "Match 1 of 3" in str(screen.query_one("#find-status", Static).render())
        await pilot.press("shift+tab")
        assert screen.query_one("#find-case", Switch).has_focus
        await pilot.press("shift+tab", "shift+tab")
        assert query.has_focus
        expected_ids = set(expected_names) | set(buttons)
        reached = set()
        # Include the scroll container if Textual puts it in the focus chain,
        # but never allow focus to leak to the editor behind this modal.
        for _ in range(len(screen.focus_chain) + 1):
            focused = app.focused
            assert focused is not None and focused.screen is screen
            if focused.id in expected_ids:
                reached.add(focused.id)
                assert_control_visible(screen, focused)
            await pilot.press("tab")
        assert reached == expected_ids
        await pilot.press("escape")
        assert app.editor().has_focus
        assert app.editor().text == "cat catalog Cat\ncat"


@pytest.mark.parametrize("size", SIZES)
async def test_find_replace_all_and_undo_work_without_pointer(tmp_path, size):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=size) as pilot:
        app.autosave_timer.stop()
        original = "cat catalog cat"
        app.editor().load_text(original)
        app.editor().move_cursor((0, 0))
        await open_command(pilot, "find within")
        await pilot.press(*"cat", "tab", *"dog", "tab", "tab", "space", "tab", "tab")
        replace_all = app.screen.query_one("#replace-all", Button)
        assert replace_all.has_focus
        assert_control_visible(app.screen, replace_all)
        await pilot.press("enter")
        assert app.editor().text == "dog catalog dog"
        assert "Replaced 2 matches" in str(app.screen.query_one("#find-status", Static).render())
        await pilot.press("escape")
        assert app.editor().has_focus
        await pilot.press("ctrl+z")
        assert app.editor().text == original


@pytest.mark.parametrize("size", SIZES)
async def test_contents_can_filter_select_and_cancel_from_keyboard(tmp_path, size):
    from textual.widgets import OptionList
    from jotline.modal import Palette

    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=size) as pilot:
        app.autosave_timer.stop()
        original = "# First\n\n" + "paragraph\n\n" * 24 + "## Target\n\nTarget body\n"
        app.editor().load_text(original)
        app.editor().move_cursor((0, 0))
        await open_command(pilot, "contents")
        contents = app.screen
        assert isinstance(contents, Palette)
        assert str(contents.query_one("#palette-title", Label).render()).startswith("Table of contents")
        query = contents.query_one("#command-query", Input)
        assert query.has_focus and query.placeholder and query.tooltip
        assert_control_visible(contents, query)
        assert "2 results" in str(contents.query_one("#command-count", Static).render())
        await pilot.press("tab")
        options = contents.query_one("#commands", OptionList)
        assert options.has_focus
        assert_control_visible(contents, options)
        await pilot.press("shift+tab")
        assert query.has_focus
        await pilot.press("escape")
        assert app.editor().has_focus and app.editor().cursor_location == (0, 0)
        await open_command(pilot, "contents")
        await pilot.press(*"Target")
        assert "1 result" in str(app.screen.query_one("#command-count", Static).render())
        await pilot.press("down", "enter")
        assert app.editor().has_focus and app.editor().cursor_location == (50, 0)
        assert app.editor().text == original


@pytest.mark.parametrize("size", SIZES)
async def test_preview_contents_and_back_buttons_fit_and_restore_focus(tmp_path, size):
    from textual.containers import VerticalScroll
    from jotline.modal import Palette
    from jotline.screens import MarkdownPreview

    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=size) as pilot:
        app.autosave_timer.stop()
        original = "# First\n\n" + "paragraph\n\n" * 24 + "## Target\n\nTarget body\n"
        app.editor().load_text(original)
        await open_command(pilot, "rendered")
        preview = app.screen
        assert isinstance(preview, MarkdownPreview)
        scroll = preview.query_one("#markdown-scroll", VerticalScroll)
        assert scroll.has_focus
        contents_button = preview.query_one("#preview-contents", Button)
        assert str(contents_button.label) == "Contents"
        assert "Table of contents" in str(contents_button.tooltip)
        assert_control_visible(preview, contents_button)
        assert_control_visible(preview, preview.query_one("#close-preview", Button))
        for _ in range(len(preview.focus_chain)):
            await pilot.press("tab")
            if contents_button.has_focus:
                break
        assert contents_button.has_focus
        await pilot.press("enter")
        assert isinstance(app.screen, Palette)
        await pilot.press("escape")
        assert app.screen is preview and scroll.has_focus
        await pilot.press("ctrl+t", *"Target", "enter")
        await pilot.pause()
        assert app.screen is preview and scroll.has_focus
        assert scroll.scroll_y > 0
        await pilot.press("escape")
        assert app.editor().has_focus
        assert app.editor().text == original


@pytest.mark.parametrize("size", SIZES)
async def test_footnotes_only_contents_is_keyboard_navigable_and_keeps_source(tmp_path, size):
    """The contents palette supplies keyboard routes; inline links are not Tab stops."""
    from textual.containers import VerticalScroll
    from jotline.rendering import PreviewMarkdown
    from jotline.screens import MarkdownPreview

    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=size) as pilot:
        app.autosave_timer.stop()
        original = "Reference[^one].\n\n" + "paragraph\n\n" * 24 + "[^one]: Footnote definition café.\n"
        app.editor().load_text(original)
        await open_command(pilot, "rendered")
        preview = app.screen
        assert isinstance(preview, MarkdownPreview)
        scroll = preview.query_one("#markdown-scroll", VerticalScroll)
        assert scroll.has_focus
        markdown = preview.query_one(PreviewMarkdown)
        blocks = list(markdown.query("MarkdownBlock"))
        assert any("Reference[1]" in block._content.plain for block in blocks)
        definition = next(block for block in blocks if "Footnote definition café." in block._content.plain)
        assert "↩" in definition._content.plain
        await pilot.press("ctrl+t")
        assert "Table of contents" in str(app.screen.query_one("#palette-title", Label).render())
        await pilot.press(*"footnote 1", "enter")
        await pilot.pause()
        assert app.screen is preview and scroll.has_focus and scroll.scroll_y > 0
        assert_control_visible(preview, definition)
        await pilot.press("ctrl+t", *"return", "enter")
        await pilot.pause()
        assert app.screen is preview and scroll.has_focus and scroll.scroll_y == 0
        # Home/End scrolling remains available without going through a link.
        await pilot.press("end")
        await pilot.pause()
        assert scroll.scroll_y > 0
        await pilot.press("home")
        await pilot.pause()
        assert scroll.scroll_y == 0
        await pilot.press("escape")
        assert app.editor().has_focus and app.editor().text == original


def test_exported_footnote_links_have_descriptive_names_not_only_arrow_glyphs():
    from html.parser import HTMLParser
    from jotline.export import render_html

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.links.append(dict(attrs))

    document = Links()
    document.feed(render_html("Synthetic footnotes", "Reference[^one].\n\n[^one]: A definition."))
    reference = next(link for link in document.links if link.get("href") == "#jl-footnote-1")
    backlink = next(link for link in document.links if link.get("href") == "#jl-footnote-ref-1")
    assert reference.get("title") == "Footnote 1"
    assert backlink.get("title") == "Back to reference 1 of footnote 1"
