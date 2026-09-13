"""Portable versioned local recipes, without code execution or implicit overwrites."""
from copy import deepcopy
import json
from pathlib import Path

from .actions import validate_actions
from .filesystem import fs as os
from .store import (MAX_SETTINGS_BYTES, create_private_temp, pin_ancestors, publish_new, read_regular_file,
                    unlink_quietly)


def encode_recipes(actions):
    validate_actions(actions)
    data = json.dumps({'format': 'jotline-actions', 'version': 1, 'actions': actions},
                      ensure_ascii=False, indent=2) + '\n'
    if len(data.encode('utf-8')) > MAX_SETTINGS_BYTES:
        raise ValueError('Recipes exceed the size limit')
    return data


def read_recipes(path):
    data = json.loads(read_regular_file(Path(path).expanduser(), MAX_SETTINGS_BYTES, ancestor_safe=True))
    if (not isinstance(data, dict) or set(data) != {'format', 'version', 'actions'}
            or data['format'] != 'jotline-actions' or type(data['version']) is not int or data['version'] != 1):
        raise ValueError('Expected a version 1 Jotline action recipe file')
    validate_actions(data['actions'])
    return data['actions']


def merge_recipes(existing, incoming):
    validate_actions(incoming)
    duplicate = set(existing) & set(incoming)
    if duplicate:
        raise ValueError('Action names already exist: ' + ', '.join(sorted(duplicate)))
    merged = {**deepcopy(existing), **deepcopy(incoming)}
    validate_actions(merged)
    return merged


def write_recipes(path, actions):
    """Create a private new file; reject existing paths and linked ancestors."""
    data = encode_recipes(actions).encode('utf-8')
    absolute = Path(path).expanduser().absolute()
    directory = pin_ancestors(absolute)
    try:
        fd, temporary = create_private_temp(directory, '.recipe-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            publish_new(directory, temporary, absolute.name)
            os.fsync(directory)
        finally:
            unlink_quietly(directory, temporary)
    finally:
        os.close(directory)
