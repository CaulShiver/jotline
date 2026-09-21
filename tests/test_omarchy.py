from pathlib import Path

import pytest
from textual.color import Color
from textual.widgets import TextArea

from jotline.app import Jotline
from jotline.capture_ui import QuickCapture
from jotline.omarchy import MAX_PALETTE_BYTES, load_omarchy_theme, palette_paths
from jotline.settings import Settings
from jotline.store import Vault


PALETTE = '''
mode = "dark"
background = "#181a1f"
foreground = "#b9bec6"
accent = "#ad2222"
text_accent = "#ff5c5c"
cursor = "#eceff2"
selection_background = "#2b2f37"
readable_muted = "#8f949c"
'''


@pytest.fixture
def palette(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    path = palette_paths()[0]
    path.parent.mkdir(parents=True)
    path.write_text(PALETTE)
    return path


def test_palette_matches_desktop_and_respects_xdg(palette):
    theme = load_omarchy_theme()
    assert theme.background == '#181a1f'
    assert theme.primary == '#ad2222'
    assert theme.accent == '#ff5c5c'
    assert theme.variables['text-muted'] == '#8f949c'
    assert theme.dark


def test_legacy_path_and_inferred_light_mode(palette):
    legacy = palette_paths()[2]
    legacy.parent.mkdir(parents=True)
    palette.rename(legacy)
    legacy.write_text('background = "#ffffff"\nforeground = "#111111"\naccent = "#336699"\n')
    theme = load_omarchy_theme()
    assert theme is not None
    assert not theme.dark


def test_theme_directory_symlink_swap(palette, tmp_path):
    original = palette.parent
    first = original.with_name('first')
    original.rename(first)
    original.symlink_to(first, target_is_directory=True)
    assert load_omarchy_theme().primary == '#ad2222'
    second = original.with_name('second')
    second.mkdir()
    (second / 'colors.toml').write_text(PALETTE.replace('#ad2222', '#112233'))
    original.unlink()
    original.symlink_to(second, target_is_directory=True)
    assert load_omarchy_theme().primary == '#112233'


# Pytest exports the case ID as PYTEST_CURRENT_TEST. Embedding the oversized
# input in that ID exceeds Windows' 32,767-character environment value limit.
@pytest.mark.parametrize('data', [b'invalid toml', b'\xff', b'x' * (MAX_PALETTE_BYTES + 1),
                                  b'background = 42', PALETTE.replace('#ad2222', 'red').encode()],
                         ids=['invalid-toml', 'invalid-utf8', 'oversized', 'wrong-type', 'invalid-color'])
def test_invalid_palettes_are_ignored(palette, data):
    palette.write_bytes(data)
    assert load_omarchy_theme() is None


async def test_live_desktop_change_preserves_editing_and_manual_theme(tmp_path, palette):
    vault = Vault(tmp_path / 'notes')
    Settings(theme='omarchy').save(vault.path / '.jotline-settings.json')
    app = Jotline(vault)
    async with app.run_test(size=(120, 36)) as pilot:
        editor = app.query_one('#editor', TextArea)
        editor.insert('# Heading\ntext')
        editor.move_cursor((0, 0))
        editor.move_cursor((1, 2), select=True)
        selection = editor.selection
        assert app.current_theme.background == '#181a1f'
        assert editor._theme.cursor_style.bgcolor == Color.parse('#eceff2').rich_color
        assert editor._theme.selection_style.bgcolor == Color.parse('#2b2f37').rich_color
        palette.write_text(PALETTE.replace('#181a1f', '#f0f0f0').replace('"dark"', '"light"')
                           .replace('#eceff2', '#223344').replace('#2b2f37', '#cccccc'))
        for _ in range(20):
            if app.get_css_variables()['background'] == '#F0F0F0':
                break
            await pilot.pause(0.2)
        assert app.get_css_variables()['background'] == '#F0F0F0'
        assert not app.current_theme.dark
        assert editor._theme.cursor_style.bgcolor == Color.parse('#223344').rich_color
        heading = next(segment for segment in editor.render_line(0) if 'Heading' in segment.text)
        assert heading.style.bgcolor == Color.parse('#cccccc').rich_color
        assert heading.style.color == editor._theme.syntax_styles['heading'].color
        assert editor.selection == selection
        assert editor.has_focus
        palette.write_text('incomplete =')
        await pilot.pause(1.2)
        assert app.current_theme.background == '#f0f0f0'
        await pilot.press('ctrl+z')
        assert editor.text == ''
        assert app.omarchy_sync._timer is not None
        app.theme = 'nord'
        palette.write_text(PALETTE)
        await pilot.pause(1.2)
        assert app.theme == 'nord'
        assert app.omarchy_sync._timer is None


async def test_omarchy_poll_runs_only_while_theme_is_omarchy(tmp_path):
    vault = Vault(tmp_path / 'notes')
    app = Jotline(vault)
    async with app.run_test():
        assert app.theme != 'omarchy'
        assert app.omarchy_sync._timer is None
        app.theme = 'omarchy'
        assert app.omarchy_sync._timer is not None
        app.theme = 'jotline'
        assert app.omarchy_sync._timer is None


async def test_palette_refresh_invalidates_cached_selection_rows(tmp_path, palette):
    vault = Vault(tmp_path / 'notes')
    Settings(theme='omarchy').save(vault.path / '.jotline-settings.json')
    app = Jotline(vault)
    async with app.run_test(size=(120, 36)):
        editor = app.query_one('#editor', TextArea)
        editor.cursor_blink = False
        editor.load_text('# Heading\ntext')
        editor.move_cursor((0, 0))
        editor.move_cursor((1, 2), select=True)
        old = next(segment for segment in editor.render_line(0) if 'Heading' in segment.text)
        assert old.style.bgcolor == Color.parse('#2b2f37').rich_color
        palette.write_text(PALETTE.replace('#2b2f37', '#cccccc'))
        app.omarchy_sync.refresh()
        # Exercise the theme notification before unrelated layout or cursor
        # events get a chance to evict the old rendered row.
        editor._app_theme_changed()
        assert editor._theme.selection_style.bgcolor == Color.parse('#cccccc').rich_color
        updated = next(segment for segment in editor.render_line(0) if 'Heading' in segment.text)
        assert updated.style.bgcolor == Color.parse('#cccccc').rich_color


async def test_missing_palette_recovers_and_capture_follows(palette):
    palette.unlink()
    app = QuickCapture('Inbox', theme='omarchy')
    async with app.run_test() as pilot:
        assert app.theme == 'omarchy'
        assert app.current_theme.background == '#101619'
        await pilot.press('h', 'i')
        palette.write_text(PALETTE)
        await pilot.pause(1.2)
        assert app.current_theme.background == '#181a1f'
        editor = app.query_one(TextArea)
        assert editor.text == 'hi'
        assert editor._theme.cursor_style.bgcolor == Color.parse('#eceff2').rich_color
        assert editor._theme.selection_style.bgcolor == Color.parse('#2b2f37').rich_color
        assert app.omarchy_sync._timer is not None


def test_a_malformed_theme_file_does_not_stop_jotline_starting(tmp_path, monkeypatch):
    # Omarchy themes come from third-party git repos, and the sync object is
    # built whether or not the theme is in use. Deeply nested TOML raises
    # RecursionError, which is not a ValueError, so a 1.8 KB file stopped the
    # app with a traceback that never named the file.
    theme = tmp_path / ".local/state/omarchy/current/theme"
    theme.mkdir(parents=True)
    (theme / "colors.toml").write_text("a = " + "[" * 900 + "]" * 900 + "\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert load_omarchy_theme() is None
