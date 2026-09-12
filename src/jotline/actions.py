"""Explicit local action recipes. No shell evaluation or network access."""
from dataclasses import replace
import re

from .store import MAX_NOTE_BYTES, validate_workspace
from .templates import Templates


class ActionCommitError(OSError):
    """The source replacement committed, but a subsequent durability check failed."""

    def __init__(self, note, error):
        super().__init__(f'Action source was saved, but durability could not be confirmed: {error}')
        self.note = note


def validate_actions(actions):
    if not isinstance(actions, dict) or len(actions) > 128:
        raise ValueError('At most 128 actions are allowed')
    allowed = {'uppercase', 'lowercase', 'strip', 'quote', 'template', 'append', 'archive', 'copy', 'export', 'restore'}
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


def run_action(vault, note, steps, *, selection='', copy=None, export=None, on_step=None):
    """Apply steps in order; stop on failure, never archive before a failed append.

    Each write uses normal conflict detection and history. Earlier successful
    steps remain committed on failure; callers must report that partial outcome.
    Transforms affect the working text; export/append use that text, and final
    text changes are saved only after all steps succeed.
    """
    validate_actions({'action': steps})
    for index, step in enumerate(steps):
        if on_step:
            on_step(index, step['type'], 'checking')
        if step['type'] == 'copy' and copy is None:
            raise ValueError('Copy requires a terminal clipboard; use export in CLI actions')
        if step['type'] == 'export' and export is None:
            raise ValueError('Export destination is unavailable')
        if step['type'] == 'append' and step['value'] == note.id:
            raise ValueError('An action cannot append a note to itself')
    working = replace(note)
    for index, step in enumerate(steps):
        kind = step['type']
        if on_step:
            on_step(index, kind, 'running')
        if kind in {'uppercase', 'lowercase', 'strip'}:
            working.body = getattr(working.body, {'uppercase': 'upper', 'lowercase': 'lower', 'strip': 'strip'}[kind])()
        elif kind == 'quote':
            # Prefix physical Markdown lines, including blank lines. A final
            # newline stays a final newline instead of gaining an extra marker.
            working.body = re.sub(r'(?:\A|(?<=\n)|(?<=\r)(?!\n))(?!\Z)', '> ', working.body) if working.body else '> '
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
        elif kind == 'restore':
            working.body = note.body
        if len(working.body.encode('utf-8')) > MAX_NOTE_BYTES:
            raise ValueError('Action output exceeds the note size limit')
        if on_step:
            on_step(index, kind, 'completed')
    if (working.body, working.collection) != (note.body, note.collection):
        if on_step:
            on_step(len(steps), 'save', 'running')
        try:
            vault.save(working)
        except OSError as error:
            if working.original is not None and working.original != note.original:
                if on_step:
                    on_step(len(steps), 'save', 'committed-with-warning')
                raise ActionCommitError(working, error) from error
            raise
        if on_step:
            on_step(len(steps), 'save', 'completed')
    return working


BUILTIN_ACTIONS = {
    'copy-clean-text': [{'type': 'strip'}, {'type': 'copy'}, {'type': 'restore'}],
    'copy-markdown-quote': [{'type': 'quote'}, {'type': 'copy'}, {'type': 'restore'}],
    'create-from-template': [{'type': 'template', 'value': '{{template:meeting}}'}, {'type': 'export'}, {'type': 'restore'}],
    'append-and-archive': [{'type': 'append', 'value': 'choose-target'}, {'type': 'archive'}],
}


def preview_action(vault, note, steps, *, selection=''):
    """Evaluate text only; list intended effects without writing or using clipboard.

    Targets, permissions, conflicts and final saves are checked only on execution.
    """
    effects = []

    def output(label, body):
        excerpt = body[:20000] + ('\n[Preview truncated at 20,000 characters]' if len(body) > 20000 else '')
        effects.append(f'{label} ({len(body)} characters):\n{excerpt}')

    class PreviewVault:
        path = vault.path

        def append_note(self, target, body, workspace):
            output(f'Append to note {target} in {workspace}', body)

        def save(self, working):
            effects.append(f'Save source note ({working.collection}, {len(working.body)} characters)')

    result = run_action(PreviewVault(), note, steps, selection=selection,
                        copy=lambda body: output('Copy to clipboard', body),
                        export=lambda body: output('Export', body))
    return result, effects
