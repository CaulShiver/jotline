"""Portable Markdown storage with atomic writes and optimistic concurrency."""
from __future__ import annotations

import codecs
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, date
import errno
import io
import json
from pathlib import Path
import re
import stat
import sys
from time import monotonic, sleep
from typing import NamedTuple
from uuid import uuid4

from .crypto import KEY_FILE, LOCKED, EncryptionError, KeyFile, NoteCipher, is_sealed, new_note_key
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
# Editor insertions stop this far short of the file limit so the metadata header always fits.
EDIT_LIMIT_BYTES = MAX_NOTE_BYTES - 4096

CONFLICT_MESSAGE = "This note changed outside Jotline. Save a recovery copy to preserve your changes."
OTHER_WORKSPACE = "Note is in another workspace; pass --workspace NAME"


class FileSignature(NamedTuple):
    """What must match for a cached parse of a note file to be reused."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")
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


def validate_note_id(note_id: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", note_id):
        raise ValueError("Invalid note ID")
    return note_id


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


def decode_problem(error: UnicodeDecodeError, encoding: str = "utf-8") -> str:
    """Describe undecodable input without Python codec jargon."""
    label = "UTF-8" if codecs.lookup(encoding).name == "utf-8" else encoding
    return f"not valid {label} text (bad byte at position {error.start})"


def _read_regular_fd(fd: int, name: str, max_bytes: int, encoding: str = "utf-8", errors: str = "strict") -> str:
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
    return bytes(raw).decode(encoding, errors)


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


def unlink_quietly(directory: int, name: str) -> None:
    """Remove a temporary file from a pinned directory; it may already be gone."""
    try:
        os.unlink(name, dir_fd=directory)
    except FileNotFoundError:
        pass


# Hard links are refused on FAT/exFAT media, most SMB shares and shared folders.
LINK_UNSUPPORTED = {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.EXDEV,
                    getattr(errno, "ENOSYS", errno.EPERM), errno.EACCES}


def link_unsupported(error: OSError) -> bool:
    return error.errno in LINK_UNSUPPORTED


def publish_new(directory: int, source: str, target: str) -> None:
    """Publish a complete file under a name that must not already exist.

    A hard link is atomic and exclusive. Where the filesystem refuses links,
    fall back to an existence check plus rename so the note is never lost.
    """
    try:
        os.link(source, target, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    except OSError as error:
        if isinstance(error, FileExistsError) or not link_unsupported(error):
            raise
        try:
            os.stat(target, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            os.replace(source, target, src_dir_fd=directory, dst_dir_fd=directory)
        else:
            raise FileExistsError(errno.EEXIST, "File exists", target) from None


def pin_ancestors(absolute: Path) -> int:
    """Open every ancestor of an absolute path without following links.

    Returns a descriptor for the parent directory; the caller closes it.
    """
    directory = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in absolute.parts[1:-1]:
            try:
                next_directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                         dir_fd=directory)
            except OSError as error:
                if isinstance(error, NotADirectoryError) or error.errno == errno.ELOOP:
                    raise OSError(
                        f"Path passes through a link at {component}; use the real path") from None
                raise
            os.close(directory)
            directory = next_directory
    except BaseException:
        os.close(directory)
        raise
    return directory


def read_regular_file(path: Path, max_bytes: int = MAX_NOTE_BYTES, *, ancestor_safe: bool = False,
                      encoding: str = "utf-8", errors: str = "strict") -> str:
    """Read bounded text (UTF-8 by default) without following links or blocking on a pipe."""
    if ancestor_safe:
        absolute = Path(path).absolute()
        directory = pin_ancestors(absolute)
        try:
            fd = os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
    else:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        return _read_regular_fd(fd, path.name, max_bytes, encoding, errors)
    finally:
        os.close(fd)


@contextmanager
def vault_lock(path: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
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
        deadline = monotonic() + timeout
        while True:
            try:
                lock_file(fd)
                break
            except BlockingIOError:
                if monotonic() >= deadline:
                    raise OSError("Vault is busy in another process; try saving again") from None
                sleep(0.025)
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
        return FileSignature(*os.file_signature(path))
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"Not a regular file: {path.name}")
    return FileSignature(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


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
    encrypted: bool = False
    # The encrypted text while encrypted notes are locked; the body is empty then.
    sealed: str | None = field(default=None, repr=False)
    derived_warnings: list[str] = field(default_factory=list, repr=False, compare=False)

    def _derived(self, pattern: re.Pattern, label: str) -> set[str]:
        values, warning = _derived_values(pattern, self.body, label)
        if warning and warning not in self.derived_warnings:
            self.derived_warnings.append(warning)
        return values

    @property
    def locked(self) -> bool:
        return self.sealed is not None

    @property
    def heading(self) -> str:
        """The full first non-blank line; links by title match against this."""
        if self.locked:
            return "Encrypted note (locked)"
        for line in io.StringIO(self.body):
            if line.strip():
                return line.lstrip("# ").strip() or "Untitled"
        return "Untitled"

    @property
    def title(self) -> str:
        return self.heading[:100]

    @property
    def tags(self) -> set[str]:
        return {tag.casefold() for tag in self._derived(TAG, "tags")}

    @property
    def links(self) -> set[str]:
        return self._derived(LINK, "links")


class Vault:
    def __init__(self, path: Path, *, create: bool = True):
        self.path = path.expanduser().resolve()
        if create:
            self.path.mkdir(parents=True, exist_ok=True)
        elif not self.path.is_dir():
            raise FileNotFoundError(
                f"Vault does not exist: {self.path} (start jotline or capture a note to create it)")
        self.warnings: list[str] = []
        # Warnings that name a retained file survive every sidebar refresh.
        self.sticky_warnings: list[str] = []
        self.backup_warning = ""
        self.lock_timeout = LOCK_TIMEOUT_SECONDS
        # Set by unlock(); while None, encrypted notes read as locked and their text stays sealed.
        self.cipher: NoteCipher | None = None
        self._cache: dict[str, tuple[FileSignature, Note, int, float]] = {}
        self.permission_warning = ("Vault is writable by other users; use chmod go-w to protect note replacement"
                                   if os.name != "nt" and self.path.stat().st_mode & 0o022 else "")
        if self.permission_warning:
            self.warnings.append(self.permission_warning)

    def locked(self):
        """Hold the vault's write lock (unrelated to Note.locked, which means encrypted and sealed)."""
        return vault_lock(self.path, self.lock_timeout)

    def retain_warning(self, message: str) -> None:
        self.sticky_warnings.append(message)
        self.warnings.append(message)

    def file(self, note_id: str) -> Path:
        return self.path / f"{validate_note_id(note_id)}.md"

    def new(self, body: str = "", workspace: str = "default") -> Note:
        stamp = now()
        return Note(uuid4().hex, body, created=stamp, updated=stamp, workspace=validate_workspace(workspace))

    def read(self, note_id: str, *, workspace: str | None = None, directory: int | None = None) -> Note:
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
        note = self.parse_note(note_id, raw, self.cipher)
        if workspace is not None and note.workspace != workspace:
            raise ValueError(OTHER_WORKSPACE)
        return note

    def titles(self, workspace: str) -> dict[str, str]:
        """Current titles for exports and previews, including external edits."""
        return {note.id: note.title for note in self.search(workspace=workspace)}

    @staticmethod
    def parse_note(note_id: str, raw: str, cipher=None) -> Note:
        """Parse a note file. Without a cipher, an encrypted note stays sealed and locked."""
        meta = {}
        # Some editors prepend a byte-order mark; it is not part of the note.
        body = raw.removeprefix("\ufeff")
        if re.match(r"\A---\r?\njotline: 1\r?\n", body):
            boundary = re.search(r"\r?\n---\r?\n", body)
            if boundary is None:
                raise ValueError("Incomplete Jotline metadata header")
            header = body[body.index("\n") + 1:boundary.start()]
            for line in header.splitlines():
                key, sep, value = line.partition(": ")
                if sep and key in {"collection", "created", "updated", "starred", "workspace", "encrypted"}:
                    try:
                        meta[key] = json.loads(value)
                    except RecursionError:
                        raise ValueError("Metadata is nested too deeply") from None
            body = body[boundary.end():]
        if meta.get("collection", "inbox") not in COLLECTIONS:
            raise ValueError("Unknown collection")
        if any(not isinstance(meta.get(k, ""), str) for k in ("created", "updated")):
            raise ValueError("Invalid timestamps")
        if not isinstance(meta.get("starred", False), bool):
            raise ValueError("Invalid starred value")
        if not isinstance(meta.get("encrypted", False), bool):
            raise ValueError("Invalid encrypted value")
        validate_workspace(meta.get("workspace", "default"))
        if meta.get("encrypted"):
            if not is_sealed(body):
                raise ValueError("Encrypted note is missing its encrypted text")
            if cipher is None:
                return Note(note_id, "", original=raw, sealed=body, **meta)
            body = cipher.open(note_id, body)
        return Note(note_id, body, original=raw, **meta)

    def invalidate_cache(self) -> None:
        """Force the next scan to reread note bodies from disk."""
        self._cache.clear()

    def notes(self) -> list[Note]:
        notes = []
        self.warnings = ([self.permission_warning] if self.permission_warning else []) + list(self.sticky_warnings)
        refreshed = {}
        retained_bytes = 0
        scanned_bytes = 0
        for index, file in enumerate(self.path.glob("*.md")):
            if index >= MAX_SCAN_ENTRIES:
                self.warnings.append(f"Vault scan stopped after {MAX_SCAN_ENTRIES} entries; results are incomplete")
                break
            try:
                signature = file_signature(file)
                scanned_bytes += signature.size
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

    def _check_saveable(self, note: Note) -> None:
        validate_workspace(note.workspace)
        if note.collection not in COLLECTIONS:
            raise ValueError("Unknown collection")
        if not isinstance(note.body, str) or not isinstance(note.starred, bool):
            raise ValueError("Invalid note body or starred value")
        if not all(isinstance(value, str) for value in (note.created, note.updated)):
            raise ValueError("Invalid timestamps")
        if not isinstance(note.encrypted, bool):
            raise ValueError("Invalid encrypted value")
        # A locked note's text is unknown here: only its metadata may change.
        if (note.locked and (note.body or not note.encrypted)) or (
                note.encrypted and not note.locked and self.cipher is None):
            raise ValueError(LOCKED)

    def _save_locked(self, note: Note, directory: int, *, preserve_updated: bool = False) -> None:
        self._check_saveable(note)
        path = self.file(note.id)
        try:
            actual = read_regular_at(directory, path.name)
        except FileNotFoundError:
            actual = None
        if actual != note.original:
            raise ConflictError(CONFLICT_MESSAGE)
        previous = None
        if actual is not None:
            previous = self.parse_note(note.id, actual, None if note.locked else self.cipher)
            # Sealed text is bound to its note ID, so it can be kept but never moved elsewhere.
            if note.locked and previous.sealed != note.sealed:
                raise ValueError(LOCKED)
            if all(getattr(previous, key) == getattr(note, key)
                   for key in ("body", "collection", "created", "starred", "workspace", "encrypted")):
                return
        elif note.locked:
            raise ValueError(LOCKED)
        newly_encrypted = note.encrypted and previous is not None and not previous.encrypted
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
        if note.encrypted:
            meta["encrypted"] = True
        stored = note.sealed if note.locked else self.cipher.seal(note.id, note.body) if note.encrypted else note.body
        raw = "---\njotline: 1\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in meta.items()) + "\n---\n" + stored
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
            try:
                history.backup(self, automatic=True, vault_directory=directory,
                               pending=(path.name, raw) if actual is None else None)
            except OSError as error:
                # A failed daily backup must never hold the note itself hostage;
                # the overwritten text is still snapshotted to history below.
                message = f"Daily backup failed: {error}"
                self.backup_warning = "; ".join(filter(None, (self.backup_warning, message)))
                if message not in self.warnings:
                    self.warnings.append(message)
            if actual is not None and not newly_encrypted:
                # A note being encrypted must not leave its plain text behind in history.
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
                raise ConflictError(CONFLICT_MESSAGE)
            if actual is None:
                try:
                    publish_new(directory, temp, path.name)
                except FileExistsError:
                    try:
                        history.snapshot(self, note.id, read_regular_at(directory, path.name),
                                         vault_directory=directory)
                    except (OSError, ValueError):
                        pass
                    raise ConflictError(CONFLICT_MESSAGE) from None
                unlink_quietly(directory, temp)
            else:
                displaced = ".jotline-displaced-" + uuid4().hex
                keep_displaced = False
                try:
                    # Move aside precisely the inode present at publication time,
                    # then publish exclusively. Even an edit after the final read
                    # remains recoverable as the displaced file or a new collision.
                    replace_at(directory, path.name, displaced)
                    try:
                        publish_new(directory, temp, path.name)
                    except BaseException:
                        # Until the displaced inode is linked back under the note
                        # name, it is the only authoritative copy and must survive
                        # every error path.
                        keep_displaced = True
                        try:
                            collision = read_regular_at(directory, path.name)
                        except FileNotFoundError:
                            try:
                                # Rename works on every filesystem; the displaced
                                # inode is the only copy, so put it straight back.
                                replace_at(directory, displaced, path.name)
                            except BaseException as restore_error:
                                self.retain_warning(
                                    f"Save failed; the original note was retained as {displaced}: {restore_error}")
                            else:
                                keep_displaced = False
                        else:
                            history.snapshot(self, note.id, collision, vault_directory=directory)
                            self.retain_warning(
                                f"Save collided with another writer; the original note was retained as {displaced}")
                        raise
                    unlink_quietly(directory, temp)  # The rename fallback may have consumed it.
                    try:
                        displaced_raw = read_regular_at(directory, displaced)
                        if displaced_raw != actual:
                            history.snapshot(self, note.id, displaced_raw, vault_directory=directory)
                            self.warnings.append(
                                "An external edit raced with save and was preserved in note history")
                    except (OSError, ValueError) as error:
                        keep_displaced = True
                        self.retain_warning(
                            f"A displaced external edit was retained as {displaced}: {error}")
                finally:
                    if not keep_displaced:
                        unlink_quietly(directory, displaced)
            # Replacement has committed even if the directory durability check fails.
            # Keep the baseline current so retrying does not invent an edit conflict.
            note.original, note.updated, note.created = raw, stamp, meta["created"]
            self._cache.pop(note.id, None)
            os.fsync(directory)
        finally:
            if note.original != raw and candidate is not None:
                history.remove_revision(self, note.id, candidate.stem, vault_directory=directory)
            unlink_quietly(directory, temp)
        try:
            history.prune_history(self, note.id, vault_directory=directory)
        except OSError as error:
            self.warnings.append(f"History retention cleanup failed: {error}")
        if newly_encrypted:
            try:
                history.remove_unencrypted_revisions(
                    self, note.id, lambda text: self.parse_note(note.id, text).encrypted, vault_directory=directory)
            except OSError as error:
                self.retain_warning(f"Unencrypted saved versions of {note.id} could not be removed: {error}")

    def history(self, note_id: str):
        from .history import revisions
        return revisions(self, note_id)

    def read_revision(self, note_id: str, revision_id: str) -> Note:
        from .history import read_revision_raw
        raw = read_revision_raw(self, note_id, revision_id)
        return self.parse_note(note_id, raw, self.cipher)

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
                            note = self.parse_note(note_id, raw, self.cipher)
                        except (ValueError, OSError) as error:
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

    def append_note(self, note_id: str, body: str, workspace: str, *, prepend: bool = False,
                    line_break: bool = False) -> Note:
        """Update a target under one lock, preserving piped text exactly.

        With line_break, text that would run into the existing body is joined
        on a new line in the note's own newline style.
        """
        with self.locked() as directory:
            note = self.read(note_id, workspace=workspace, directory=directory)
            if line_break and note.body and body:
                newline = "\r\n" if "\r\n" in note.body else ("\r" if "\r" in note.body else "\n")
                if prepend and not body.endswith(("\n", "\r")):
                    body += newline
                elif not prepend and not note.body.endswith(("\n", "\r")) and not body.startswith(("\n", "\r")):
                    body = newline + body
            note.body = body + note.body if prepend else note.body + body
            self._save_locked(note, directory)
            return note

    def backlinks(self, target: Note) -> list[Note]:
        targets = {target.id, target.title, target.heading}
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

    def has_key(self) -> bool:
        try:
            (self.path / KEY_FILE).lstat()
        except FileNotFoundError:
            return False
        return True

    def _read_key(self, directory: int) -> KeyFile:
        try:
            return KeyFile.loads(read_regular_at(directory, KEY_FILE, MAX_SETTINGS_BYTES))
        except FileNotFoundError:
            raise EncryptionError("Encryption is not set up for this vault") from None

    def _write_key(self, directory: int, key: KeyFile, *, replace_existing: bool) -> None:
        fd, temp = create_private_temp(directory, ".jotline-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(key.dumps())
                stream.flush()
                os.fsync(stream.fileno())
            if replace_existing:
                replace_at(directory, temp, KEY_FILE)
            else:
                publish_new(directory, temp, KEY_FILE)
            os.fsync(directory)
        finally:
            unlink_quietly(directory, temp)

    def unlock(self, passphrase: str) -> None:
        """Unwrap the note key so encrypted notes read and save as text."""
        directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            key = self._read_key(directory)
        finally:
            os.close(directory)
        self.cipher = NoteCipher(key.unwrap(passphrase))
        self.invalidate_cache()

    def lock(self) -> None:
        self.cipher = None
        self.invalidate_cache()

    def setup_encryption(self, passphrase: str, *, n: int | None = None) -> None:
        from .crypto import SCRYPT_N

        already = "Encryption is already set up for this vault; change its passphrase instead"
        if self.has_key():
            raise ValueError(already)
        note_key = new_note_key()
        key = KeyFile.create(passphrase, note_key, n=n or SCRYPT_N)
        with self.locked() as directory:
            try:
                # Never replace an existing key: notes sealed with it would become unreadable.
                self._write_key(directory, key, replace_existing=False)
            except FileExistsError:
                raise ValueError(already) from None
        self.cipher = NoteCipher(note_key)
        self.invalidate_cache()

    def change_passphrase(self, old: str, new: str) -> None:
        """Rewrap the note key; encrypted notes themselves are not rewritten."""
        with self.locked() as directory:
            current = self._read_key(directory)
            note_key = current.unwrap(old)
            self._write_key(directory, KeyFile.create(new, note_key, n=current.n), replace_existing=True)

    def set_encrypted(self, note_id: str, workspace: str, encrypted: bool) -> tuple[Note, bool]:
        """Encrypt or decrypt one note; returns the note and whether anything changed."""
        with self.locked() as directory:
            note = self.read(note_id, workspace=workspace, directory=directory)
            if note.locked or (encrypted and self.cipher is None):
                raise ValueError(LOCKED)
            if note.encrypted == encrypted:
                return note, False
            note.encrypted = encrypted
            self._save_locked(note, directory)
            return note, True

    def update_body(self, note_id: str, workspace: str, change) -> Note:
        """Replace a note's text with change(text) under one lock."""
        with self.locked() as directory:
            note = self.read(note_id, workspace=workspace, directory=directory)
            if note.locked:
                raise ValueError(LOCKED)
            note.body = change(note.body)
            self._save_locked(note, directory)
            return note

    def recovery(self, note: Note) -> Note:
        if note.locked:
            raise ValueError(LOCKED)
        recovered = replace(note, id=uuid4().hex, original=None, created=now(), collection="inbox")
        self.save(recovered)
        return recovered
