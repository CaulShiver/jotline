import pytest
from textual.color import Color
from jotline.app import Jotline
from jotline.capture_ui import QuickCapture
from jotline.markdown_editor import reading_line_style
from jotline.settings import BUILTIN_THEMES, PALETTES, THEMES, Settings
from jotline.store import Vault
from jotline.themes import jotline_theme


def luminance(color: str) -> float:
    r, g, b = (channel / 255 for channel in Color.parse(color).rgb)
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_theme_names_keep_default_first_and_omarchy_last():
    assert THEMES[0] == 'jotline' and THEMES[-1] == 'omarchy'
    assert set(PALETTES) <= set(THEMES) and set(BUILTIN_THEMES) <= set(THEMES)
    assert len(set(THEMES)) == len(THEMES)


@pytest.mark.parametrize('name', PALETTES)
def test_palette_text_and_accents_are_readable(name):
    palette = PALETTES[name]
    for role in ('foreground', 'primary', 'accent'):
        assert contrast(palette[role], palette['background']) >= 4.5, (name, role)
    assert jotline_theme(name).dark == palette.get('dark', True)


async def test_every_listed_theme_is_registered_on_both_apps(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        assert set(THEMES) <= set(app.available_themes)
    capture = QuickCapture('inbox')
    async with capture.run_test():
        assert set(THEMES) <= set(capture.available_themes)


def test_saved_settings_accept_new_theme_names(tmp_path):
    path = tmp_path / '.jotline-settings.json'
    for name in PALETTES:
        Settings(theme=name).save(path)
        assert Settings.load(path)[0].theme == name


def test_light_themes_get_a_faint_current_line_band():
    background = Color.parse(PALETTES['jotline-light']['background'])
    band = reading_line_style(jotline_theme('jotline-light'), background).bgcolor
    assert contrast(band.get_truecolor().hex, background.hex) < 1.3
