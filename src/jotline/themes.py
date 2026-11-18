"""Palettes Jotline defines itself, as plain data so settings can list the names.

Textual is imported only when themes are built, so settings.py can list the
names without importing Textual. Each palette is the keyword set for
``textual.theme.Theme``; ``dark`` defaults to True. Hex values come from each
project's published palette (see docs/theme-research.md), with a few accents
darkened within the family so they reach 4.5:1 against the background.
"""
from __future__ import annotations

PALETTES: dict[str, dict] = {
    'jotline': dict(primary='#a8d5a2', accent='#a8d5a2', foreground='#d6ddd8',
                    background='#101619', surface='#162024', panel='#162024'),
    'jotline-light': dict(
        dark=False, primary='#2f6b3a', secondary='#5b6b4a', accent='#2f6b3a', warning='#8a5a00',
        error='#a83232', success='#2f6b3a', foreground='#26332c',
        background='#f4efe3', surface='#ebe5d6', panel='#ebe5d6'),
    'everforest-dark': dict(
        primary='#a7c080', secondary='#7fbbb3', accent='#83c092', warning='#dbbc7f',
        error='#e67e80', success='#a7c080', foreground='#d3c6aa',
        background='#2d353b', surface='#343f44', panel='#3d484d'),
    'everforest-light': dict(
        dark=False, primary='#2a6f96', secondary='#8f4f8f', accent='#5f7300', warning='#9a5a00',
        error='#c8312e', success='#5f7300', foreground='#5c6a72',
        background='#fdf6e3', surface='#f4f0d9', panel='#efebd4'),
    'kanagawa': dict(
        primary='#7e9cd8', secondary='#957fb8', accent='#98bb6c', warning='#e6c384',
        error='#e46876', success='#98bb6c', foreground='#dcd7ba',
        background='#1f1f28', surface='#2a2a37', panel='#363646'),
    'gruvbox-light': dict(
        dark=False, primary='#076678', secondary='#8f3f71', accent='#3b7050', warning='#8f5c06',
        error='#9d0006', success='#3b7050', foreground='#3c3836',
        background='#fbf1c7', surface='#f2e5bc', panel='#ebdbb2'),
    'tokyo-night-day': dict(
        dark=False, primary='#2e5ab0', secondary='#7847bd', accent='#006c8f', warning='#8c5c00',
        error='#c4194a', success='#4b6631', foreground='#3760bf',
        background='#e1e2e7', surface='#e9e9ec', panel='#d0d5e3'),
    'ayu-mirage': dict(
        primary='#73d0ff', secondary='#dfbfff', accent='#ffcc66', warning='#ffa759',
        error='#ff6666', success='#87d96c', foreground='#cccac2',
        background='#1f2430', surface='#242936', panel='#2d3340'),
    'high-contrast': dict(
        primary='#ffff00', secondary='#ffffff', accent='#00ffff', warning='#ffd000',
        error='#ff6b6b', success='#00ff7f', foreground='#ffffff',
        background='#000000', surface='#0d0d0d', panel='#1a1a1a'),
}

# Plain TextAreas (dialogs, quick capture) paint the current line from CSS;
# MarkdownEditor uses reading_line_style. A faint tint keeps light themes legible.
CURSOR_LINE_CSS = """
TextArea .text-area--cursor-line { background: $foreground 18%; }
TextArea .text-area--cursor-gutter { background: $foreground 18%; text-style: bold; }
TextArea:light .text-area--cursor-line, TextArea:light .text-area--cursor-gutter { background: $foreground 8%; }
"""


def jotline_theme(name: str = 'jotline', palette: str | None = None):
    """A palette as a Textual theme. ``palette`` borrows another palette's colours under ``name``."""
    from textual.theme import Theme
    return Theme(name=name, **PALETTES[palette or name])


def register_themes(app) -> None:
    for name in PALETTES:
        app.register_theme(jotline_theme(name))
