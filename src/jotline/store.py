"""Portable Markdown storage with atomic writes and optimistic concurrency."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, date
import io
import json
from pathlib import Path
import re
import stat
import sys
import time
from time import monotonic
from uuid import uuid4

from .filesystem import fs as os, lock_file

COLLECTIONS = ("inbox", "projects", "areas", "resources", "archive", "trash")
# Limits protect the interactive app from accidentally imported huge files.
MAX_NOTE_BYTES = 10 * 1024 * 1024
MAX_SETTINGS_BYTES = 256 * 1024
LOCK_TIMEOUT_SECONDS = 1.0
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_CACHED_NOTES = 2048
CACHE_TTL_SECONDS = 1.0
MAX_SCAN_ENTRIES = 10_000
MAX_SCAN_BYTES = 128 * 1024 * 1024
MAX_DERIVED_ITEMS = 50_000

FileSignature = tuple[int, int, int, int, int]

LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]*)?\]\]")
TAG = re.compile(r"(?<![\w#])#([\w][\w/-]*)", re.UNICODE)


def _derived_values(pattern: re.Pattern, body: str, label: str) -> tuple[set[str], str]:
    values = set()
    for index, match in enumerate(pattern.finditer(body)):
        if index >= MAX_DERIVED_ITEMS:
            return values, f"Note has more than {MAX_DERIVED_ITEMS} {label}; results were truncated"
        values.add(match.group(1))
    return values, ""


def validate_workspace(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", name):
        raise ValueError("Workspace names need 1–48 lowercase letters, numbers, hyphens or underscores")
    return name


def tagged_body(body: str, tags: str) -> str:
    names = {tag.removeprefix("#").casefold() for tag in tags.split()}
    if not names or any(not re.fullmatch(r"[\w][\w/-]*", tag) for tag in names):
        raise ValueError("Enter tags separated by spaces; use letters, numbers, underscores, / or -")
    existing, warning = _derived_values(TAG, body, "tags")
    if warning:
        raise ValueError(warning)
    missing = names - {tag.casefold() for tag in existing}
    return body + ("\n\n" + " ".join("#" + tag for tag in sorted(missing)) if missing else "")


class ConflictError(OSError):
    """An external edit must be resolved before overwriting a note."""


def _read_regular_fd(fd: int, name: str, max_bytes: int) -> str:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"Not a regular file: {name}")
    if info.st_size > max_bytes:
        raise ValueError(f"{name} exceeds the {max_bytes}-byte file limit")
    raw = bytearray()
    while len(raw) <= max_bytes:
        chunk = os.read(fd, min(64 * 1024, max_bytes + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    if len(raw) > max_bytes:
        raise ValueError(f"{name} exceeds the {max_bytes}-byte file limit")
    return bytes(raw).decode("utf-8")


def read_regular_at(directory: int, name: str, max_bytes: int = MAX_NOTE_BYTES) -> str:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        return _read_regular_fd(fd, name, max_bytes)
    finally:
        os.close(fd)


def create_private_temp(directory: int, prefix: str) -> tuple[int, str]:
    """Create a private file inside an already-pinned directory."""
    for _ in range(100):
        name = prefix + uuid4().hex
        try:
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            return fd, name
        except FileExistsError:
            continue
    raise FileExistsError("Could not allocate private storage")


def replace_at(directory: int, source: str, target: str) -> None:
    """Replace within a pinned directory, failing closed if dir_fd is unsupported."""
    os.replace(source, target, src_dir_fd=directory, dst_dir_fd=directory)


def read_regular_file(path: Path, max_bytes: int = MAX_NOTE_BYTES, *, ancestor_safe: bool = False) -> str:
    """Read bounded UTF-8 text without following links or blocking on a pipe."""
    if ancestor_safe:
        absolute = Path(path).absolute()
        directory = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in absolute.parts[1:-1]:
                next_directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                         dir_fd=directory)
                os.close(directory)
                directory = next_directory
            fd = os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
    else:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        return _read_regular_fd(fd, path.name, max_bytes)
    finally:
        os.close(fd)


@contextmanager
def vault_lock(path: Path):
    """Coordinate local writers without hanging the UI indefinitely."""
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # APFS can report ENOENT for concurrent O_CREAT | O_NOFOLLOW opens.
        # Separate existing-file opens from exclusive creation and retry only
        # when another writer wins creation. Links still fail without following.
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
        for _ in range(100):
            try:
                fd = os.open(".jotline.lock", flags, dir_fd=directory)
                break
            except FileNotFoundError:
                try:
                    fd = os.open(".jotline.lock", flags | os.O_CREAT | os.O_EXCL,
                                 0o600, dir_fd=directory)
                    break
                except FileExistsError:
                    continue
        else:
            raise OSError("Vault lock changed repeatedly; try saving again")
    except BaseException:
        os.close(directory)
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("Jotline lock is not a regular file")
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                lock_file(fd)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OSError("Vault is busy in another process; try saving again") from None
                time.sleep(0.025)
        try:
            yield directory
        finally:
            lock_file(fd, unlock=True)
    finally:
        os.close(fd)
        os.close(directory)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def file_signature(path: Path) -> FileSignature:
    if os.name == "nt":
        return os.file_signature(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"Not a regular file: {path.name}")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@dataclass
class Note:
    id: str
    body: str = ""
    collection: str = "inbox"
    created: str = ""
    updated: str = ""
    starred: bool = False
    original: str | None = None
    workspace: str = "default"
    derived_warnings: list[str] = field(default_factory=list, repr=False, compare=False)

    def _derived(self, pattern: re.Pattern, label: str) -> set[str]:
        values, warning = _derived_values(pattern, self.body, label)
        if warning and warning not in self.derived_warnings:
            self.derived_warnings.append(warning)
        return values

    @property
    def title(self) -> str:
        for line in io.StringIO(self.body):
            if line.strip():
                return line.lstrip("# ").strip()[:100] or "Untitled"
        return "Untitled"

    @property
    def tags(self) -> set[str]:
        return {tag.casefold() for tag in self._derived(TAG, "tags")}

    @property
    def links(self) -> set[str]:
        return self._derived(LINK, "links")


class Vault:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        self.warnings: list[str] = []
        self.backup_warning = ""
        self._cache: dict[str, tuple[FileSignature, Note, int, float]] = {}
        self.permission_warning = ("Vault is writable by other users; use chmod go-w to protect note replacement"
                                   if os.name != "nt" and self.path.stat().st_mode & 0o022 else "")
        if self.permission_warning:
            self.warnings.append(self.permission_warning)

    def locked(self):
        return vault_lock(self.path)

    def file(self, note_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", note_id):
            raise ValueError("Invalid note ID")
        return self.path / f"{note_id}.md"

    def new(self, body: str = "", workspace: str = "default") -> Note:
        stamp = now()
        return Note(uuid4().hex, body, created=stamp, updated=stamp, workspace=validate_workspace(workspace))

    def read(self, note_id: str, *, directory: int | None = None) -> Note:
        filename = self.file(note_id).name
        own_directory = directory is None
        if own_directory:
            directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                raw = _read_regular_fd(fd, filename, MAX_NOTE_BYTES)
            finally:
                os.close(fd)
        finally:
            if own_directory:
                os.close(directory)
        return self.parse_note(note_id, raw)

    @staticmethod
    def parse_note(note_id: str, raw: str) -> Note:
        meta = {}
        body = raw
        if re.match(r"\A---\r?\njotline: 1\r?\n", raw):
            boundary = re.search(r"\r?\n---\r?\n", raw)
            if boundary is None:
                raise ValueError("Incomplete Jotline metadata header")
            header = raw[raw.index("\n") + 1:boundary.start()]
            for line in header.splitlines():
                key, sep, value = line.partition(": ")
                if sep and key in {"collection", "created", "updated", "starred", "workspace"}:
                    try:
                        meta[key] = json.loads(value)
                    except RecursionError:
                        raise ValueError("Metadata is nested too deeply") from None
            body = raw[boundary.end():]
        if meta.get("collection", "inbox") not in COLLECTIONS:
            raise ValueError("Unknown collection")
        if any(not isinstance(meta.get(k, ""), str) for k in ("created", "updated")):
            raise ValueError("Invalid timestamps")
        if not isinstance(meta.get("starred", False), bool):
            raise ValueError("Invalid starred value")
        validate_workspace(meta.get("workspace", "default"))
        return Note(note_id, body, original=raw, **meta)

    def invalidate_cache(self) -> None:
        """Force the next scan to reread note bodies from disk."""
        self._cache.clear()

    def notes(self) -> list[Note]:
        notes = []
        self.warnings = [self.permission_warning] if self.permission_warning else []
        refreshed = {}
        retained_bytes = 0
        scanned_bytes = 0
        for index, file in enumerate(self.path.glob("*.md")):
            if index >= MAX_SCAN_ENTRIES:
                self.warnings.append(f"Vault scan stopped after {MAX_SCAN_ENTRIES} entries; results are incomplete")
                break
            try:
                signature = file_signature(file)
                scanned_bytes += signature[2]
                if scanned_bytes > MAX_SCAN_BYTES:
                    self.warnings.append(f"Vault scan stopped after {MAX_SCAN_BYTES} bytes; results are incomplete")
                    break
                cached = self._cache.get(file.stem)
                cache_hit = cached is not None and cached[0] == signature and monotonic() < cached[3]
                if cache_hit:
                    note, cost, expires = cached[1:]
                else:
                    # File timestamps are not unique content revisions. A rapid
                    # same-size edit can retain the full signature, especially
                    # when a sync tool restores mtime. Bound stale cache reuse
                    # from the real read; cache hits must not extend this deadline.
                    expires = monotonic() + CACHE_TTL_SECONDS
                    note = self.read(file.stem)
                    # Include both body and original snapshot plus a conservative
                    # allowance for the small cache entry and note attributes.
                    cost = sum(sys.getsizeof(value) for value in vars(note).values()) + 1024
                notes.append(replace(note))
                # A file changed during reading is still a valid snapshot, but
                # must be read afresh next time. Never cache it under a stale stat.
                if (len(refreshed) < MAX_CACHED_NOTES and retained_bytes + cost <= MAX_CACHE_BYTES
                        and (cache_hit or file_signature(file) == signature)):
                    refreshed[file.stem] = (signature, note, cost, expires)
                    retained_bytes += cost
            except (ValueError, OSError) as error:
                self.warnings.append(f"{file.name}: {error}")
        self._cache = refreshed
        return sorted(notes, key=lambda n: (n.starred, n.updated, n.id), reverse=True)

    def save(self, note: Note, *, preserve_updated: bool = False) -> None:
        with self.locked() as directory:
            self._save_locked(note, directory, preserve_updated=preserve_updated)

    def _save_locked(self, note: Note, directory: int, *, preserve_updated: bool = False) -> None:
        validate_workspace(note.workspace)
        if note.collection not in COLLECTIONS:
            raise ValueError("Unknown collection")
        if not isinstance(note.body, str) or not isinstance(note.starred, bool):
            raise ValueError("Invalid note body or starred value")
        if not all(isinstance(value, str) for value in (note.created, note.updated)):
            raise ValueError("Invalid timestamps")
        path = self.file(note.id)
        try:
            actual = read_regular_at(directory, path.name)
        except FileNotFoundError:
            actual = None
        if actual != note.original:
            raise ConflictError("This note changed outside Jotline. Save a recovery copy to preserve your changes.")
        if actual is not None:
            previous = self.parse_note(note.id, actual)
            if all(getattr(previous, key) == getattr(note, key)
                   for key in ("body", "collection", "created", "starred", "workspace")):
                return
        if preserve_updated:
            if actual is not None:
                raise ValueError("Import timestamps can only be preserved for new notes")
            for timestamp in (note.created, note.updated):
                if timestamp:
                    try:
                        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        if timestamp[:10] != parsed.date().isoformat():
                            raise ValueError("Non-canonical timestamp date")
                    except (AttributeError, TypeError, ValueError):
                        raise ValueError("Invalid import timestamp") from None
        stamp = (note.updated if preserve_updated else "") or now()
        meta = {"collection": note.collection, "created": note.created or stamp,
                "updated": stamp, "starred": note.starred, "workspace": note.workspace}
        raw = "---\njotline: 1\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in meta.items()) + "\n---\n" + note.body
        if len(raw.encode("utf-8")) > MAX_NOTE_BYTES:
            raise ValueError(f"Note exceeds the {MAX_NOTE_BYTES}-byte file limit")
        from . import history
        fd, temp = create_private_temp(directory, ".jotline-")
        candidate = None
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            history.backup(self, automatic=True, vault_directory=directory,
                           pending=(path.name, raw) if actual is None else None)
            if actual is not None:
                history.snapshot(self, note.id, actual, vault_directory=directory)
            candidate = history.snapshot(self, note.id, raw, vault_directory=directory)
            # Revalidate as late as possible. For a brand-new note, publish with
            # an atomic hard link so an uncooperative creator can never be replaced.
            try:
                latest = read_regular_at(directory, path.name)
            except FileNotFoundError:
                latest = None
            if latest != actual:
                if latest is not None:
                    history.snapshot(self, note.id, latest, vault_directory=directory)
                raise ConflictError("This note changed outside Jotline. Save a recovery copy to preserve your changes.")
            if actual is None:
                try:
                    os.link(temp, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                except FileExistsError:
                    try:
                        history.snapshot(self, note.id, read_regular_at(directory, path.name),
                                         vault_directory=directory)
                    except (OSError, ValueError, UnicodeError):
                        pass
                    raise ConflictError("This note changed outside Jotline. Save a recovery copy to preserve your changes.") from None
                os.unlink(temp, dir_fd=directory)
            else:
                displaced = ".jotline-displaced-" + uuid4().hex
                keep_displaced = False
                try:
                    # Move aside precisely the inode present at publication time,
                    # then publish exclusively. Even an edit after the final read
                    # remains recoverable as the displaced file or a new collision.
                    replace_at(directory, path.name, displaced)
                    try:
                        os.link(temp, path.name, src_dir_fd=directory, dst_dir_fd=directory,
                                follow_symlinks=False)
                    except BaseException:
                        # Until the displaced inode is linked back under the note
                        # name, it is the only authoritative copy and must survive
                        # every error path.
                        keep_displaced = True
                        try:
                            collision = read_regular_at(directory, path.name)
                        except FileNotFoundError:
                            try:
                                os.link(displaced, path.name, src_dir_fd=directory, dst_dir_fd=directory,
                                        follow_symlinks=False)
                            except BaseException as restore_error:
                                self.warnings.append(
                                    f"Save failed; the original note was retained as {displaced}: {restore_error}")
                            else:
                                keep_displaced = False
                        else:
                            history.snapshot(self, note.id, collision, vault_directory=directory)
                            self.warnings.append(
                                f"Save collided with another writer; the original note was retained as {displaced}")
                        raise
                    os.unlink(temp, dir_fd=directory)
                    try:
                        displaced_raw = read_regular_at(directory, displaced)
                        if displaced_raw != actual:
                            history.snapshot(self, note.id, displaced_raw, vault_directory=directory)
                            self.warnings.append(
                                "An external edit raced with save and was preserved in note history")
                    except (OSError, ValueError, UnicodeError) as error:
                        keep_displaced = True
                        self.warnings.append(
                            f"A displaced external edit was retained as {displaced}: {error}")
                finally:
                    if not keep_displaced:
                        try:
                            os.unlink(displaced, dir_fd=directory)
                        except FileNotFoundError:
                            pass
            # Replacement has committed even if the directory durability check fails.
            # Keep the baseline current so retrying does not invent an edit conflict.
            note.original, note.updated, note.created = raw, stamp, meta["created"]
            self._cache.pop(note.id, None)
            os.fsync(directory)
        finally:
            if note.original != raw and candidate is not None:
                history.remove_revision(self, note.id, candidate.stem, vault_directory=directory)
            try:
                os.unlink(temp, dir_fd=directory)
            except FileNotFoundError:
                pass
        try:
            history.prune_history(self, note.id, vault_directory=directory)
        except OSError as error:
            self.warnings.append(f"History retention cleanup failed: {error}")

    def history(self, note_id: str):
        from .history import revisions
        return revisions(self, note_id)

    def read_revision(self, note_id: str, revision_id: str) -> Note:
        from .history import read_revision_raw
        raw = read_revision_raw(self, note_id, revision_id)
        return self.parse_note(note_id, raw)

    def history_notes(self, workspace: str) -> list[Note]:
        from .history import history_note_ids, read_revision_raw, revisions
        validate_workspace(workspace)
        notes = []
        directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for note_id in history_note_ids(self, vault_directory=directory):
                try:
                    for revision in revisions(self, note_id, vault_directory=directory):
                        try:
                            raw = read_revision_raw(
                                self, note_id, revision.id, vault_directory=directory)
                            note = self.parse_note(note_id, raw)
                        except (ValueError, OSError, UnicodeError) as error:
                            self.warnings.append(f"History {note_id}/{revision.id}: {error}")
                            continue
                        if note.workspace == workspace:
                            notes.append(note)
                            break
                except (ValueError, OSError) as error:
                    self.warnings.append(f"History {note_id}: {error}")
        finally:
            os.close(directory)
        return sorted(notes, key=lambda note: (note.updated, note.id), reverse=True)

    def backup(self) -> Path:
        from .history import backup
        with self.locked() as directory:
            return backup(self, vault_directory=directory)

    def daily(self, template: str = "# {{date}}\n\n", workspace: str = "default") -> Note:
        with self.locked() as directory:
            return self._daily_locked(template, workspace, directory=directory)

    def _daily_locked(self, template: str, workspace: str = "default", *, directory: int | None = None) -> Note:
        today = date.today().isoformat()
        validate_workspace(workspace)
        note_id = f"daily-{today}" + (f"-{workspace}" if workspace != "default" else "")
        try:
            note = self.read(note_id, directory=directory)
            if note.workspace != workspace:
                raise ValueError("This daily log was moved to another workspace; move it back or create a regular note")
            return note
        except FileNotFoundError:
            stamp = now()
            return Note(note_id, template.replace("{{date}}", today), "inbox", stamp, stamp, workspace=workspace)

    def append_daily(self, body: str, template: str = "# {{date}}\n\n", workspace: str = "default") -> Note:
        """Append a shell capture atomically with respect to other Jotline writers."""
        with self.locked() as directory:
            note = self._daily_locked(template, workspace, directory=directory)
            separator = "" if note.body.endswith("\n\n") else ("\n" if note.body.endswith("\n") else "\n\n")
            note.body = note.body + separator + body + "\n"
            self._save_locked(note, directory)
            return note

    def append_note(self, note_id: str, body: str, workspace: str, *, prepend: bool = False) -> Note:
        """Update a target under one lock, preserving piped text exactly."""
        with self.locked() as directory:
            note = self.read(note_id, directory=directory)
            if note.workspace != workspace:
                raise ValueError("Note is in another workspace; pass --workspace NAME")
            note.body = body + note.body if prepend else note.body + body
            self._save_locked(note, directory)
            return note

    def backlinks(self, target: Note) -> list[Note]:
        targets = {target.id, target.title}
        matches = []
        for note in self.notes():
            if note.id == target.id or note.collection == "trash" or note.workspace != target.workspace:
                continue
            linked = targets.intersection(note.links)
            self._collect_derived_warnings(note)
            if linked:
                matches.append(note)
        return matches

    def search(self, query: str = "", collection: str = "all", workspace: str | None = None) -> list[Note]:
        from .search import compile_query
        matches_query = compile_query(query)
        matches = []
        for note in self.notes():
            if workspace is not None and note.workspace != workspace:
                continue
            if collection == "all":
                included = note.collection != "trash"
            elif collection == "starred":
                included = note.starred and note.collection != "trash"
            else:
                included = note.collection == collection
            if not included:
                continue
            matched = matches_query(note)
            self._collect_derived_warnings(note)
            if matched:
                matches.append(note)
        return matches

    def tags(self, workspace: str) -> Counter:
        result = Counter()
        for note in self.search(workspace=workspace):
            result.update(note.tags)
            self._collect_derived_warnings(note)
        return result

    def _collect_derived_warnings(self, note: Note) -> None:
        for warning in note.derived_warnings:
            message = f"{note.id}.md: {warning}"
            if message not in self.warnings:
                self.warnings.append(message)

    def workspaces(self) -> set[str]:
        return {"default", *(note.workspace for note in self.notes())}

    def recovery(self, note: Note) -> Note:
        recovered = replace(note, id=uuid4().hex, original=None, created=now(), collection="inbox")
        self.save(recovered)
        return recovered
