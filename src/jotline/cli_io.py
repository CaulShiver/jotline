"""Safe terminal output and bounded command input."""
from __future__ import annotations

import argparse
import codecs
import os
from pathlib import Path
import sys
import unicodedata

from .limits import MAX_NOTE_BYTES
from .store import Vault, decode_problem


def default_vault() -> Path:
    override = os.environ.get("JOTLINE_VAULT")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "jotline/notes"
    xdg_home = os.environ.get("XDG_DATA_HOME") or ""
    if not Path(xdg_home).is_absolute():
        xdg_home = ""
    xdg = Path(xdg_home or Path.home() / ".local/share") / "jotline/notes"
    if sys.platform == "darwin" and not xdg_home and not xdg.exists():
        return Path.home() / "Library/Application Support/jotline/notes"
    return xdg


DISRUPTIVE_FORMAT = frozenset("\u2028\u2029\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def is_terminal_control(character: str) -> bool:
    """Whether a character can alter a terminal; tab and line breaks are ordinary note text."""
    return (unicodedata.category(character) in ("Cc", "Cs", "Cn") and character not in "\t\n\r") \
        or character in DISRUPTIVE_FORMAT


def terminal_text(value: object) -> str:
    """Render a one-line diagnostic without letting note or filename controls affect a terminal.

    Tabs and line breaks are escaped as well, so a name cannot forge a second line of output.
    """
    return "".join(character.encode("unicode_escape").decode("ascii")
                   if is_terminal_control(character) or character in "\n\r\t" else character
                   for character in str(value))


def warning(value: object) -> None:
    print(f"warning: {terminal_text(value)}", file=sys.stderr)


def report_warnings(vault: Vault) -> None:
    for item in vault.warnings:
        warning(item)


def read_capture_input(encoding: str = "utf-8", errors: str = "strict") -> str:
    """Read a bounded piped capture, retaining line endings when stdin exposes bytes."""
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(MAX_NOTE_BYTES + 1)
    if isinstance(raw, bytes):
        if len(raw) > MAX_NOTE_BYTES:
            raise ValueError(f"Capture exceeds the {MAX_NOTE_BYTES}-byte file limit")
        return raw.decode(encoding, errors)
    if len(raw.encode("utf-8")) > MAX_NOTE_BYTES:
        raise ValueError(f"Capture exceeds the {MAX_NOTE_BYTES}-byte file limit")
    return raw


def has_terminal_controls(body: str) -> bool:
    return any(is_terminal_control(character) for character in body)


def encoding_name(value: str) -> str:
    try:
        codecs.lookup(value)
        b"a".decode(value, "replace")
    except LookupError:
        raise argparse.ArgumentTypeError(f"unknown text encoding: {value}") from None
    return value


def command_text(words: list[str], encoding: str, errors: str) -> str:
    text = " ".join(words)
    if sys.platform == "win32":
        return text
    return os.fsencode(text).decode(encoding, errors)


def decode_input(source: str, encoding: str, read):
    try:
        return read()
    except UnicodeDecodeError as error:
        raise ValueError(f"{source} is {decode_problem(error, encoding)}; pass --encoding NAME if it uses "
                         "another encoding, or --replace-invalid to substitute bad bytes") from None


def input_text(args: argparse.Namespace, encoding: str, errors: str, *, interactive: bool) -> str:
    """Text from the command line, or from piped stdin when none was given."""
    if args.text:
        return decode_input("Command-line text", encoding, lambda: command_text(args.text, encoding, errors))
    if interactive:
        return ""
    return decode_input("Piped input", encoding, lambda: read_capture_input(encoding, errors))


def utf8_error_message(error: UnicodeDecodeError) -> str:
    return f"The note file is {decode_problem(error)}; convert it to UTF-8 and retry"
