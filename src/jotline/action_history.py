"""Bounded private action outcomes. Note bodies and recipe values are never logged."""
from datetime import datetime, timezone
import json
from pathlib import Path

from .actions import MAX_STEPS, ActionCommitError, run_action
from .filesystem import create_private_temp, fs as os, read_regular_at, replace_at, unlink_quietly, vault_lock
from .history import stamp

MAX_RUNS = 100
MAX_HISTORY_BYTES = 256 * 1024
HISTORY_FILE = '.jotline-action-history.json'


class ActionHistory:
    def __init__(self, vault_path):
        self.path = Path(vault_path)

    def _read(self, directory):
        try:
            data = json.loads(read_regular_at(directory, HISTORY_FILE, MAX_HISTORY_BYTES))
        except FileNotFoundError:
            return []
        # A run records each recipe step plus the final save step.
        if not isinstance(data, list) or len(data) > MAX_RUNS or any(
                not isinstance(item, dict) or not isinstance(item.get('steps'), list)
                or len(item['steps']) > MAX_STEPS + 1 for item in data):
            raise ValueError('Invalid action history')
        return data

    def read(self):
        with vault_lock(self.path) as directory:
            return self._read(directory)

    def append(self, record):
        """Append one run. Returns a warning when a corrupt log was set aside."""
        warning = None
        with vault_lock(self.path) as directory:
            try:
                records = self._read(directory)
            except (ValueError, RecursionError) as error:
                # A corrupt log must not disable logging forever; keep the bytes
                # for inspection and start a fresh bounded history.
                quarantine = f'.jotline-action-history.invalid-{stamp()}.json'
                replace_at(directory, HISTORY_FILE, quarantine)
                records = []
                warning = f'Action history was unreadable ({error}); it was set aside as {quarantine}'
            records = (records + [record])[-MAX_RUNS:]
            output = json.dumps(records, ensure_ascii=False).encode('utf-8')
            while len(output) > MAX_HISTORY_BYTES and len(records) > 1:
                records.pop(0)
                output = json.dumps(records, ensure_ascii=False).encode('utf-8')
            if len(output) > MAX_HISTORY_BYTES:
                raise ValueError('Action history entry exceeds the size limit')
            fd, temporary = create_private_temp(directory, '.action-history-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(output)
                    stream.flush()
                    os.fsync(stream.fileno())
                replace_at(directory, temporary, HISTORY_FILE)
                os.fsync(directory)
            finally:
                unlink_quietly(directory, temporary)
        return warning


def run_recorded_action(vault, note, steps, *, name='action', history_warning=None, **kwargs):
    """Run and log partial outcomes; logging failures never hide action outcomes."""
    record = {'time': datetime.now(timezone.utc).isoformat(), 'name': str(name)[:48],
              'note_id': note.id, 'workspace': note.workspace, 'status': 'failed', 'steps': []}
    current = None

    def observe(index, kind, status):
        nonlocal current
        current = index
        while len(record['steps']) <= index:
            record['steps'].append({'type': steps[len(record['steps'])]['type'], 'status': 'not-run'}
                                   if len(record['steps']) < len(steps) else {'type': 'save', 'status': 'not-run'})
        if status != 'checking':
            record['steps'][index]['status'] = status

    try:
        result = run_action(vault, note, steps, on_step=observe, **kwargs)
        record['status'] = 'completed'
        return result
    except (ValueError, OSError) as error:
        record['error'] = type(error).__name__
        if isinstance(error, ActionCommitError):
            record['status'] = 'committed-with-warning'
        elif current is not None:
            record['steps'][current]['status'] = 'failed'
        raise
    finally:
        try:
            quarantined = ActionHistory(vault.path).append(record)
            if quarantined and history_warning:
                history_warning(quarantined)
        except (ValueError, OSError, RecursionError) as error:
            if history_warning:
                history_warning(f'Action history could not be saved: {error}')


def format_history(records):
    if not records:
        return 'No recorded action runs yet.'
    lines = ['Most recent first. Completed text transforms are staged until the final save.',
             'A failed run can leave earlier append, copy or export effects applied. No note text is logged.', '']
    for record in reversed(records):
        lines.append(f"{record.get('time', '?')}  {record.get('name', '?')} — {record.get('status', '?')}")
        lines.append(f"Note {record.get('note_id', '?')} · workspace {record.get('workspace', '?')}")
        for index, step in enumerate(record['steps'], 1):
            if isinstance(step, dict):
                lines.append(f"  {index}. {step.get('type', '?')}: {step.get('status', '?')}")
        if record.get('error'):
            lines.append(f"  Error: {record['error']}")
        lines.append('')
    return '\n'.join(lines)
