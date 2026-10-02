from dataclasses import replace

import pytest
from textual.widgets import Input, Static, TextArea

from jotline.app import Jotline, Palette
from jotline.navigation import KeySheet
from jotline.preferences import Preferences
from jotline.settings import Settings
from jotline.store import Vault


@pytest.mark.parametrize('hotkeys', [
    {'new': 'ctrl+p'}, {'new': 'n'}, {'new': 'ctrl+i'}, {'new': 'ctrl+c'},
    {'new': 'f0'}, {'new': 'escape'}, {'new': ''}, {'new': 'f13'},
    {'new': 'ctrl+n,ctrl+r'}, {'new': None}, {'unknown': 'f2'}, [],
])
def test_rejects_conflicts_unsafe_keys_and_bad_settings(hotkeys):
    with pytest.raises(ValueError):
        Settings(hotkeys=hotkeys).validate()


async def test_ctrl_comma_opens_settings_and_f1_the_key_sheet(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press('ctrl+comma')
        assert isinstance(app.screen, Preferences)
        await pilot.press('escape')
        await pilot.press('f1')
        assert isinstance(app.screen, KeySheet)


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
        await pilot.press('ctrl+comma')
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
        await pilot.press('f2', 'ctrl+comma')
        assert isinstance(app.screen, Palette)
        assert app.current.id == current
        await pilot.press('escape')
    second = Jotline(vault)
    async with second.run_test() as pilot:
        original = second.current.id
        await pilot.press('f2')
        assert second.current.id != original
        await pilot.press('ctrl+comma')
        assert isinstance(second.screen, Preferences)
        assert second.screen.query_one('#hotkey-new', Input).value == 'f2'


async def test_conflict_cancel_and_reset_hotkeys(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.press('ctrl+comma')
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
        await pilot.press('ctrl+comma')
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
        await pilot.press('ctrl+comma', 'alt+3')
        await pilot.pause()
        assert isinstance(app.screen, Preferences)
        assert app.screen.query_one('#hotkey-new', Input).has_focus
        await pilot.press('alt+4')
        await pilot.pause()
        assert app.screen.query_one('#daily-template', TextArea).has_focus


def test_new_defaults_step_aside_for_keys_people_already_use(tmp_path):
    settings = Settings(hotkeys={'format_bold': 'ctrl+g', 'tags': 'f1'}, outline_hotkeys={'duplicate': 'ctrl+l'})
    settings.save(tmp_path / '.jotline-settings.json')
    loaded, warning = Settings.load(tmp_path / '.jotline-settings.json')
    assert not warning
    hotkeys = loaded.effective_hotkeys
    assert (hotkeys['format_bold'], hotkeys['tags'], hotkeys['recent']) == ('ctrl+g', 'f1', 'ctrl+r')
    assert hotkeys['follow_link'] == hotkeys['keys'] == hotkeys['toggle_task'] == ''
    replace(loaded, hotkeys={**loaded.hotkeys, 'recent': ''}).validate()
    defaults = Settings().effective_hotkeys
    assert (defaults['recent'], defaults['follow_link'], defaults['toggle_task'], defaults['keys']) == (
        'ctrl+r', 'ctrl+g', 'ctrl+l', 'f1')
    assert defaults['previous_note'] == defaults['find_in_note'] == ''
    with pytest.raises(ValueError):
        Settings(hotkeys={'recent': 'ctrl+n'}).validate()


async def test_new_everyday_hotkeys_dispatch(tmp_path):
    from jotline.screens import FindInNote
    vault = Vault(tmp_path)
    target = vault.new('Target note')
    vault.save(target)
    app = Jotline(vault)
    async with app.run_test(size=(110, 40)) as pilot:
        app.save_settings(replace(app.settings, hotkeys={'previous_note': 'f5', 'find_in_note': 'f6'}))
        editor = app.query_one('#editor', TextArea)
        editor.insert('Source with [[Target note]]\n- [ ] chore')
        assert app.save_current(explicit=True)
        source = app.current.id
        await pilot.press('ctrl+l')
        assert editor.text.endswith('- [x] chore')
        editor.move_cursor((0, 16))
        await pilot.press('ctrl+g')
        assert app.current.id == target.id
        await pilot.press('ctrl+r')
        assert isinstance(app.screen, Palette)
        assert app.screen.choices[0][0] == source
        await pilot.press('enter')
        assert app.current.id == source
        await pilot.press('f5')
        assert app.current.id == target.id
        await pilot.press('f6')
        assert isinstance(app.screen, FindInNote)
        await pilot.press('escape', 'ctrl+p')
        assert any('ctrl+r' in label for key, label in app.screen.choices if key == 'recent')
        assert any('f5' in label for key, label in app.screen.choices if key == 'previous')
        assert any('ctrl+g' in label for key, label in app.screen.choices if key == 'follow')
