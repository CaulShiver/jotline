import json
import os
import subprocess
import sys
from datetime import date
import pytest
from textual.widgets import Input, Select, Switch, TextArea
from jotline.app import Jotline
from jotline.preferences import Preferences
from jotline.settings import Settings, THEMES
from jotline.store import Vault


def test_validation_and_malformed_settings(tmp_path):
    path = tmp_path / '.jotline-settings.json'
    path.write_text('{broken')
    settings, warning = Settings.load(path)
    assert warning and settings == Settings()
    assert path.read_text() == '{broken'
    for bad in (Settings(sidebar_width=2), Settings(autosave_seconds=float('nan')),
                Settings(theme='missing'), Settings(soft_wrap='false')):
        with pytest.raises(ValueError):
            bad.save(path)
    assert path.read_text() == '{broken'


def test_all_bundled_themes_are_available_preferences():
    assert {'ansi-dark', 'ansi-light', 'atom-one-dark', 'atom-one-light', 'textual-dark'} <= set(THEMES)


async def test_settings_apply_persist_and_keep_editor(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(110, 40)) as pilot:
        app.query_one('#editor', TextArea).insert('Keep this unfinished thought')
        await pilot.press('ctrl+p')
        await pilot.press(*'settings')
        await pilot.press('enter')
        await pilot.pause()
        prefs = app.screen
        assert isinstance(prefs, Preferences)
        prefs.query_one('#pref-theme', Select).value = 'solarized-light'
        prefs.query_one('#pref-line_numbers', Switch).value = True
        prefs.query_one('#pref-soft_wrap', Switch).value = False
        prefs.query_one('#pref-sidebar_width', Input).value = '40'
        prefs.query_one('#pref-startup', Select).value = 'daily'
        prefs.query_one('#pref-default_collection', Select).value = 'projects'
        prefs.query_one('#pref-sort_order', Select).value = 'title'
        prefs.query_one('#daily-template', TextArea).load_text('# {{date}}\n\n## Priorities\n- [ ] ')
        await pilot.press('ctrl+s')
        await pilot.pause()
        assert not isinstance(app.screen, Preferences)
        assert app.theme == 'solarized-light'
        assert app.query_one('#editor', TextArea).show_line_numbers
        assert not app.query_one('#editor', TextArea).soft_wrap
        assert app.query_one('#editor', TextArea).text == 'Keep this unfinished thought'
        app.action_new()
        assert app.current.collection == 'projects'
    second = Jotline(vault)
    async with second.run_test() as pilot:
        await pilot.pause()
        assert second.theme == 'solarized-light'
        assert second.current.body.startswith(f'# {date.today()}\n\n## Priorities')
        assert second.query_one('#editor', TextArea).show_line_numbers
    assert vault.notes()[0].body == 'Keep this unfinished thought'


async def test_added_bundled_themes_can_be_applied(tmp_path):
    app = Jotline(Vault(tmp_path))
    added = {'ansi-dark', 'ansi-light', 'atom-one-dark', 'atom-one-light', 'textual-dark'}
    async with app.run_test() as pilot:
        await pilot.pause()
        assert added <= set(app.available_themes)
        for theme in added:
            app.save_settings(Settings(theme=theme))
            assert app.theme == theme


async def test_cancel_and_validation_do_not_change_settings(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.command('settings')
        await pilot.pause()
        prefs = app.screen
        prefs.query_one('#pref-sidebar_width', Input).value = '1'
        prefs.action_save()
        assert app.screen is prefs
        assert not app.settings_path.exists()
        await pilot.press('escape')
        assert app.settings == Settings()
        assert not app.settings_path.exists()


def test_daily_template_does_not_replace_existing_note(tmp_path):
    vault = Vault(tmp_path)
    note = vault.daily('custom {{date}}')
    vault.save(note)
    assert vault.daily('replacement').body == f'custom {date.today()}'


def test_which_field_survives_a_collision_does_not_depend_on_the_hash_seed(tmp_path):
    # _partial kept whichever fields validated together, iterating a set. String
    # hashing is randomised per process, so the same file kept the user's hotkey
    # map in some runs and discarded it in others -- and Settings.save then wrote
    # the loser back as empty, losing it for good.
    path = tmp_path / ".jotline-settings.json"
    path.write_text(json.dumps({"theme": "nord", "hotkeys": {"preview": "ctrl+g"},
                                "outline_hotkeys": {"indent": "ctrl+g"}}))
    probe = ("import json, pathlib, sys; from jotline.settings import Settings;"
             f"settings, warnings = Settings.load(pathlib.Path({str(path)!r}));"
             "print(json.dumps([settings.hotkeys, settings.outline_hotkeys]))")
    seen = set()
    for seed in ("0", "1", "2", "3", "4", "5", "6", "7"):
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, check=True,
                                text=True, timeout=60, env={**os.environ, "PYTHONHASHSEED": seed})
        seen.add(result.stdout.strip())
    assert len(seen) == 1, seen
    # The dependent field is the one rejected: outline_hotkeys validates
    # against the main map, so the map itself is what the user keeps.
    assert json.loads(seen.pop()) == [{"preview": "ctrl+g"}, {}]
