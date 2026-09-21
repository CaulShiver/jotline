"""What may reach a terminal.

Note text, filenames and titles are data the user was handed, often by an
import or a synced vault. Printed raw they are instructions: an escape
sequence can retitle the window, clear the screen, forge output, or write the
system clipboard through OSC 52, which Jotline itself relies on terminals
honouring. This module holds the one policy both the shell commands and the
terminal UI apply, and depends on nothing else in the package so either can
import it.
"""
from __future__ import annotations

import unicodedata

DISRUPTIVE_FORMAT = frozenset("  ‪‫‬‭‮⁦⁧⁨⁩")


def is_terminal_control(character: str) -> bool:
    """Whether a character can alter a terminal; tab and line breaks are ordinary note text."""
    return (unicodedata.category(character) in ("Cc", "Cs", "Cn") and character not in "\t\n\r") \
        or character in DISRUPTIVE_FORMAT


def has_terminal_controls(body: str) -> bool:
    return any(is_terminal_control(character) for character in body)


def terminal_text(value: object) -> str:
    """Render a one-line diagnostic without letting note or filename controls affect a terminal.

    Tabs and line breaks are escaped as well, so a name cannot forge a second line of output.
    """
    return "".join(character.encode("unicode_escape").decode("ascii")
                   if is_terminal_control(character) or character in "\n\r\t" else character
                   for character in str(value))


def one_line(value: str) -> str:
    """The same policy for text shown inside a widget, which supplies its own layout.

    Line breaks are escaped here too: a row of a list is one line, and text that
    can add another one can push the rest of the list around.
    """
    return terminal_text(value)
