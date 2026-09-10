from dataclasses import replace

import pytest
from textual.widgets import Input, TextArea

from jotline.app import Jotline, MarkdownPreview
from jotline.settings import HOTKEY_ACTIONS, Settings
from jotline.store import Vault


def test_markdown_defaults_preserve_existing_custom_shortcuts(tmp_path):
    settings = Settings(hotkeys={'new': 'ctrl+r', 'commands': 'f2'})
    settings.save(tmp_path / '.jotline-settings.json')
    loaded, warning = Settings.load(tmp_path / '.jotline-settings.json')
    assert not warning
    assert loaded.hotkeys == settings.hotkeys
    assert loaded.effective_hotkeys['new'] == 'ctrl+r'
    assert loaded.effective_hotkeys['commands'] == 'f2'
    assert all(loaded.effective_hotkeys[action] == ''
               for action, (default, _) in HOTKEY_ACTIONS.items() if not default)
    replace(loaded, hotkeys={**loaded.hotkeys, 'preview': '  '}).validate()


@pytest.mark.parametrize('hotkeys', [
    {'preview': 'ctrl+n'}, {'preview': 'f3', 'format_bold': 'f3'},
    {'format_bold': 'ctrl+b'}, {'preview': 'ctrl+c'}, {'preview': 'p'},
    {'preview': None}, {'new': ' '},
])
def test_optional_shortcuts_still_validate_conflicts_and_key_safety(hotkeys):
    with pytest.raises(ValueError):
        Settings(hotkeys=hotkeys).validate()


async def test_markdown_shortcuts_can_be_assigned_cleared_and_reset(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 40)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('word')
        await pilot.press('f1')
        prefs = app.screen
        assert prefs.query_one('#hotkey-preview', Input).value == ''
        prefs.query_one('#hotkey-preview', Input).value = 'f3'
        prefs.query_one('#hotkey-format_bold', Input).value = 'alt+b'
        await pilot.press('ctrl+s')
        editor.move_cursor((0, 0))
        editor.move_cursor((0, 4), select=True)
        await pilot.press('alt+b')
        assert editor.text == '**word**'
        await pilot.press('f3')
        assert isinstance(app.screen, MarkdownPreview)
        await pilot.press('alt+b')
        assert editor.text == '**word**'
        await pilot.press('escape', 'f1')
        app.screen.query_one('#hotkey-preview', Input).value = ''
        await pilot.press('ctrl+s', 'f3')
        assert not isinstance(app.screen, MarkdownPreview)
        assert app.settings.effective_hotkeys['format_bold'] == 'alt+b'
        await pilot.press('f1')
        app.screen.reset_hotkeys()
        await pilot.press('ctrl+s')
        before = editor.text
        await pilot.press('alt+b')
        assert editor.text == before
        assert app.settings.effective_hotkeys == Settings().effective_hotkeys
    loaded, warning = Settings.load(app.settings_path)
    assert not warning
    assert loaded.effective_hotkeys['preview'] == ''
    assert loaded.effective_hotkeys['format_bold'] == ''


@pytest.mark.parametrize('style,expected', [
    ('bold', '**word**'), ('italic', '*word*'), ('code', '`word`'),
    ('heading', '## word'), ('list', '- word'), ('quote', '> word'),
])
async def test_configured_formatting_shortcuts_dispatch(tmp_path, style, expected):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.save_settings(replace(app.settings, hotkeys={'format_' + style: 'f4'}))
        editor = app.query_one('#editor', TextArea)
        editor.insert('word')
        editor.move_cursor((0, 0))
        editor.move_cursor((0, 4), select=True)
        await pilot.press('f4')
        assert editor.text == expected
