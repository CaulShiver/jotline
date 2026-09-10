"""Portable Markdown storage with atomic writes and optimistic concurrency."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, date
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from uuid import uuid4

COLLECTIONS = ("inbox", "projects", "areas", "resources", "archive", "trash")
# Limits protect the interactive app from accidentally imported huge files.
MAX_NOTE_BYTES = 10 * 1024 * 1024
MAX_SETTINGS_BYTES = 256 * 1024
LOCK_TIMEOUT_SECONDS = 1.0
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_CACHED_NOTES = 2048

FileSignature = tuple[int, int, int, int, int]

LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]*)?\]\]")
TAG = re.compile(r"(?<![\w#])#([\w][\w/-]*)", re.UNICODE)


class ConflictError(OSError):
    """An external edit must be resolved before overwriting a note."""


def read_regular_file(path: Path, max_bytes: int = MAX_NOTE_BYTES) -> str:
    """Read bounded UTF-8 text without following links or blocking on a pipe."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"Not a regular file: {path.name}")
        if info.st_size > max_bytes:
            raise ValueError(f"{path.name} exceeds the {max_bytes}-byte file limit")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError(f"{path.name} exceeds the {max_bytes}-byte file limit")
        return raw.decode("utf-8")
    finally:
        os.close(fd)


@contextmanager
def vault_lock(path: Path):
    """Coordinate local writers without hanging the UI indefinitely."""
    fd = os.open(path / ".jotline.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("Jotline lock is not a regular file")
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OSError("Vault is busy in another process; try saving again") from None
                time.sleep(0.025)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def file_signature(path: Path) -> FileSignature:
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

    @property
    def title(self) -> str:
        title = next((line.lstrip("# ").strip() for line in self.body.splitlines() if line.strip()), "")
        return title[:100] or "Untitled"

    @property
    def tags(self) -> set[str]:
        return {tag.casefold() for tag in TAG.findall(self.body)}

    @property
    def links(self) -> set[str]:
        return set(LINK.findall(self.body))


class Vault:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        self.warnings: list[str] = []
        self._cache: dict[str, tuple[FileSignature, Note, int]] = {}

    def locked(self):
        return vault_lock(self.path)

    def file(self, note_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", note_id):
            raise ValueError("Invalid note ID")
        return self.path / f"{note_id}.md"

    def new(self, body: str = "") -> Note:
        stamp = now()
        return Note(uuid4().hex, body, created=stamp, updated=stamp)

    def read(self, note_id: str) -> Note:
        raw = read_regular_file(self.file(note_id))
        meta = {}
        body = raw
        if re.match(r"\A---\r?\njotline: 1\r?\n", raw):
            boundary = re.search(r"\r?\n---\r?\n", raw)
            if boundary is None:
                raise ValueError("Incomplete Jotline metadata header")
            header = raw[raw.index("\n") + 1:boundary.start()]
            for line in header.splitlines():
                key, sep, value = line.partition(": ")
                if sep and key in {"collection", "created", "updated", "starred"}:
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
        return Note(note_id, body, original=raw, **meta)

    def invalidate_cache(self) -> None:
        """Force the next scan to reread note bodies from disk."""
        self._cache.clear()

    def notes(self) -> list[Note]:
        notes = []
        self.warnings = []
        refreshed = {}
        retained_bytes = 0
        for file in self.path.glob("*.md"):
            try:
                signature = file_signature(file)
                cached = self._cache.get(file.stem)
                cache_hit = cached is not None and cached[0] == signature
                if cache_hit:
                    note, cost = cached[1:]
                else:
                    note = self.read(file.stem)
                    # Include both body and original snapshot plus a conservative
                    # allowance for the small cache entry and note attributes.
                    cost = sum(sys.getsizeof(value) for value in vars(note).values()) + 1024
                notes.append(replace(note))
                # A file changed during reading is still a valid snapshot, but
                # must be read afresh next time. Never cache it under a stale stat.
                if (len(refreshed) < MAX_CACHED_NOTES and retained_bytes + cost <= MAX_CACHE_BYTES
                        and (cache_hit or file_signature(file) == signature)):
                    refreshed[file.stem] = (signature, note, cost)
                    retained_bytes += cost
            except (ValueError, OSError) as error:
                self.warnings.append(f"{file.name}: {error}")
        self._cache = refreshed
        return sorted(notes, key=lambda n: (n.starred, n.updated, n.id), reverse=True)

    def save(self, note: Note) -> None:
        with self.locked():
            self._save_locked(note)

    def _save_locked(self, note: Note) -> None:
        if note.collection not in COLLECTIONS:
            raise ValueError("Unknown collection")
        if not isinstance(note.body, str) or not isinstance(note.starred, bool):
            raise ValueError("Invalid note body or starred value")
        if not all(isinstance(value, str) for value in (note.created, note.updated)):
            raise ValueError("Invalid timestamps")
        path = self.file(note.id)
        try:
            actual = read_regular_file(path)
        except FileNotFoundError:
            actual = None
        if actual != note.original:
            raise ConflictError("This note changed outside Jotline. Save a recovery copy to preserve your changes.")
        stamp = now()
        meta = {"collection": note.collection, "created": note.created or stamp,
                "updated": stamp, "starred": note.starred}
        raw = "---\njotline: 1\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in meta.items()) + "\n---\n" + note.body
        if len(raw.encode("utf-8")) > MAX_NOTE_BYTES:
            raise ValueError(f"Note exceeds the {MAX_NOTE_BYTES}-byte file limit")
        fd, temp = tempfile.mkstemp(prefix=".jotline-", dir=self.path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            # Replacement has committed even if the directory durability check fails.
            # Keep the baseline current so retrying does not invent an edit conflict.
            note.original, note.updated, note.created = raw, stamp, meta["created"]
            self._cache.pop(note.id, None)
            directory = os.open(self.path, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def daily(self, template: str = "# {{date}}\n\n") -> Note:
        with self.locked():
            return self._daily_locked(template)

    def _daily_locked(self, template: str) -> Note:
        today = date.today().isoformat()
        note_id = f"daily-{today}"
        try:
            return self.read(note_id)
        except FileNotFoundError:
            stamp = now()
            return Note(note_id, template.replace("{{date}}", today), "inbox", stamp, stamp)

    def append_daily(self, body: str, template: str = "# {{date}}\n\n") -> Note:
        """Append a shell capture atomically with respect to other Jotline writers."""
        with self.locked():
            note = self._daily_locked(template)
            note.body = note.body.rstrip() + "\n\n" + body + "\n"
            self._save_locked(note)
            return note

    def backlinks(self, target: Note) -> list[Note]:
        targets = {target.id, target.title}
        return [n for n in self.notes() if n.id != target.id and n.collection != "trash"
                and targets.intersection(n.links)]

    def search(self, query: str = "", collection: str = "all") -> list[Note]:
        terms = query.casefold().split()
        words = [t for t in terms if not t.startswith("#")]
        tags = {t[1:] for t in terms if t.startswith("#")}
        matches = []
        for note in self.notes():
            if collection == "all":
                included = note.collection != "trash"
            elif collection == "starred":
                included = note.starred and note.collection != "trash"
            else:
                included = note.collection == collection
            if not included or (tags and not tags.issubset(note.tags)):
                continue
            body = note.body.casefold() if words else ""
            if all(word in body or word in note.id for word in words):
                matches.append(note)
        return matches

    def recovery(self, note: Note) -> Note:
        recovered = replace(note, id=uuid4().hex, original=None, created=now(), collection="inbox")
        self.save(recovered)
        return recovered
