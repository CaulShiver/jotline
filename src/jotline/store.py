"""Portable Markdown storage with atomic writes and optimistic concurrency."""
from __future__ import annotations

import codecs
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, date, timedelta
import json
from pathlib import Path
import re
import sys
from time import monotonic
from uuid import uuid4

from .crypto import KEY_FILE, LOCKED, SCRYPT_N, EncryptionError, KeyFile, NoteCipher, is_sealed, new_note_key
# Several names below are re-exported: other modules and the tests import
# them from jotline.store rather than reaching into jotline.filesystem.
from .filesystem import (
    FileSignature,
    create_private_temp,
    file_signature,
    follow_root_prefix_symlinks,  # noqa: F401
    fs as os,
    pin_ancestors,  # noqa: F401
    publish_new,
    read_regular_at,
    read_regular_fd,
    read_regular_file,  # noqa: F401
    replace_at,
    restore_displaced,
    unlink_quietly,
    vault_lock,
)
from .limits import (
    CACHE_TTL_SECONDS,
    EDIT_LIMIT_BYTES,  # noqa: F401
    LOCK_TIMEOUT_SECONDS,
    MAX_CACHE_BYTES,
    MAX_CACHED_NOTES,
    MAX_DERIVED_ITEMS,
    MAX_NOTE_BYTES,
    MAX_SCAN_BYTES,
    MAX_SCAN_ENTRIES,
    MAX_SETTINGS_BYTES,
)
from .links import LINK, NoteConnections, connect_note, wiki_link_targets  # noqa: F401
from .search import compile_query
from .tasks import gather

COLLECTIONS = ("inbox", "projects", "areas", "resources", "archive", "trash")

CONFLICT_MESSAGE = "This note changed outside Jotline. Save a recovery copy to preserve your changes."
OTHER_WORKSPACE = "Note is in another workspace; pass --workspace NAME"

# Start with the literal marker so the regex engine can skip directly to '#'.
# The two-character lookbehind then rejects the same word/# prefixes as before.
TAG = re.compile(r"#(?<![\w#]#)([\w][\w/-]*)", re.UNICODE)


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


def displaced_note_id(name: str) -> str | None:
    """The note a displaced original belongs to, or None when the name predates it."""
    if not name.startswith(history.DISPLACED_PREFIX):
        return None
    # A note ID cannot contain a dot, so the first one separates it from the
    # unique suffix. Names written before 0.9.9 are only the suffix and name
    # no note; those stay for the user to sort out, as doctor already says.
    stem, separator, _ = name[len(history.DISPLACED_PREFIX):].partition(".")
    if not separator:
        return None
    try:
        return validate_note_id(stem)
    except ValueError:
        return None


def parse_calendar_date(value: str, *, today: date | None = None) -> date:
    """YYYY-MM-DD, today, or yesterday. Compact dates such as 20260914 are refused."""
    today = today or date.today()
    text = value.strip()
    folded = text.casefold()
    if folded == "today":
        return today
    if folded == "yesterday":
        return today - timedelta(days=1)
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != text:
        raise ValueError("Use a date like 2026-09-14, today, or yesterday")
    return parsed


def daily_id(when: date, workspace: str = "default") -> str:
    validate_workspace(workspace)
    return f"daily-{when.isoformat()}" + (f"-{workspace}" if workspace != "default" else "")


def daily_date_from_id(note_id: str) -> date | None:
    """The calendar day encoded in a daily log ID, if the ID is well formed."""
    if not note_id.startswith("daily-"):
        return None
    parts = note_id.split("-")
    if len(parts) < 4:
        return None
    stamp = "-".join(parts[1:4])
    try:
        parsed = date.fromisoformat(stamp)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == stamp else None


def is_daily_id(note_id: str) -> bool:
    return note_id.startswith("daily-")


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


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


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
    # Note ID this inbox copy was preserved from after an external change.
    recovery_of: str | None = None
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
        start = 0
        while start < len(self.body):
            end = self.body.find("\n", start)
            if end < 0:
                end = len(self.body)
            line = self.body[start:end]
            if line.strip():
                return line.lstrip("# ").strip() or "Untitled"
            start = end + 1
        return "Untitled"

    @property
    def title(self) -> str:
        return self.heading[:100]

    @property
    def tags(self) -> set[str]:
        return {tag.casefold() for tag in self._derived(TAG, "tags")}

    @property
    def links(self) -> set[str]:
        values, warning = wiki_link_targets(self.body)
        if warning and warning not in self.derived_warnings:
            self.derived_warnings.append(warning)
        return values


def wiki_link(note: Note) -> str:
    """Stable wiki-link markup for a note, with a title label safe for [[id|label]].

    An encrypted note contributes no label. Its title is the first line of the
    decrypted body, and the note being linked from is usually not encrypted, so
    a label would copy that line into a plaintext file, its history and every
    backup, where it would stay after the vault was locked again. A bare link
    still resolves, and the list and the picker still show the real title.
    """
    if note.encrypted:
        return f"[[{note.id}]]"
    label = note.title.replace("|", " ").replace("[", "").replace("]", "")
    return f"[[{note.id}|{label}]]"


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
        self._recovered_displaced = False
        self.permission_warning = ("Vault is writable by other users; use chmod go-w to protect note replacement"
                                   if self.path.stat().st_mode & 0o022 else "")
        if self.permission_warning:
            self.warnings.append(self.permission_warning)

    def write_lock(self):
        """Hold the vault's write lock (unrelated to Note.locked, which means encrypted and sealed)."""
        return vault_lock(self.path, self.lock_timeout)

    def locked(self):
        """Compatibility alias for callers using the original lock helper."""
        return self.write_lock()

    def retain_warning(self, message: str) -> None:
        if message not in self.sticky_warnings:
            self.sticky_warnings.append(message)
        if message not in self.warnings:
            self.warnings.append(message)

    def file(self, note_id: str) -> Path:
        return self.path / f"{validate_note_id(note_id)}.md"

    def new(self, body: str = "", workspace: str = "default") -> Note:
        stamp = now()
        return Note(uuid4().hex, body, created=stamp, updated=stamp, workspace=validate_workspace(workspace))

    def read(self, note_id: str, *, workspace: str | None = None, directory: int | None = None,
             locked: bool = False) -> Note:
        filename = self.file(note_id).name
        own_directory = directory is None
        if own_directory:
            directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                raw = read_regular_fd(fd, filename, MAX_NOTE_BYTES)
            finally:
                os.close(fd)
        finally:
            if own_directory:
                os.close(directory)
        note = self.parse_note(note_id, raw, None if locked else self.cipher)
        if workspace is not None and note.workspace != workspace:
            raise ValueError(OTHER_WORKSPACE)
        return note

    def titles(self, workspace: str, *, notes: list[Note] | None = None) -> dict[str, str]:
        """Current titles for exports and previews, including external edits."""
        return {note.id: note.title for note in self.search(workspace=workspace, notes=notes)}

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
                if sep and key in {"collection", "created", "updated", "starred", "workspace",
                                   "encrypted", "recovery_of"}:
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
        if meta.get("recovery_of") is not None:
            if not isinstance(meta["recovery_of"], str):
                raise ValueError("Invalid recovery source")
            validate_note_id(meta["recovery_of"])
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

    def recover_displaced(self) -> list[str]:
        """Put back displaced originals whose note file is missing.

        A save moves the note aside and then publishes the new text under its
        name. A crash in that window, or a filesystem that refuses both a hard
        link and an exclusive rename, leaves the only copy of the note under a
        hidden name that nothing lists: the note is simply gone from the app.
        Where the note's own name is free again, the displaced file is that
        note, so put it back. A displaced file whose note does exist is the
        litter of a save that did finish, and doctor already reports it.
        """
        recovered: list[str] = []
        try:
            with os.scandir(self.path) as entries:
                names = [entry.name for index, entry in enumerate(entries)
                         if index < MAX_SCAN_ENTRIES and entry.name.startswith(history.DISPLACED_PREFIX)]
        except OSError:
            return recovered
        pending = [(name, note_id) for name in names
                   if (note_id := displaced_note_id(name)) and not self.file(note_id).exists()]
        if not pending:
            return recovered
        try:
            with self.write_lock():
                directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    for name, note_id in pending:
                        try:
                            # Read it first: a symlink or a directory under that
                            # name is not a note and must not be published as one.
                            read_regular_at(directory, name)
                            restore_displaced(directory, name, self.file(note_id).name)
                        except (OSError, ValueError):
                            continue
                        recovered.append(note_id)
                    if recovered:
                        history.sync_directory(directory)
                finally:
                    os.close(directory)
        except OSError:
            return recovered
        for note_id in recovered:
            self.warnings.append(f"Recovered note {note_id}; a save had left it under a hidden name")
        return recovered

    def notes(self) -> list[Note]:
        notes = []
        self.warnings = ([self.permission_warning] if self.permission_warning else []) + list(self.sticky_warnings)
        if self.backup_warning and self.backup_warning not in self.warnings:
            self.warnings.append(self.backup_warning)
        if not self._recovered_displaced:
            self._recovered_displaced = True
            self.recover_displaced()
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
                if isinstance(error, EncryptionError):
                    # An encrypted note that will not open stays listed, sealed as
                    # when locked, rather than vanish as though deleted. It is not
                    # cached, so every scan reports it again.
                    try:
                        notes.append(self.read(file.stem, locked=True))
                    except (ValueError, OSError):
                        pass
        self._cache = refreshed
        return sorted(notes, key=lambda n: (n.starred, n.updated, n.id), reverse=True)

    def save(self, note: Note, *, preserve_updated: bool = False) -> None:
        with self.write_lock() as directory:
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

    def _serialized(self, note: Note, previous: Note | None, actual: str | None,
                    *, preserve_updated: bool) -> tuple[str, dict, str, bool]:
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
        if note.recovery_of:
            meta["recovery_of"] = validate_note_id(note.recovery_of)
        stored = note.sealed if note.locked else self.cipher.seal(note.id, note.body) if note.encrypted else note.body
        raw = "---\njotline: 1\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in meta.items()) + "\n---\n" + stored
        if len(raw.encode("utf-8")) > MAX_NOTE_BYTES:
            raise ValueError(f"Note exceeds the {MAX_NOTE_BYTES}-byte file limit")
        return stamp, meta, raw, newly_encrypted

    def _write_temp(self, directory: int, raw: str) -> str:
        fd, temp = create_private_temp(directory, ".jotline-")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return temp

    def _publish_created(self, directory: int, temp: str, filename: str, note_id: str) -> None:
        try:
            publish_new(directory, temp, filename)
        except FileExistsError:
            try:
                history.snapshot(self, note_id, read_regular_at(directory, filename),
                                 vault_directory=directory)
            except (OSError, ValueError):
                pass
            raise ConflictError(CONFLICT_MESSAGE) from None
        unlink_quietly(directory, temp)

    def _publish_replace(self, directory: int, temp: str, filename: str, note_id: str,
                         actual: str) -> None:
        # The note ID is in the name because nothing else records it: the note
        # file has no ID in its header, its name is the ID. Without it a
        # displaced original cannot be put back by anything but a human.
        displaced = f"{history.DISPLACED_PREFIX}{note_id}.{uuid4().hex}"
        keep_displaced = False
        try:
            # Move aside precisely the inode present at publication time,
            # then publish exclusively. Even an edit after the final read
            # remains recoverable as the displaced file or a new collision.
            replace_at(directory, filename, displaced)
            try:
                publish_new(directory, temp, filename)
            except BaseException:
                # Until the displaced inode is linked back under the note
                # name, it is the only authoritative copy and must survive
                # every error path.
                keep_displaced = True
                try:
                    collision = read_regular_at(directory, filename)
                except FileNotFoundError:
                    try:
                        # Restore only into a free name. A creator after the
                        # read above must not lose its own content.
                        restore_displaced(directory, displaced, filename)
                    except BaseException as restore_error:
                        self.retain_warning(
                            f"Save failed; the original note was retained as {displaced}: {restore_error}")
                    else:
                        keep_displaced = False
                else:
                    history.snapshot(self, note_id, collision, vault_directory=directory)
                    self.retain_warning(
                        f"Save collided with another writer; the original note was retained as {displaced}")
                raise
            unlink_quietly(directory, temp)  # The rename fallback may have consumed it.
            try:
                displaced_raw = read_regular_at(directory, displaced)
                if displaced_raw != actual:
                    history.snapshot(self, note_id, displaced_raw, vault_directory=directory)
                    self.warnings.append(
                        "An external edit raced with save and was preserved in note history")
            except (OSError, ValueError) as error:
                keep_displaced = True
                self.retain_warning(
                    f"A displaced external edit was retained as {displaced}: {error}")
        finally:
            if not keep_displaced:
                unlink_quietly(directory, displaced)

    def _post_commit(self, note: Note, directory: int, *, newly_encrypted: bool) -> None:
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

    def _save_locked(self, note: Note, directory: int, *, preserve_updated: bool = False) -> None:
        self._check_saveable(note)
        path = self.file(note.id)
        try:
            actual = read_regular_at(directory, path.name)
        except FileNotFoundError:
            actual = None
        if actual != note.original:
            raise ConflictError(CONFLICT_MESSAGE)
        if note.encrypted:
            # Outline revisions are hashes of plaintext, so they must not remain
            # beside ciphertext (including on otherwise unchanged saves).
            from .outline_state import STATE_FILE, remove_state_locked
            remove_state_locked(self.path / STATE_FILE, note.id, directory)
        previous = None
        if actual is not None:
            previous = self.parse_note(note.id, actual, None if note.locked else self.cipher)
            # Sealed text is bound to its note ID, so it can be kept but never moved elsewhere.
            if note.locked and previous.sealed != note.sealed:
                raise ValueError(LOCKED)
            if all(getattr(previous, key) == getattr(note, key)
                   for key in ("body", "collection", "created", "starred", "workspace",
                               "encrypted", "recovery_of")):
                return
        elif note.locked:
            raise ValueError(LOCKED)
        stamp, meta, raw, newly_encrypted = self._serialized(
            note, previous, actual, preserve_updated=preserve_updated)
        temp = self._write_temp(directory, raw)
        candidate = None
        try:
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
                self._publish_created(directory, temp, path.name, note.id)
            else:
                self._publish_replace(directory, temp, path.name, note.id, actual)
            # Replacement has committed even if the directory durability check fails.
            # Keep the baseline current so retrying does not invent an edit conflict.
            note.original, note.updated, note.created = raw, stamp, meta["created"]
            self._cache.pop(note.id, None)
            os.fsync(directory)
        finally:
            if note.original != raw and candidate is not None:
                history.remove_revision(self, note.id, candidate.stem, vault_directory=directory)
            unlink_quietly(directory, temp)
        self._post_commit(note, directory, newly_encrypted=newly_encrypted)

    def history(self, note_id: str):
        return history.revisions(self, note_id)

    def read_revision(self, note_id: str, revision_id: str) -> Note:
        raw = history.read_revision_raw(self, note_id, revision_id)
        return self.parse_note(note_id, raw, self.cipher)

    def history_notes(self, workspace: str) -> list[Note]:
        validate_workspace(workspace)
        notes = []
        directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for note_id in history.history_note_ids(self, vault_directory=directory):
                try:
                    for revision in history.revisions(self, note_id, vault_directory=directory):
                        try:
                            raw = history.read_revision_raw(
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
        with self.write_lock() as directory:
            return history.backup(self, vault_directory=directory)

    def daily(self, template: str = "# {{date}}\n\n", workspace: str = "default",
              when: date | None = None) -> Note:
        with self.write_lock() as directory:
            return self._daily_locked(template, workspace, when=when, directory=directory)

    def _daily_locked(self, template: str, workspace: str = "default", *,
                      when: date | None = None, directory: int | None = None) -> Note:
        day = when or date.today()
        note_id = daily_id(day, workspace)
        try:
            note = self.read(note_id, directory=directory)
            if note.workspace != workspace:
                raise ValueError("This daily log was moved to another workspace; move it back or create a regular note")
            return note
        except FileNotFoundError:
            stamp = now()
            return Note(note_id, template.replace("{{date}}", day.isoformat()), "inbox", stamp, stamp,
                        workspace=workspace)

    def append_daily(self, body: str, template: str = "# {{date}}\n\n", workspace: str = "default",
                     when: date | None = None) -> Note:
        """Append a shell capture atomically with respect to other Jotline writers."""
        with self.write_lock() as directory:
            note = self._daily_locked(template, workspace, when=when, directory=directory)
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
        with self.write_lock() as directory:
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

    def _included(self, note: Note, collection: str, workspace: str | None) -> bool:
        if workspace is not None and note.workspace != workspace:
            return False
        if collection == "all":
            return note.collection != "trash"
        if collection == "starred":
            return note.starred and note.collection != "trash"
        return note.collection == collection

    def workspace_notes(self, workspace: str, *, notes: list[Note] | None = None) -> list[Note]:
        """Notes in one workspace, excluding trash. Collects derived-link warnings."""
        found = []
        for note in (self.notes() if notes is None else notes):
            if note.collection == "trash" or note.workspace != workspace:
                continue
            self._collect_derived_warnings(note)
            found.append(note)
        return found

    def connections(self, target: Note, *, notes: list[Note] | None = None,
                    body: str | None = None) -> NoteConnections:
        peers = self.workspace_notes(target.workspace, notes=notes)
        return connect_note(target, peers, body=body)

    def backlinks(self, target: Note, *, notes: list[Note] | None = None) -> list[Note]:
        peers = self.workspace_notes(target.workspace, notes=notes)
        by_id = {note.id: note for note in peers}
        return [by_id[item.note_id] for item in connect_note(target, peers).incoming if item.note_id]

    def search(self, query: str = "", collection: str = "all", workspace: str | None = None,
               *, notes: list[Note] | None = None) -> list[Note]:
        matches_query = compile_query(query)
        matches = []
        for note in (self.notes() if notes is None else notes):
            if not self._included(note, collection, workspace):
                continue
            matched = matches_query(note)
            self._collect_derived_warnings(note)
            if matched:
                matches.append(note)
        return matches

    def inbox_captures(self, workspace: str, *, notes: list[Note] | None = None) -> list[Note]:
        """Oldest inbox notes that are not daily logs, so processing skips the log itself."""
        snapshot = self.notes() if notes is None else notes
        captures = [note for note in self.search(collection="inbox", workspace=workspace, notes=snapshot)
                    if not is_daily_id(note.id) and not note.locked]
        captures.sort(key=lambda note: (note.created, note.id))
        return captures

    def stats(self, workspace: str, *, notes: list[Note] | None = None) -> dict[str, object]:
        """Workspace counts with no note bodies, for `jotline stats` and scripts."""
        snapshot = self.notes() if notes is None else notes
        found = self.search(workspace=workspace, notes=snapshot)
        inbox = self.search(collection="inbox", workspace=workspace, notes=snapshot)
        captures = self.inbox_captures(workspace, notes=snapshot)
        return {
            "workspace": workspace,
            "notes": len(found),
            "inbox": len(inbox),
            "inbox_captures": len(captures),
            "daily_logs": sum(is_daily_id(note.id) for note in found),
            "open_tasks": len(gather(found)),
            "tagged": sum(bool(note.tags) for note in found),
            "starred": sum(note.starred for note in found),
        }

    def tags(self, workspace: str, *, notes: list[Note] | None = None) -> Counter:
        result = Counter()
        snapshot = self.notes() if notes is None else notes
        for note in self.search(workspace=workspace, notes=snapshot):
            result.update(note.tags)
            self._collect_derived_warnings(note)
        return result

    def _collect_derived_warnings(self, note: Note) -> None:
        for warning in note.derived_warnings:
            message = f"{note.id}.md: {warning}"
            if message not in self.warnings:
                self.warnings.append(message)

    def workspaces(self, *, notes: list[Note] | None = None) -> set[str]:
        snapshot = self.notes() if notes is None else notes
        return {"default", *(note.workspace for note in snapshot)}

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
        already = "Encryption is already set up for this vault; change its passphrase instead"
        if self.has_key():
            raise ValueError(already)
        note_key = new_note_key()
        key = KeyFile.create(passphrase, note_key, n=n or SCRYPT_N)
        with self.write_lock() as directory:
            try:
                # Never replace an existing key: notes sealed with it would become unreadable.
                self._write_key(directory, key, replace_existing=False)
            except FileExistsError:
                raise ValueError(already) from None
        self.cipher = NoteCipher(note_key)
        self.invalidate_cache()

    def change_passphrase(self, old: str, new: str, *, n: int | None = None) -> None:
        """Rewrap the note key; encrypted notes themselves are not rewritten."""
        with self.write_lock() as directory:
            current = self._read_key(directory)
            note_key = current.unwrap(old)
            # The current work factor, not the file's: this is the one time a
            # vault set up with a weaker n gets stronger, and its key ID is written.
            self._write_key(directory, KeyFile.create(new, note_key, n=n or SCRYPT_N), replace_existing=True)

    def set_encrypted(self, note_id: str, workspace: str, encrypted: bool) -> tuple[Note, bool]:
        """Encrypt or decrypt one note; returns the note and whether anything changed."""
        with self.write_lock() as directory:
            note = self.read(note_id, workspace=workspace, directory=directory)
            if note.locked or (encrypted and self.cipher is None):
                raise ValueError(LOCKED)
            if note.encrypted == encrypted:
                if encrypted:
                    from .outline_state import STATE_FILE, remove_state_locked
                    remove_state_locked(self.path / STATE_FILE, note.id, directory)
                return note, False
            note.encrypted = encrypted
            self._save_locked(note, directory)
            return note, True

    def update_body(self, note_id: str, workspace: str, change) -> Note:
        """Replace a note's text with change(text) under one lock."""
        with self.write_lock() as directory:
            note = self.read(note_id, workspace=workspace, directory=directory)
            if note.locked:
                raise ValueError(LOCKED)
            note.body = change(note.body)
            self._save_locked(note, directory)
            return note

    def recoveries(self, *, notes: list[Note] | None = None) -> list[Note]:
        """Inbox copies saved after an external change or a manual recovery."""
        snapshot = self.notes() if notes is None else notes
        return [note for note in snapshot if note.recovery_of]

    def recovery(self, note: Note) -> Note:
        if note.locked:
            raise ValueError(LOCKED)
        recovered = replace(note, id=uuid4().hex, original=None, created=now(), collection="inbox",
                            recovery_of=note.recovery_of or note.id)
        self.save(recovered)
        return recovered


from . import history  # noqa: E402  — after Vault; history imports validate_note_id from this module
