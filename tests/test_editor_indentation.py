from dataclasses import replace

import pytest
from textual.widgets import Tooltip

from jotline.app import Jotline
from jotline.capture_ui import QuickCapture
from jotline.store import Vault


async def test_tab_enter_and_outdent_keep_writing_and_save(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        editor = app.editor()
        await pilot.press(*"Parent", "enter", "tab", *"Child", "enter", *"Sibling")
        assert editor.has_focus
        assert editor.text == "Parent\n  Child\n  Sibling"
        await pilot.press("shift+tab")
        assert editor.text == "Parent\n  Child\nSibling"
        assert editor.has_focus
        await pilot.press("ctrl+z")
        assert editor.text == "Parent\n  Child\n  Sibling"
        assert app.save_current()
        assert vault.read(app.current.id).body == editor.text


async def test_tab_indents_selected_lines_without_replacing_text(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.editor()
        editor.load_text("first\nsecond\nthird")
        # A backward selection ending at the next line's start excludes that line.
        editor.move_cursor((2, 0))
        editor.move_cursor((0, 0), select=True)
        await pilot.press("tab")
        assert editor.text == "  first\n  second\nthird"
        assert not editor.selection.is_empty
        await pilot.press("shift+tab")
        assert editor.text == "first\nsecond\nthird"
        await pilot.press("ctrl+z")
        assert editor.text == "  first\n  second\nthird"


async def test_tab_nests_lists_and_enter_continues_at_that_level(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.editor()
        await pilot.press(*"- Parent", "enter", "tab", *"Child", "enter")
        assert editor.text == "- Parent\n  - Child\n  - "
        await pilot.press("shift+tab", *"Sibling")
        assert editor.text == "- Parent\n  - Child\n- Sibling"


@pytest.mark.parametrize("body,cursor,expected", [
    ("    text", (0, 8), "    text\n    "),
    ("\ttext", (0, 5), "\ttext\n\t"),
    ("    text", (0, 2), "  \n    text"),
    ("```\n  code", (1, 6), "```\n  code\n  "),
    ("  first\r\n  second", (1, 8), "  first\r\n  second\r\n  "),
])
async def test_enter_preserves_indentation_without_smart_lists(tmp_path, body, cursor, expected):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.save_settings(replace(app.settings, smart_lists=False))
        editor = app.editor()
        editor.load_text(body)
        editor.move_cursor(cursor)
        await pilot.press("enter")
        assert editor.text == expected
        await pilot.press("ctrl+z")
        assert editor.text == body


async def test_editor_still_allows_keyboard_navigation(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.editor()
        await pilot.press("ctrl+tab")
        assert not editor.has_focus
        await pilot.press("escape")
        assert editor.has_focus
        await pilot.press("ctrl+shift+tab")
        assert not editor.has_focus
        await pilot.press("ctrl+f")
        assert app.query_one("#search").has_focus
        await pilot.press("tab")
        assert not app.query_one("#search").has_focus
        assert editor.text == ""


async def test_read_only_editor_cannot_be_indented(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.editor()
        editor.load_text("  unchanged")
        editor.read_only = True
        await pilot.press("enter", "shift+tab")
        editor.focus()
        await pilot.press("tab")
        assert editor.text == "  unchanged"


@pytest.mark.parametrize("capture", [False, True])
async def test_hover_descriptions_are_hidden(tmp_path, capture):
    app = QuickCapture("inbox") if capture else Jotline(Vault(tmp_path))
    app.TOOLTIP_DELAY = 0.01
    async with app.run_test(tooltips=True) as pilot:
        await pilot.hover("#capture-editor" if capture else "#editor")
        await pilot.pause(0.05)
        assert not app.screen.query_one(Tooltip).visible
        if not capture:
            await pilot.press("f1")
            await pilot.hover("#pref-theme")
            await pilot.pause(0.05)
            assert not app.screen.query_one(Tooltip).visible
