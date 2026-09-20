"""Revision-checked view preferences. Never stores note text or block labels."""
import json

from .filesystem import read_regular_file
from .limits import MAX_SETTINGS_BYTES
from .outline_session import revision
from .settings import Settings


def read_state(path, note_id, text):
    try:
        data = json.loads(read_regular_file(path, MAX_SETTINGS_BYTES)).get(note_id, {})
        return data if isinstance(data, dict) and data.get('revision') == revision(text) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def write_state(path, note_id, data):
    from .filesystem import read_regular_at, vault_lock
    with vault_lock(path.parent) as directory:
        try:
            states = json.loads(read_regular_at(directory, path.name, MAX_SETTINGS_BYTES))
            if not isinstance(states, dict):
                states = {}
        except (FileNotFoundError, ValueError, TypeError):
            states = {}
        states.pop(note_id, None)
        states[note_id] = data
        while len(states) > 100 or len(json.dumps(states).encode()) > MAX_SETTINGS_BYTES:
            del states[next(iter(states))]
        Settings()._save_locked(path, states, directory)
