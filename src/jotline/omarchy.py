"""Read Omarchy's active palette without changing desktop configuration."""
from dataclasses import replace
import os
from pathlib import Path
import re
import stat
import tomllib

from textual.app import App
from textual.color import Color
from textual.theme import Theme

from .markdown_editor import JOTLINE_THEME

MAX_PALETTE_BYTES = 64 * 1024


def palette_paths() -> list[Path]:
    """Current Omarchy uses state; older versions used the config directory."""
    def xdg(name: str, fallback: Path) -> Path:
        value = Path(os.environ.get(name) or fallback)
        return value if value.is_absolute() else fallback

    home = Path.home()
    roots = [xdg('XDG_STATE_HOME', home / '.local/state'), home / '.local/state',
             xdg('XDG_CONFIG_HOME', home / '.config'), home / '.config']
    return list(dict.fromkeys(root / 'omarchy/current/theme/colors.toml' for root in roots))


def load_omarchy_theme() -> Theme | None:
    for path in palette_paths():
        try:
            # Theme directories may legitimately be symlinks. Avoid opening
            # special files, and bound the amount of configuration we parse.
            descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    continue
                raw = source.read(MAX_PALETTE_BYTES + 1)
            if len(raw) > MAX_PALETTE_BYTES:
                continue
            colors = tomllib.loads(raw.decode('utf-8'))

            # Called inside this iteration, so the palette it reads is this one.
            def color(key: str, fallback: str | None = None) -> str:  # noqa: B023
                value = colors.get(key, fallback)  # noqa: B023
                if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                    raise ValueError('Invalid palette color: ' + key)
                return value

            background = color('background')
            foreground = color('foreground')
            primary = color('accent')
            accent = color('text_accent', primary)
            selection = color('selection_background', Color.parse(background).blend(Color.parse(primary), .3).hex)
            cursor = color('cursor', foreground)
            mode = colors.get('mode')
            if mode is not None and mode not in ('light', 'dark'):
                raise ValueError('Invalid palette mode')
            variables = {
                'jotline-selection-background': selection,
                'jotline-cursor-background': cursor,
                'block-cursor-background': cursor,
                'block-cursor-foreground': background,
                'input-cursor-background': cursor,
                'input-cursor-foreground': background,
                'input-selection-background': selection,
                'input-selection-foreground': color('selection_foreground', foreground),
                'text-muted': color('readable_muted', foreground),
            }
            return Theme(
                name='omarchy', primary=primary, accent=accent,
                background=background, foreground=foreground,
                surface=color('lighter_bg', background), panel=color('lighter_bg', background),
                secondary=color('color6', accent), success=color('color2', foreground),
                warning=color('warning_text', color('color3', accent)),
                error=color('color1', accent), variables=variables,
                dark=mode == 'dark' if mode else Color.parse(background).brightness < .5,
            )
        except (OSError, ValueError, RecursionError):
            # Omarchy themes are installed from third-party git repos, and the
            # sync object is built whether or not the theme is in use, so a
            # malformed palette must degrade to the built-in theme rather than
            # stop Jotline starting. Deeply nested TOML raises RecursionError,
            # which is not a ValueError.
            continue
    return None


class OmarchySync:
    """Keep an opt-in theme current, retaining the last good palette on errors."""

    def __init__(self, app: App):
        self.app = app
        self.palette = load_omarchy_theme() or replace(JOTLINE_THEME, name='omarchy')
        self._timer = None
        app.register_theme(self.palette)

    def start(self) -> None:
        self.app.watch(self.app, 'theme', self._theme_changed)

    def _theme_changed(self, _old: str, theme: str) -> None:
        if theme == 'omarchy':
            if self._timer is None:
                self._timer = self.app.set_interval(1, self.refresh)
            return
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def refresh(self) -> None:
        if self.app.theme != 'omarchy':
            return
        palette = load_omarchy_theme()
        if palette is not None and palette != self.palette:
            self.palette = palette
            self.app.register_theme(palette)
            # The name stays the same, but its palette has changed. Notify the
            # normal theme watcher so CSS and mounted editors both refresh.
            self.app.mutate_reactive(App.theme)
