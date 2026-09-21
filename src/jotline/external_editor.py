"""Hand a note's file to the editor the user already has configured.

Jotline is its own editor, and for a quick thought that is the point. For a
long rewrite it is a wall: the people this app is for have a configured Neovim
or Helix and no way to reach it. The vault is plain Markdown on disk, so
lending a file out and reading it back needs no format, no protocol and no
daemon — only the editor named in the environment.
"""
from __future__ import annotations

import os
import shlex

# Checked in this order, matching git, less and most other terminal programs.
EDITOR_VARIABLES = ("JOTLINE_EDITOR", "VISUAL", "EDITOR")

NO_EDITOR = ("No editor is configured. Set $EDITOR (or $VISUAL) in your shell "
             "to open this note where you normally write.")
ENCRYPTED = ("An encrypted note stays in Jotline. Its file on disk holds sealed "
             "text, so an external editor would only see the ciphertext.")
UNSAVED = "Write something first; an empty note has no file to open yet."


def configured_editor(environment: dict[str, str] | None = None) -> list[str]:
    """The editor command as argv, or an empty list when none is set.

    The value may carry arguments, as `EDITOR="code --wait"` does, so it is
    split the way a shell would without handing anything to a shell.
    """
    source = os.environ if environment is None else environment
    for name in EDITOR_VARIABLES:
        value = (source.get(name) or "").strip()
        if not value:
            continue
        try:
            command = shlex.split(value)
        except ValueError:
            # An unbalanced quote in $EDITOR is a shell problem, not a note one.
            continue
        if command:
            return command
    return []
