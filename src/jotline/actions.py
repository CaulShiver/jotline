"""Explicit local action recipes. No shell evaluation or network access."""
from dataclasses import replace

from .store import MAX_NOTE_BYTES, validate_workspace
from .templates import Templates


def validate_actions(actions):
    if not isinstance(actions, dict) or len(actions) > 128:
        raise ValueError('At most 128 actions are allowed')
    allowed = {'uppercase', 'lowercase', 'strip', 'template', 'append', 'archive', 'copy', 'export'}
    for name, steps in actions.items():
        validate_workspace(name)
        if not isinstance(steps, list) or not 1 <= len(steps) <= 16:
            raise ValueError('An action needs 1–16 steps')
        for step in steps:
            if not isinstance(step, dict) or not isinstance(step.get('type'), str) or step['type'] not in allowed:
                raise ValueError('Unknown action step')
            kind = step['type']
            expected = {'type', 'value'} if kind in {'template', 'append'} else {'type'}
            if set(step) != expected or ('value' in step and not isinstance(step['value'], str)):
                raise ValueError('Invalid action step fields')
            if kind == 'append' and (not step['value'] or len(step['value']) > 128):
                raise ValueError('Append needs a target note ID')


def run_action(vault, note, steps, *, selection='', copy=None, export=None):
    """Apply steps in order; stop on failure, never archive before a failed append.

    Each write uses normal conflict detection and history. Earlier successful
    steps remain committed on failure; callers must report that partial outcome.
    Transforms affect the working text; export/append use that text, and final
    text changes are saved only after all steps succeed.
    """
    validate_actions({'action': steps})
    for step in steps:
        if step['type'] == 'copy' and copy is None:
            raise ValueError('Copy requires a terminal clipboard; use export in CLI actions')
        if step['type'] == 'export' and export is None:
            raise ValueError('Export destination is unavailable')
        if step['type'] == 'append' and step['value'] == note.id:
            raise ValueError('An action cannot append a note to itself')
    working = replace(note)
    for step in steps:
        kind = step['type']
        if kind in {'uppercase', 'lowercase', 'strip'}:
            working.body = getattr(working.body, {'uppercase': 'upper', 'lowercase': 'lower', 'strip': 'strip'}[kind])()
        elif kind == 'template':
            working.body = Templates(vault.path).render_text(
                step['value'], note.workspace, title=working.title,
                body=working.body, selection=selection)
        elif kind == 'append':
            vault.append_note(step['value'], working.body, note.workspace)
        elif kind == 'archive':
            working.collection = 'archive'
        elif kind == 'copy':
            copy(working.body)
        elif kind == 'export':
            export(working.body)
        if len(working.body.encode('utf-8')) > MAX_NOTE_BYTES:
            raise ValueError('Action output exceeds the note size limit')
    if (working.body, working.collection) != (note.body, note.collection):
        vault.save(working)
    return working
