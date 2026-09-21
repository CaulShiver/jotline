"""Bounded local revisions and portable ZIP backups; callers hold the vault lock."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, date
import json
from pathlib import Path
import re
import stat
import time
from uuid import uuid4
import zipfile

from .filesystem import create_private_temp, fs as os, read_regular_at, replace_at, unlink_quietly
from .limits import MAX_NOTE_BYTES, MAX_SETTINGS_BYTES
from .store import validate_note_id

HISTORY_LIMIT = 30
BACKUP_LIMIT = 7
MAX_HISTORY_ENTRIES = 4096
MAX_BACKUP_ENTRIES = 10_000
MAX_BACKUP_BYTES = 256 * 1024 * 1024
# A manifest Jotline wrote lists at most two scan budgets of skipped paths, a
# few megabytes at the outside. An entry's declared size is whatever the file
# says, so the cap is on the bytes actually inflated.
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
REVISION_ID = re.compile(r"[0-9]{8}T[0-9]{12}-[0-9a-f]{8}")
# Every create_private_temp caller uses one of these prefixes, followed by a uuid4 hex.
TEMP_PREFIXES = ("jotline", "backup", "revision", "settings", "action-history", "tmp", "recipe")
STALE_TEMP = re.compile(r"\.(?:" + "|".join(TEMP_PREFIXES) + r")-[0-9a-f]{32}")
STALE_TEMP_SECONDS = 3600
BACKUP_NAME = re.compile(r"(?:daily-[0-9]{4}-[0-9]{2}-[0-9]{2}|manual-[0-9]{8}T[0-9]{12}-[0-9a-f]{8})\.zip")
QUARANTINE_NAME = re.compile(r"\.invalid-[0-9]{8}T[0-9]{12}-[0-9a-f]{8}\.zip")
DISPLACED_PREFIX = ".jotline-displaced-"
STALE_BACKUP_SECONDS = 2 * 24 * 3600


@dataclass(frozen=True)
class Revision:
    id: str
    saved_at: str


@dataclass(frozen=True)
class BackupArchive:
    name: str
    path: Path
    size: int
    modified: float
    valid: bool
    reason: str


def stamp() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S%f") + "-" + uuid4().hex[:8]


def prune_stale_temps(directory: int) -> int:
    """Remove private temp files left by a crash mid-write; they are never live data."""
    removed = 0
    cutoff = time.time() - STALE_TEMP_SECONDS
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_BACKUP_ENTRIES:
                break
            if not STALE_TEMP.fullmatch(entry.name):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and info.st_mtime < cutoff:
                    os.unlink(entry.name, dir_fd=directory)
                    removed += 1
            except OSError:
                continue
    return removed


def sync_directory(path_or_fd: Path | int) -> None:
    own = not isinstance(path_or_fd, int)
    fd = os.open(path_or_fd, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if own else os.dup(path_or_fd)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _vault_directory(vault, existing: int | None = None):
    fd = os.dup(existing) if existing is not None else os.open(
        vault.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _managed_directory(parent: int, name: str, *, create: bool):
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
            sync_directory(parent)
        except FileExistsError:
            pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _revision_directory(vault, note_id: str, *, create: bool, vault_directory: int | None = None):
    validate_note_id(note_id)
    with _vault_directory(vault, vault_directory) as root:
        with _managed_directory(root, ".jotline-history", create=create) as history:
            with _managed_directory(history, note_id, create=create) as note:
                yield history, note


def _stat_entry(entry: os.DirEntry) -> os.stat_result | None:
    try:
        return entry.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None  # Removed by another writer between listing and stat.


def _revisions_at(vault, note_id: str, folder: int) -> list[Revision]:
    result = []
    with os.scandir(folder) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_HISTORY_ENTRIES:
                vault.warnings.append(
                    f"History {note_id} stopped after {MAX_HISTORY_ENTRIES} entries; results are incomplete")
                break
            stem = entry.name[:-3] if entry.name.endswith(".md") else ""
            if not REVISION_ID.fullmatch(stem):
                continue
            info = _stat_entry(entry)
            if info is None or not stat.S_ISREG(info.st_mode):
                continue
            try:
                when = datetime.strptime(stem.split("-")[0], "%Y%m%dT%H%M%S%f")
            except ValueError:
                continue
            result.append((info.st_mtime_ns, Revision(stem, when.isoformat(timespec="seconds"))))
    # Wall-clock stamps can step backwards; the file's own write time orders
    # revisions reliably and the ID only breaks ties.
    return [revision for _, revision in sorted(result, key=lambda item: (item[0], item[1].id), reverse=True)]


def revisions(vault, note_id: str, *, vault_directory: int | None = None) -> list[Revision]:
    try:
        with _revision_directory(vault, note_id, create=False, vault_directory=vault_directory) as (_, folder):
            return _revisions_at(vault, note_id, folder)
    except FileNotFoundError:
        return []


def snapshot(vault, note_id: str, raw: str, *, vault_directory: int | None = None) -> Path | None:
    with _revision_directory(vault, note_id, create=True, vault_directory=vault_directory) as (history, folder):
        for entry in _revisions_at(vault, note_id, folder):
            try:
                latest = read_regular_at(folder, f"{entry.id}.md")
            except (OSError, ValueError) as error:
                vault.warnings.append(f"History {note_id}/{entry.id}: {error}; skipped corrupt revision")
                continue
            if latest == raw:
                return None
            break
        name = f"{stamp()}.md"
        fd, temporary = create_private_temp(folder, ".revision-")
        published = False
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            replace_at(folder, temporary, name)
            published = True
            sync_directory(folder)
            sync_directory(history)
            return vault.path / ".jotline-history" / note_id / name
        except BaseException:
            if published:
                unlink_quietly(folder, name)
            raise
        finally:
            unlink_quietly(folder, temporary)


def prune_history(vault, note_id: str, *, vault_directory: int | None = None) -> None:
    try:
        with _revision_directory(vault, note_id, create=False, vault_directory=vault_directory) as (_, folder):
            entries = _revisions_at(vault, note_id, folder)
            # _revisions_at orders by the file's own write time; hold on to that
            # order. Ranking the survivors by the wall-clock stamp inside the ID
            # instead means a clock that steps backwards -- DST ending, an NTP
            # correction, a VM resumed from a snapshot -- sorts the newest
            # revisions below the old ones, so the work just done is what gets
            # deleted and the stale revisions are what is kept.
            newest_first = {entry.id: index for index, entry in enumerate(entries)}
            first_per_minute = {}
            for entry in reversed(entries):
                first_per_minute.setdefault(entry.id[:13], entry.id)
            keep = set(sorted(first_per_minute.values(),
                              key=lambda revision: newest_first[revision])[:HISTORY_LIMIT])
            keep.update(entry.id for entry in entries[:2])
            for entry in entries:
                if entry.id not in keep:
                    os.unlink(f"{entry.id}.md", dir_fd=folder)
            # prune_stale_temps only ever ran over the vault root and the
            # backups folder, so a temp in here was never anyone's to collect.
            cutoff = time.time() - STALE_TEMP_SECONDS
            with os.scandir(folder) as leftovers:
                for index, entry in enumerate(leftovers):
                    if index >= MAX_HISTORY_ENTRIES:
                        break
                    if not STALE_TEMP.fullmatch(entry.name):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISREG(info.st_mode) and info.st_mtime < cutoff:
                            os.unlink(entry.name, dir_fd=folder)
                    except OSError:
                        continue
            sync_directory(folder)
    except FileNotFoundError:
        pass


def remove_revision(vault, note_id: str, revision_id: str, *, vault_directory: int | None = None) -> None:
    if not REVISION_ID.fullmatch(revision_id):
        raise ValueError("Invalid revision ID")
    try:
        with _revision_directory(vault, note_id, create=False, vault_directory=vault_directory) as (_, folder):
            os.unlink(f"{revision_id}.md", dir_fd=folder)
            sync_directory(folder)
    except FileNotFoundError:
        pass


def _remove_revision_temps(folder: int) -> int:
    """Remove partly written revisions from a note's history folder."""
    removed = 0
    with os.scandir(folder) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_HISTORY_ENTRIES:
                break
            if not STALE_TEMP.fullmatch(entry.name):
                continue
            try:
                os.unlink(entry.name, dir_fd=folder)
                removed += 1
            except OSError:
                continue
    return removed


def remove_unencrypted_revisions(vault, note_id: str, is_encrypted, *, vault_directory: int | None = None) -> int:
    """Delete saved versions of a note that could hold its text unencrypted."""
    removed = 0
    try:
        with _revision_directory(vault, note_id, create=False, vault_directory=vault_directory) as (_, folder):
            for entry in _revisions_at(vault, note_id, folder):
                try:
                    keep = is_encrypted(read_regular_at(folder, f"{entry.id}.md"))
                except (OSError, ValueError):
                    keep = False
                if not keep:
                    os.unlink(f"{entry.id}.md", dir_fd=folder)
                    removed += 1
            # A crash during a revision write leaves a .revision-* temp holding
            # the whole note in the clear. It has no revision ID, so the loop
            # above never sees it, and until now nothing else removed it either.
            removed += _remove_revision_temps(folder)
            sync_directory(folder)
    except FileNotFoundError:
        pass
    return removed


def read_revision_raw(vault, note_id: str, revision_id: str, *, vault_directory: int | None = None) -> str:
    if not REVISION_ID.fullmatch(revision_id):
        raise ValueError("Invalid revision ID")
    with _revision_directory(vault, note_id, create=False, vault_directory=vault_directory) as (_, folder):
        return read_regular_at(folder, f"{revision_id}.md")


def history_note_ids(vault, *, vault_directory: int | None = None) -> list[str]:
    try:
        with _vault_directory(vault, vault_directory) as root:
            with _managed_directory(root, ".jotline-history", create=False) as history:
                result = []
                with os.scandir(history) as entries:
                    for index, entry in enumerate(entries):
                        if index >= MAX_HISTORY_ENTRIES:
                            vault.warnings.append(
                                f"History scan stopped after {MAX_HISTORY_ENTRIES} entries; results are incomplete")
                            break
                        try:
                            validate_note_id(entry.name)
                            if stat.S_ISDIR(entry.stat(follow_symlinks=False).st_mode):
                                result.append(entry.name)
                        except (OSError, ValueError):
                            pass
                return result
    except FileNotFoundError:
        return []


def _validate_archive(stream, *, require_content: bool) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_BACKUP_ENTRIES:
                return False, "archive has an invalid entry count"
            names = {entry.filename for entry in entries}
            if len(names) != len(entries):
                return False, "archive contains duplicate names"
            if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
                return False, "archive contains an unsafe member name"
            if require_content and names == {"jotline-backup-manifest.json"}:
                return False, "archive contains only a manifest"
            if "jotline-backup-manifest.json" not in names:
                return False, "manifest is missing"
            if sum(entry.file_size for entry in entries) > MAX_BACKUP_BYTES:
                return False, "archive contents exceed validation limit"
            consumed = 0
            manifest = None
            for entry in entries:
                captured = bytearray() if entry.filename == "jotline-backup-manifest.json" else None
                with archive.open(entry) as member:
                    while chunk := member.read(min(64 * 1024, MAX_BACKUP_BYTES - consumed + 1)):
                        consumed += len(chunk)
                        if consumed > MAX_BACKUP_BYTES:
                            return False, "archive contents exceed validation limit"
                        if captured is not None:
                            if len(captured) + len(chunk) > MAX_MANIFEST_BYTES:
                                return False, "manifest exceeds validation limit"
                            captured.extend(chunk)
                if captured is not None:
                    manifest = json.loads(bytes(captured))
            if (not isinstance(manifest, dict) or not isinstance(manifest.get("created"), str)
                    or not isinstance(manifest.get("skipped"), list)
                    or not isinstance(manifest.get("scope"), str)):
                return False, "manifest is structurally incomplete"
        return True, ""
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile, RuntimeError) as error:
        return False, str(error)


def _validate_backup_at(directory_fd: int | None, name: str | Path, *,
                        require_content: bool = True) -> tuple[bool, str]:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except OSError as error:
        return False, str(error)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return False, "not a regular file"
        if info.st_size > MAX_BACKUP_BYTES:
            return False, "archive exceeds validation limit"
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return _validate_archive(stream, require_content=require_content)
    finally:
        os.close(fd)


def validate_backup(path: Path) -> tuple[bool, str]:
    return _validate_backup_at(None, path, require_content=path.name.startswith("daily-"))


def list_archives(vault) -> list[BackupArchive]:
    """Named ZIP backups with validation results. Missing folders yield an empty list."""
    root = vault.path / ".jotline-backups"
    archives = []
    try:
        entries = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError:
        return archives
    for index, path in enumerate(entries):
        if index >= MAX_BACKUP_ENTRIES:
            vault.warnings.append(
                f"Backup listing stopped after {MAX_BACKUP_ENTRIES} entries; results are incomplete")
            break
        if not BACKUP_NAME.fullmatch(path.name):
            continue
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            valid, reason = validate_backup(path)
            archives.append(BackupArchive(path.name, path, info.st_size, info.st_mtime, valid, reason))
        except OSError as error:
            archives.append(BackupArchive(path.name, path, 0, 0.0, False, str(error)))
    archives.sort(key=lambda archive: archive.modified, reverse=True)
    return archives


def newest_valid_archive(archives: list[BackupArchive]) -> BackupArchive | None:
    return next((archive for archive in archives if archive.valid), None)


def _reuse_daily_backup(vault, folder: int, name: str) -> bool:
    """True when today's automatic backup already exists and validates.

    An invalid archive is set aside so a fresh one can be written.
    """
    try:
        target_info = os.stat(name, dir_fd=folder, follow_symlinks=False)
    except FileNotFoundError:
        return False
    # Inflating the whole archive on every save is expensive; the
    # result is stable while the file's identity and size are.
    key = (target_info.st_ino, target_info.st_size, target_info.st_mtime_ns)
    validated = getattr(vault, "_validated_backups", None)
    if validated is None:
        validated = vault._validated_backups = {}
    if validated.get(name) == key:
        return True
    valid, reason = _validate_backup_at(folder, name)
    if valid:
        validated[name] = key
        return True
    if not stat.S_ISREG(target_info.st_mode):
        raise OSError("Daily backup is not a regular file")
    quarantine = f".invalid-{stamp()}.zip"
    replace_at(folder, name, quarantine)
    sync_directory(folder)
    message = f"Invalid daily backup retained as {quarantine} ({reason}); created a replacement"
    vault.backup_warning = message
    vault.warnings.append(message)
    return False


def _prune_backups(vault, folder: int, keep_name: str) -> None:
    """Keep the newest BACKUP_LIMIT archives, always including today's and the one just written,
    and the newest BACKUP_LIMIT quarantined ones."""
    archives = []
    quarantined = []
    with os.scandir(folder) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_BACKUP_ENTRIES:
                vault.warnings.append(f"Backup retention stopped after {MAX_BACKUP_ENTRIES} entries")
                break
            info = _stat_entry(entry)
            if info is None or not stat.S_ISREG(info.st_mode):
                continue
            if BACKUP_NAME.fullmatch(entry.name):
                archives.append((info.st_mtime_ns, entry.name))
            elif QUARANTINE_NAME.fullmatch(entry.name):
                quarantined.append((info.st_mtime_ns, entry.name))
    archives.sort(reverse=True)
    today = f"daily-{date.today().isoformat()}.zip"
    keep = {keep_name, *(archive_name for _, archive_name in archives if archive_name == today)}
    for _, archive_name in archives:
        if len(keep) < BACKUP_LIMIT:
            keep.add(archive_name)
        if archive_name not in keep:
            os.unlink(archive_name, dir_fd=folder)
    for _, quarantine_name in sorted(quarantined, reverse=True)[BACKUP_LIMIT:]:
        os.unlink(quarantine_name, dir_fd=folder)
    sync_directory(folder)


def backup(vault, *, automatic: bool = False, vault_directory: int | None = None,
           pending: tuple[str, str] | None = None) -> Path:
    with _vault_directory(vault, vault_directory) as root:
        with _managed_directory(root, ".jotline-backups", create=True) as folder:
            name = f"daily-{date.today().isoformat()}.zip" if automatic else f"manual-{stamp()}.zip"
            target = vault.path / ".jotline-backups" / name
            if automatic and _reuse_daily_backup(vault, folder, name):
                return target

            for stale in (root, folder):
                try:
                    prune_stale_temps(stale)
                except OSError:
                    pass
            sources: list[tuple[int, str, str, int]] = []
            skipped = []
            source_bytes = 0

            def add_source(source_fd: int, source_name: str, archive_name: str, limit: int) -> None:
                nonlocal source_bytes
                if len(sources) >= MAX_BACKUP_ENTRIES - 1:
                    skipped.append({"path": archive_name, "reason": "backup entry budget reached"})
                    return
                try:
                    info = os.stat(source_name, dir_fd=source_fd, follow_symlinks=False)
                except OSError as error:
                    skipped.append({"path": archive_name, "reason": str(error)})
                    return
                if source_bytes + info.st_size > MAX_BACKUP_BYTES:
                    skipped.append({"path": archive_name, "reason": "backup byte budget reached"})
                    return
                source_bytes += info.st_size
                sources.append((source_fd, source_name, archive_name, limit))

            pending_name = pending[0] if pending else None
            with os.scandir(root) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_BACKUP_ENTRIES:
                        skipped.append({"path": "vault", "reason": "backup scan budget reached"})
                        break
                    if entry.name.endswith(".md") and entry.name != pending_name:
                        add_source(root, entry.name, entry.name, MAX_NOTE_BYTES)
            if pending is not None:
                pending_size = len(pending[1].encode("utf-8"))
                if source_bytes + pending_size <= MAX_BACKUP_BYTES and len(sources) < MAX_BACKUP_ENTRIES - 1:
                    source_bytes += pending_size
                else:
                    skipped.append({"path": pending[0], "reason": "backup byte or entry budget reached"})
                    pending = None
            try:
                os.stat(".jotline-settings.json", dir_fd=root, follow_symlinks=False)
                add_source(root, ".jotline-settings.json", ".jotline-settings.json", MAX_SETTINGS_BYTES)
            except FileNotFoundError:
                pass
            try:
                # Encrypted notes are unreadable without it; it holds only the passphrase-wrapped key.
                os.stat(".jotline-key.json", dir_fd=root, follow_symlinks=False)
                add_source(root, ".jotline-key.json", ".jotline-key.json", MAX_SETTINGS_BYTES)
            except FileNotFoundError:
                pass

            template_fd = None
            try:
                template_fd = os.open(".jotline-templates", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                      dir_fd=root)
                with os.scandir(template_fd) as entries:
                    for index, entry in enumerate(entries):
                        if index >= MAX_BACKUP_ENTRIES:
                            skipped.append({"path": ".jotline-templates", "reason": "backup scan budget reached"})
                            break
                        if entry.name.endswith(".md"):
                            add_source(template_fd, entry.name, f".jotline-templates/{entry.name}", MAX_NOTE_BYTES)
            except FileNotFoundError:
                pass
            except OSError as error:
                skipped.append({"path": ".jotline-templates", "reason": str(error)})

            try:
                fd, temporary = create_private_temp(folder, ".backup-")
            except BaseException:
                if template_fd is not None:
                    os.close(template_fd)
                raise
            try:
                with os.fdopen(fd, "w+b") as stream:
                    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        written_bytes = 0
                        for source_fd, source_name, archive_name, limit in sources:
                            try:
                                raw = read_regular_at(source_fd, source_name, limit)
                            except (OSError, ValueError) as error:
                                skipped.append({"path": archive_name, "reason": str(error)})
                                continue
                            encoded = raw.encode("utf-8")
                            if written_bytes + len(encoded) > MAX_BACKUP_BYTES:
                                skipped.append({"path": archive_name, "reason": "backup byte budget reached"})
                                continue
                            archive.writestr(archive_name, encoded)
                            written_bytes += len(encoded)
                        if pending is not None:
                            encoded = pending[1].encode("utf-8")
                            if written_bytes + len(encoded) <= MAX_BACKUP_BYTES:
                                archive.writestr(pending[0], encoded)
                                written_bytes += len(encoded)
                            else:
                                skipped.append({"path": pending[0], "reason": "backup byte budget reached"})
                        archive.writestr("jotline-backup-manifest.json", json.dumps({
                            "created": datetime.now().astimezone().isoformat(), "skipped": skipped,
                            "scope": "Root Markdown notes, settings, and Markdown templates; excludes history and other backups",
                        }, indent=2))
                    stream.flush()
                    os.fsync(stream.fileno())
                replace_at(folder, temporary, name)
                sync_directory(folder)
            finally:
                if template_fd is not None:
                    os.close(template_fd)
                unlink_quietly(folder, temporary)

            new_warning = (f"Backup skipped {len(skipped)} unsafe, unreadable, or over-budget entries; see its manifest"
                           if skipped else "")
            vault.backup_warning = "; ".join(filter(None, (vault.backup_warning, new_warning)))
            if vault.backup_warning:
                vault.warnings.append(vault.backup_warning)
            _prune_backups(vault, folder, name)
            return target
