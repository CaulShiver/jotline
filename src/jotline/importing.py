"""Preview bounded, non-destructive Markdown and Drafts library imports."""
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import stat
from uuid import UUID

from .filesystem import fs, pin_ancestors, read_regular_file
from .limits import MAX_NOTE_BYTES
from .store import COLLECTIONS, Note, Vault, decode_problem, tagged_body, validate_note_id, validate_workspace

MAX_IMPORT_BYTES = 32 * 1024 * 1024
MAX_IMPORT_ENTRIES = 1000
IMPORT_SUFFIXES = ('.md', '.txt', '.draftsexport')


@dataclass
class ImportItem:
    source: str
    note: Note
    duplicate: bool = False


@dataclass
class ImportPlan:
    items: list[ImportItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicates: str = 'skip'
    # The warnings that leave nothing for the user to fix: a link the importer
    # never follows, or a note already in the vault that could not be read.
    notices: list[str] = field(default_factory=list)

    def notice(self, message):
        self.warnings.append(message)
        self.notices.append(message)

    @property
    def needs_review(self):
        """Whether a warning means a source was not, or not fully, imported."""
        return len(self.warnings) > len(self.notices)

    @property
    def ready(self):
        return sum(not item.duplicate or self.duplicates == 'copy' for item in self.items)

    def summary(self):
        return f'{self.ready} to import · {len(self.items) - self.ready} duplicates skipped · {len(self.warnings)} warnings'


@dataclass
class ImportResult:
    imported: list[str] = field(default_factory=list)
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self):
        return f'Imported {len(self.imported)} · skipped {self.skipped} · failed {len(self.errors)}'


def _fingerprint(note):
    return hashlib.sha256(note.body.encode('utf-8')).digest(), note.workspace


def _timestamp(value):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('Timestamps must be ISO date strings')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid ISO timestamp') from None
    # Date filters compare the leading calendar date. Normalize alternate ISO
    # forms while retaining ordinary Drafts timestamps (including their Z suffix).
    return value if value[:10] == parsed.date().isoformat() else parsed.isoformat()


def _draft(vault, entry, workspace):
    if not isinstance(entry, dict) or not isinstance(entry.get('content'), str):
        raise ValueError('Draft must contain a text content field')
    note = vault.new(entry['content'], workspace=workspace)
    if 'uuid' in entry:
        if not isinstance(entry['uuid'], str):
            raise ValueError('Draft uuid must be a string')
        note.id = 'drafts-' + UUID(entry['uuid']).hex
    folder = entry.get('folder', 0)
    # Drafts uses 0=inbox, 1=archive, 2=trash in JSON exports.
    if type(folder) is int and folder in (0, 1, 2):
        note.collection = ('inbox', 'archive', 'trash')[folder]
    elif isinstance(folder, str) and folder in ('inbox', 'archive', 'trash'):
        note.collection = folder
    else:
        raise ValueError('Unsupported Drafts folder')
    flagged = entry.get('flagged', False)
    if not isinstance(flagged, bool):
        raise ValueError('Flagged must be true or false')
    note.starred = flagged
    note.created = _timestamp(entry.get('created_at')) or note.created
    note.updated = _timestamp(entry.get('modified_at')) or note.updated
    tags = entry.get('tags', [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError('Tags must be a list of strings')
    # Preserve tags outside the inline-tag grammar visibly, never silently drop them.
    simple, other = [], []
    for tag in tags:
        try:
            if len(tag.split()) != 1:
                raise ValueError('Tag contains spaces')
            tagged_body('', tag)
            simple.append(tag)
        except ValueError:
            other.append(tag)
    if simple:
        note.body = tagged_body(note.body, ' '.join(simple))
    if other:
        note.body += '\n\nDrafts tags: ' + json.dumps(other, ensure_ascii=False)
    return note


@contextmanager
def _open_directory(path):
    """Pin every ancestor before enumerating; reject symlinks and reparse points."""
    parent = pin_ancestors(path)
    try:
        directory = (fs.open(path.name, fs.O_RDONLY | fs.O_DIRECTORY | fs.O_NOFOLLOW, dir_fd=parent)
                     if path.name else fs.dup(parent))
    finally:
        fs.close(parent)
    try:
        yield directory
    finally:
        fs.close(directory)


def _jotline_note(vault, raw, workspace, default_collection):
    """Carry a Jotline-format file's own metadata instead of treating it as body."""
    parsed = Vault.parse_note(vault.new().id, raw)
    if parsed.encrypted:
        # The text is bound to its own vault's key and note ID; importing it would copy unreadable text.
        raise ValueError('Encrypted Jotline note skipped; it only opens in the vault that encrypted it')
    note = vault.new(parsed.body, workspace=workspace)
    note.collection = parsed.collection if parsed.collection != 'trash' else default_collection
    note.starred = parsed.starred
    note.created = parsed.created or note.created
    note.updated = parsed.updated or note.updated
    return note


def _note_file(source):
    """Whether a vault would read this file as one of its notes: an ID-shaped .md name.

    Only such a file's header is metadata. Any other file is outside text, so a
    header at its start stays in the body where the review shows it; a file
    cannot pick its own collection, star or dates just by starting with one.
    """
    if source.suffix.lower() != '.md':
        return False
    try:
        validate_note_id(source.stem)
    except ValueError:
        return False
    return True


def _scan_folder(root: Path, recursive: bool, plan: ImportPlan) -> list[Path]:
    """Importable files under a folder, bounded by MAX_IMPORT_ENTRIES and never following links."""
    paths = []
    pending = [root]
    scanned = 0
    while pending and scanned < MAX_IMPORT_ENTRIES:
        folder = pending.pop()
        try:
            with _open_directory(folder) as directory, fs.scandir(directory) as children:
                for entry in children:
                    scanned += 1
                    if scanned > MAX_IMPORT_ENTRIES:
                        plan.warnings.append(f'Scan stopped at {MAX_IMPORT_ENTRIES} entries')
                        break
                    child = folder / entry.name
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError as error:
                        plan.warnings.append(f'{child.name}: {error}')
                        continue
                    if stat.S_ISLNK(info.st_mode):
                        plan.notice(f'Skipped link: {child.name}')
                    elif stat.S_ISDIR(info.st_mode) and recursive:
                        pending.append(child)
                    elif stat.S_ISREG(info.st_mode) and child.suffix.lower() in IMPORT_SUFFIXES:
                        paths.append(child)
        except OSError as error:
            plan.warnings.append(f'{folder.name}: {error}')
    if pending:
        plan.warnings.append('Some subfolders were not scanned because the entry limit was reached')
    return sorted(paths)


def preview_import(vault: Vault, path: Path, workspace='default', default_collection='inbox',
                   duplicates='skip', recursive=False, encoding='utf-8', errors='strict') -> ImportPlan:
    validate_workspace(workspace)
    if duplicates not in ('skip', 'copy') or default_collection not in COLLECTIONS:
        raise ValueError('Invalid import options')
    plan = ImportPlan(duplicates=duplicates)
    existing = vault.notes()
    for message in vault.warnings:
        plan.notice(message)
    fingerprints = {_fingerprint(note) for note in existing}
    ids = {note.id for note in existing}
    total_bytes = 0
    total_records = 0
    path = path.expanduser().absolute()
    paths = _scan_folder(path, recursive, plan) if stat.S_ISDIR(path.lstat().st_mode) else [path]
    for source in paths:
        if total_bytes >= MAX_IMPORT_BYTES or total_records >= MAX_IMPORT_ENTRIES:
            plan.warnings.append('Import limit reached; split the source into smaller batches')
            break
        try:
            raw = read_regular_file(source, min(MAX_IMPORT_BYTES - total_bytes, MAX_IMPORT_BYTES
                                    if source.suffix.lower() == '.draftsexport' else MAX_NOTE_BYTES), ancestor_safe=True,
                                    encoding=encoding, errors=errors)
            total_bytes += len(raw.encode('utf-8'))
            is_drafts = source.suffix.lower() == '.draftsexport'
            if is_drafts:
                try:
                    entries = json.loads(raw)
                except (json.JSONDecodeError, RecursionError) as error:
                    raise ValueError('Invalid Drafts JSON export') from error
                if not isinstance(entries, list):
                    raise ValueError('Drafts export must contain a JSON list of drafts')
            else:
                entries = [raw]
            for index, entry in enumerate(entries):
                total_records += 1
                if total_records > MAX_IMPORT_ENTRIES:
                    plan.warnings.append('Draft limit reached; split the source into smaller batches')
                    break
                label = f'{source.name} #{index + 1}' if is_drafts else source.name
                try:
                    if is_drafts:
                        note = _draft(vault, entry, workspace)
                    elif _note_file(source) and re.match(r'\A\ufeff?---\r?\njotline: 1\r?\n', entry):
                        note = _jotline_note(vault, entry, workspace, default_collection)
                        # The header is gone from the body, so say where the collection came from.
                        label += ' (Jotline note)'
                    else:
                        note = vault.new(entry.removeprefix('\ufeff'), workspace=workspace)
                        note.collection = default_collection
                    if len(note.body.encode('utf-8')) > MAX_NOTE_BYTES - 1024:
                        raise ValueError('Note too large after metadata mapping')
                    fingerprint = _fingerprint(note)
                    duplicate = note.id in ids or fingerprint in fingerprints
                    plan.items.append(ImportItem(label, note, duplicate))
                    fingerprints.add(fingerprint)
                    ids.add(note.id)
                except (TypeError, AttributeError, ValueError) as error:
                    plan.warnings.append(f'{label}: {error}')
        except UnicodeDecodeError as error:
            plan.warnings.append(f'{source.name}: {decode_problem(error, encoding)}')
        except (OSError, ValueError) as error:
            plan.warnings.append(f'{source.name}: {error}')
    return plan


def apply_import(vault: Vault, plan: ImportPlan) -> ImportResult:
    """Apply the exact in-memory preview; new files only, never replace a note."""
    result = ImportResult()
    existing = vault.notes()
    fingerprints = {_fingerprint(note) for note in existing}
    ids = {note.id for note in existing}
    for item in plan.items:
        note = replace(item.note, original=None)
        fingerprint = _fingerprint(note)
        duplicate = item.duplicate or note.id in ids or fingerprint in fingerprints
        if duplicate and plan.duplicates == 'skip':
            result.skipped += 1
            continue
        if duplicate:
            note.id = vault.new().id
        try:
            vault.save(note, preserve_updated=True)
            result.imported.append(note.id)
            fingerprints.add(fingerprint)
            ids.add(note.id)
        except (OSError, ValueError) as error:
            result.errors.append(f'{item.source}: {error}')
    return result
