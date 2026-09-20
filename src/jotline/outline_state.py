"""Revision-checked view preferences, retained only for unencrypted notes."""
import json

from .filesystem import read_regular_at, read_regular_file, vault_lock
from .limits import MAX_SETTINGS_BYTES
from .outline_session import revision

STATE_FILE = '.jotline-outline.json'


def read_state(path, note_id, text):
    try:
        data = json.loads(read_regular_file(path, MAX_SETTINGS_BYTES)).get(note_id, {})
        return data if isinstance(data, dict) and data.get('revision') == revision(text) else {}
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return {}


def _states(directory, name):
    try:
        states = json.loads(read_regular_at(directory, name, MAX_SETTINGS_BYTES))
        return states if isinstance(states, dict) else None
    except FileNotFoundError:
        return {}
    except (ValueError, TypeError, RecursionError):
        return None


def remove_state_locked(path, note_id, directory):
    """Remove a plaintext fingerprint before encryption, under the caller's lock."""
    from .settings import Settings
    states = _states(directory, path.name)
    if states is None:
        # Even corrupt derived preferences can retain a plaintext fingerprint.
        # Clear regular invalid state; unsafe filesystem objects still raise.
        Settings()._save_locked(path, {}, directory)
        return
    if note_id in states:
        del states[note_id]
        Settings()._save_locked(path, states, directory)


def write_state(path, note_id, data):
    from .settings import Settings
    from .store import Vault, validate_note_id
    validate_note_id(note_id)
    with vault_lock(path.parent) as directory:
        # A second window may still hold plaintext after another process encrypts
        # the note. Check the persisted flag inside the same lock as publication.
        try:
            note = Vault.parse_note(note_id, read_regular_at(directory, note_id + '.md'))
        except FileNotFoundError:
            note = None
        if data is None or note is not None and note.encrypted:
            remove_state_locked(path, note_id, directory)
            return
        states = _states(directory, path.name) or {}
        states.pop(note_id, None)
        states[note_id] = data
        while states and (len(states) > 100 or len(
                (json.dumps(states, indent=2, ensure_ascii=False) + '\n').encode('utf-8')) > MAX_SETTINGS_BYTES):
            del states[next(iter(states))]
        Settings()._save_locked(path, states, directory)
