from dataclasses import replace

import pytest
from textual.widgets import Input, Static, TextArea

from jotline.app import Jotline, Palette
from jotline.preferences import Preferences
from jotline.settings import Settings
from jotline.store import Vault


@pytest.mark.parametrize('hotkeys', [
    {'new': 'ctrl+p'}, {'new': 'n'}, {'new': 'ctrl+i'}, {'new': 'ctrl+c'},
    {'new': 'f1'}, {'new': 'escape'}, {'new': ''}, {'new': 'f13'},
    {'new': 'ctrl+n,ctrl+r'}, {'new': None}, {'unknown': 'f2'}, [],
])
def test_rejects_conflicts_unsafe_keys_and_bad_settings(hotkeys):
    with pytest.raises(ValueError):
        Settings(hotkeys=hotkeys).validate()


def test_hotkey_defaults_partial_overrides_and_swaps(tmp_path):
    settings = Settings(hotkeys={'new': ' CTRL+P ', 'commands': 'ctrl+n', 'tags': 'alt+t'})
    settings.save(tmp_path / '.jotline-settings.json')
    loaded, warning = Settings.load(tmp_path / '.jotline-settings.json')
    assert not warning
    assert loaded.effective_hotkeys['new'] == 'ctrl+p'
    assert loaded.effective_hotkeys['commands'] == 'ctrl+n'
    assert loaded.effective_hotkeys['save'] == 'ctrl+s'


async def test_edit_hotkeys_apply_immediately_and_persist(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(110, 40)) as pilot:
        app.query_one('#editor', TextArea).insert('Keep this note')
        original = app.current.id
        await pilot.press('f1')
        assert isinstance(app.screen, Preferences)
        app.screen.query_one('#hotkey-new', Input).value = 'f2'
        app.screen.query_one('#hotkey-commands', Input).value = 'f4'
        await pilot.press('ctrl+s')
        await pilot.pause()
        assert app.current.id == original
        assert app.query_one('#editor', TextArea).text == 'Keep this note'
        assert 'f4 commands' in str(app.query_one('#hint', Static).render())
        assert 'f4' in str(app.query_one('#connections', Static).render())
        await pilot.press('ctrl+n')
        assert app.current.id == original
        await pilot.press('f2')
        assert app.current.id != original
        assert vault.read(original).body == 'Keep this note'
        await pilot.press('f4')
        assert isinstance(app.screen, Palette)
        assert any('f2' in label for key, label in app.screen.choices if key == 'new')
        current = app.current.id
        await pilot.press('f2', 'f1')
        assert isinstance(app.screen, Palette)
        assert app.current.id == current
        await pilot.press('escape')
    second = Jotline(vault)
    async with second.run_test() as pilot:
        original = second.current.id
        await pilot.press('f2')
        assert second.current.id != original
        await pilot.press('f1')
        assert isinstance(second.screen, Preferences)
        assert second.screen.query_one('#hotkey-new', Input).value == 'f2'


async def test_conflict_cancel_and_reset_hotkeys(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press('f1')
        prefs = app.screen
        prefs.query_one('#hotkey-new', Input).value = 'ctrl+p'
        await pilot.press('ctrl+s')
        assert app.screen is prefs
        assert 'assigned to both' in str(prefs.query_one('#preferences-error', Static).render())
        assert not app.settings_path.exists()
        prefs.query_one('#hotkey-new', Input).value = 'f2'
        await pilot.press('escape')
        assert app.settings.effective_hotkeys['new'] == 'ctrl+n'
        app.save_settings(replace(app.settings, theme='nord', hotkeys={'new': 'f2'}))
        await pilot.press('f1')
        app.screen.reset_hotkeys()
        await pilot.press('ctrl+s')
        assert app.settings.theme == 'nord'
        assert app.settings.effective_hotkeys['new'] == 'ctrl+n'
        original = app.current.id
        await pilot.press('f2')
        assert app.current.id == original
        await pilot.press('ctrl+n')
        assert app.current.id != original


async def test_swapped_shortcuts_and_failed_save(tmp_path, monkeypatch):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.save_settings(replace(app.settings, hotkeys={'new': 'ctrl+p', 'commands': 'ctrl+n'}))
        original = app.current.id
        await pilot.press('ctrl+p')
        assert app.current.id != original
        await pilot.press('ctrl+n')
        assert isinstance(app.screen, Palette)
        await pilot.press('escape')
        def fail_save(*args):
            raise OSError('Disk full')
        monkeypatch.setattr(Settings, 'save', fail_save)
        app.save_settings(replace(app.settings, hotkeys={'new': 'f2'}))
        assert app.settings.effective_hotkeys['new'] == 'ctrl+p'
        original = app.current.id
        await pilot.press('f2')
        assert app.current.id == original
        await pilot.press('ctrl+p')
        assert app.current.id != original


async def test_preferences_sections_are_keyboard_jumpable(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press('f1', 'alt+3')
        await pilot.pause()
        assert isinstance(app.screen, Preferences)
        assert app.screen.query_one('#hotkey-new', Input).has_focus
        await pilot.press('alt+4')
        await pilot.pause()
        assert app.screen.query_one('#daily-template', TextArea).has_focus
