"""Bounded local revisions and portable ZIP backups; callers hold the vault lock."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from uuid import uuid4
import zipfile

from .store import MAX_SETTINGS_BYTES, read_regular_file

HISTORY_LIMIT = 30
BACKUP_LIMIT = 7
REVISION_ID = re.compile(r"[0-9]{8}T[0-9]{12}-[0-9a-f]{8}")
BACKUP_NAME = re.compile(r"(?:daily-[0-9]{4}-[0-9]{2}-[0-9]{2}|manual-[0-9]{8}T[0-9]{12}-[0-9a-f]{8})\.zip")


@dataclass(frozen=True)
class Revision:
    id: str
    saved_at: str


def stamp() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S%f") + "-" + uuid4().hex[:8]


def directory(path: Path, *, create: bool = True) -> Path:
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise OSError(f"Not a safe directory: {path.name}")
    return path


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def revision_dir(vault, note_id: str, *, create: bool = True) -> Path:
    vault.file(note_id)  # Validate before joining any path.
    return directory(directory(vault.path / ".jotline-history", create=create) / note_id, create=create)


def revisions(vault, note_id: str) -> list[Revision]:
    try:
        folder = revision_dir(vault, note_id, create=False)
    except FileNotFoundError:
        return []
    result = []
    for path in folder.glob("*.md"):
        if REVISION_ID.fullmatch(path.stem) and stat.S_ISREG(path.lstat().st_mode):
            try:
                when = datetime.strptime(path.stem.split("-")[0], "%Y%m%dT%H%M%S%f")
            except ValueError:
                continue
            result.append(Revision(path.stem, when.isoformat(timespec="seconds")))
    return sorted(result, key=lambda rev: rev.id, reverse=True)


def snapshot(vault, note_id: str, raw: str) -> Path | None:
    folder = revision_dir(vault, note_id)
    existing = revisions(vault, note_id)
    if existing and read_regular_file(folder / f"{existing[0].id}.md") == raw:
        return None
    target = folder / f"{stamp()}.md"
    fd, temp = tempfile.mkstemp(prefix=".revision-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
        sync_directory(folder)
        sync_directory(folder.parent)
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        Path(temp).unlink(missing_ok=True)


def prune_history(vault, note_id: str) -> None:
    entries = revisions(vault, note_id)
    # Keep minute checkpoints plus two latest saves, including the version
    # immediately before an accidental destructive edit.
    first_per_minute = {}
    for entry in reversed(entries):
        first_per_minute.setdefault(entry.id[:13], entry.id)
    keep = set(sorted(first_per_minute.values(), reverse=True)[:HISTORY_LIMIT])
    keep.update(entry.id for entry in entries[:2])
    for entry in entries:
        if entry.id not in keep:
            (revision_dir(vault, note_id) / f"{entry.id}.md").unlink()


def backup(vault, *, automatic: bool = False) -> Path:
    folder = directory(vault.path / ".jotline-backups")
    name = f"daily-{date.today().isoformat()}.zip" if automatic else f"manual-{stamp()}.zip"
    target = folder / name
    if automatic and (target.exists() or target.is_symlink()):
        if not stat.S_ISREG(target.lstat().st_mode):
            raise OSError("Daily backup is not a regular file")
        return target
    sources = [(path, path.name, None) for path in sorted(vault.path.glob("*.md"))]
    settings = vault.path / ".jotline-settings.json"
    if settings.exists() or settings.is_symlink():
        sources.append((settings, settings.name, MAX_SETTINGS_BYTES))
    skipped = []
    templates = vault.path / ".jotline-templates"
    if templates.exists() or templates.is_symlink():
        try:
            directory(templates, create=False)
            sources.extend((path, f".jotline-templates/{path.name}", None) for path in sorted(templates.glob("*.md")))
        except OSError as error:
            skipped.append({"path": templates.name, "reason": str(error)})
    fd, temp = tempfile.mkstemp(prefix=".backup-", dir=folder)
    try:
        with os.fdopen(fd, "w+b") as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path, name, limit in sources:
                    try:
                        raw = read_regular_file(path, limit) if limit else read_regular_file(path)
                    except (OSError, ValueError) as error:
                        skipped.append({"path": name, "reason": str(error)})
                        continue
                    archive.writestr(name, raw.encode("utf-8"))
                archive.writestr("jotline-backup-manifest.json", json.dumps({
                    "created": datetime.now().astimezone().isoformat(), "skipped": skipped,
                    "scope": "Root Markdown notes, settings, and Markdown templates; excludes history and other backups",
                }, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
        sync_directory(folder)
    finally:
        Path(temp).unlink(missing_ok=True)
    vault.backup_warning = (f"Backup skipped {len(skipped)} unsafe or unreadable entries; see its manifest"
                            if skipped else "")
    if vault.backup_warning:
        vault.warnings.append(vault.backup_warning)
    archives = sorted((path for path in folder.iterdir() if BACKUP_NAME.fullmatch(path.name)
                       and stat.S_ISREG(path.lstat().st_mode)), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    # Today's automatic backup remains the once-per-day marker even after many manual backups.
    today = f"daily-{date.today().isoformat()}.zip"
    keep = {target, *(path for path in archives if path.name == today)}
    for path in archives:
        if len(keep) < BACKUP_LIMIT:
            keep.add(path)
        if path not in keep:
            path.unlink()
    return target
