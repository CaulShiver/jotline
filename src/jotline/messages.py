"""Wording shared by in-app messages: key names, sizes, and what failed."""
from .limits import MAX_NOTE_BYTES

KEY_NAMES = {'ctrl': 'Ctrl', 'alt': 'Alt', 'shift': 'Shift', 'comma': ',', 'escape': 'Esc', 'enter': 'Enter',
             'tab': 'Tab', 'space': 'Space', 'backspace': 'Backspace', 'delete': 'Delete', 'up': 'Up',
             'down': 'Down', 'left': 'Left', 'right': 'Right', 'home': 'Home', 'end': 'End',
             'pageup': 'PgUp', 'pagedown': 'PgDn', 'insert': 'Insert'}


def key_name(key: str) -> str:
    """A key as every screen shows it: Ctrl+N, Alt+K, F1, Ctrl+Shift+Up."""
    return '+'.join(KEY_NAMES.get(part, part.upper()) for part in key.split('+')) if key else ''


def megabytes(size: int) -> str:
    amount = size / (1024 * 1024)
    return f"{amount:.1f} MB".replace(".0 MB", " MB") if amount >= 0.1 else "under 0.1 MB"


NOTE_LIMIT = megabytes(MAX_NOTE_BYTES)
TOO_LARGE = f"Nothing was changed: the note would be over the {NOTE_LIMIT} size limit. Shorten it, or use less text."


def reason(error: BaseException) -> str:
    """The informative part of an error: an OS error's reason and file, otherwise its message."""
    if isinstance(error, OSError) and error.strerror:
        return error.strerror + (f": {error.filename}" if error.filename else "")
    return str(error).strip().rstrip(".") or type(error).__name__


def failed(what: str, error: BaseException, then: str = "") -> str:
    """``what`` could not happen, why, and what to do next."""
    return f"{what}: {reason(error)}." + (f" {then}" if then else "")


def plural(count: int, word: str, words: str = "") -> str:
    return f"{count} {word if count == 1 else words or word + 's'}"
