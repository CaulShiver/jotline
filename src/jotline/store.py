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
import tempfile
from uuid import uuid4

COLLECTIONS = ("inbox", "projects", "areas", "resources", "archive", "trash")
LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
TAG = re.compile(r"(?<![\w#])#([\w][\w/-]*)", re.UNICODE)


class ConflictError(OSError):
    """An external edit must be resolved before overwriting a note."""


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

    @property
    def title(self) -> str:
        return next((line.lstrip("# ").strip() for line in self.body.splitlines() if line.strip()), "Untitled")[:100]

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

    @contextmanager
    def locked(self):
        with (self.path / ".jotline.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def file(self, note_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", note_id):
            raise ValueError("Invalid note ID")
        return self.path / f"{note_id}.md"

    def new(self, body: str = "") -> Note:
        stamp = now()
        return Note(uuid4().hex, body, created=stamp, updated=stamp)

    def read(self, note_id: str) -> Note:
        raw = self.file(note_id).read_text(encoding="utf-8")
        meta = {}
        body = raw
        if raw.startswith("---\njotline: 1\n"):
            header, separator, remainder = raw[4:].partition("\n---\n")
            if separator:
                for line in header.splitlines():
                    key, sep, value = line.partition(": ")
                    if sep and key in {"collection", "created", "updated", "starred"}:
                        meta[key] = json.loads(value)
                body = remainder
        if meta.get("collection", "inbox") not in COLLECTIONS:
            raise ValueError("Unknown collection")
        if any(not isinstance(meta.get(k, ""), str) for k in ("created", "updated")):
            raise ValueError("Invalid timestamps")
        if not isinstance(meta.get("starred", False), bool):
            raise ValueError("Invalid starred value")
        return Note(note_id, body, original=raw, **meta)

    def notes(self) -> list[Note]:
        notes = []
        self.warnings = []
        for file in self.path.glob("*.md"):
            try:
                notes.append(self.read(file.stem))
            except (ValueError, OSError) as error:
                self.warnings.append(f"{file.name}: {error}")
        return sorted(notes, key=lambda n: (n.starred, n.updated, n.id), reverse=True)

    def save(self, note: Note) -> None:
        if note.collection not in COLLECTIONS:
            raise ValueError("Unknown collection")
        path = self.file(note.id)
        with self.locked():
            actual = path.read_text(encoding="utf-8") if path.exists() else None
            if actual != note.original:
                raise ConflictError("This note changed outside Jotline. Your text is still in the editor; use 'Save recovery copy'.")
            stamp = now()
            meta = {"collection": note.collection, "created": note.created or stamp,
                    "updated": stamp, "starred": note.starred}
            raw = "---\njotline: 1\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in meta.items()) + "\n---\n" + note.body
            fd, temp = tempfile.mkstemp(prefix=".jotline-", dir=self.path)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, path)
                directory = os.open(self.path, os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            note.original, note.updated, note.created = raw, stamp, meta["created"]

    def daily(self, template: str = "# {{date}}\n\n") -> Note:
        note_id = f"daily-{date.today().isoformat()}"
        with self.locked():
            # Return an unsaved note; save() protects concurrent creation.
            if self.file(note_id).exists():
                return self.read(note_id)
            stamp = now()
            return Note(note_id, template.replace("{{date}}", date.today().isoformat()), "inbox", stamp, stamp)

    def backlinks(self, target: Note) -> list[Note]:
        return [n for n in self.notes() if n.id != target.id and n.collection != "trash"
                and (target.id in n.links or target.title in n.links)]

    def search(self, query: str = "", collection: str = "all") -> list[Note]:
        terms = query.casefold().split()
        return [n for n in self.notes()
                if (n.collection != "trash" if collection == "all" else
                    n.starred and n.collection != "trash" if collection == "starred" else
                    n.collection == collection)
                and all(t[1:] in n.tags if t.startswith("#") else t in n.body.casefold() or t in n.id
                        for t in terms)]

    def recovery(self, note: Note) -> Note:
        recovered = replace(note, id=uuid4().hex, original=None, created=now(), collection="inbox")
        self.save(recovered)
        return recovered
