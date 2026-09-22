"""The environment a helper process is started with.

Scripts hand jotline the passphrase in JOTLINE_PASSPHRASE, and anything
jotline then starts -- $EDITOR, a clipboard tool, an export converter, the
terminal it opens capture in -- would inherit it, where on Linux any process
of the same user can read it from /proc/<pid>/environ. Every spawn passes the
environment built here instead: the user's own, minus the secrets. It depends
on nothing else in the package so any module can import it.
"""
from __future__ import annotations

import os

# Every variable jotline.cli reads a passphrase from.
SECRET_VARIABLES = ("JOTLINE_PASSPHRASE", "JOTLINE_NEW_PASSPHRASE")


def child_environment() -> dict[str, str]:
    """A copy of os.environ for a child process, with the passphrases left out."""
    return {name: value for name, value in os.environ.items() if name not in SECRET_VARIABLES}
