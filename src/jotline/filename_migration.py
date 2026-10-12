"""Opt-in migration between ``<id>.md`` and ``slug--short.md``.

``migrate_filenames`` takes the vault write lock itself, including for a dry
run, so the plan matches one snapshot of the folder.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import history
from .filenames import FilenameMode, filename_for, header_needs_id, is_generated_id, set_header_id
from .filesystem import (
    create_private_temp,
    fs as os,
    publish_new,
    read_regular_at,
    replace_at,
    unlink_quietly,
)
from .limits import MAX_NOTE_BYTES, MAX_SCAN_ENTRIES
from .settings import Settings
from .store import Note, Vault, is_daily_id


@dataclass(frozen=True)
class FilenameChange:
    note_id: str
    title: str
    source: str
    target: str
    action: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.note_id,
            "title": self.title,
            "source": self.source,
            "target": self.target,
            "action": self.action,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FilenameReport:
    dry_run: bool
    revert: bool
    backup: str | None
    readable_filenames: bool | None
    changes: tuple[FilenameChange, ...]

    @property
    def ok(self) -> bool:
        return not any(change.action in {"conflict", "failed"} for change in self.changes)

    def as_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "revert": self.revert,
            "ok": self.ok,
            "backup": self.backup,
            "readable_filenames": self.readable_filenames,
            "changes": [change.as_dict() for change in self.changes],
        }

    def lines(self) -> list[str]:
        output: list[str] = []
        if self.dry_run:
            output.append("Dry run. No backup was written and no files were changed.")
        elif self.backup:
            output.append(f"Backed up to {self.backup}")
        for change in self.changes:
            output.append(_line(change, dry_run=self.dry_run))
        if not self.ok and self.backup is None:
            output.append("Nothing was changed.")
        elif not self.ok:
            output.append("Some notes could not be renamed. The backup above still has the previous files. "
                          "Run the command again after the conflicts are resolved.")
        elif self.dry_run:
            output.append("Readable filenames would be turned off." if self.revert
                          else "Readable filenames would be turned on.")
        elif self.readable_filenames:
            output.append("Readable filenames are on.")
        else:
            output.append("Readable filenames are off. Note files use their IDs again.")
        return output


def _line(change: FilenameChange, *, dry_run: bool) -> str:
    if change.action == "rename":
        verb = "would rename" if dry_run else "renamed"
        reason = f" ({change.reason})" if change.reason else ""
        return f"{verb} {change.source} -> {change.target}{reason}"
    if change.action == "drop":
        verb = "would remove duplicate" if dry_run else "removed duplicate"
        return f"{verb} {change.source}"
    if change.action == "skip":
        return f"skip {change.source} ({change.reason})"
    if change.action == "conflict":
        return f"conflict {change.source or 'vault'}: {change.reason}"
    if change.action == "failed":
        return f"failed {change.source}: {change.reason}"
    raise AssertionError(change.action)


def _same_note(left: Note, right: Note) -> bool:
    fields = ("body", "sealed", "collection", "created", "updated", "starred",
              "workspace", "encrypted", "recovery_of", "key_id")
    return all(getattr(left, name) == getattr(right, name) for name in fields)


def _skip_reason(note: Note, *, revert: bool) -> str:
    if is_daily_id(note.id):
        return "daily log"
    if note.encrypted:
        return "encrypted; the title stays out of the filename"
    if not is_generated_id(note.id):
        return "keeps its own filename"
    if revert:
        return "already named with its ID"
    return "already readable"


@dataclass(frozen=True)
class _File:
    name: str
    note: Note | None
    raw: str
    error: str


def migrate_filenames(vault: Vault, settings: Settings, *, dry_run: bool = False,
                      revert: bool = False) -> FilenameReport:
    """Rename note files, or put the ID back in the filename.

    A dry run only reports. A real run refuses to start when any note is
    blocked. Otherwise it writes a manual ZIP backup and then renames. The
    setting changes only after every planned rename succeeds.
    """
    with vault.write_lock() as directory:
        changes, truncated = _plan(vault, directory, revert=revert)
        if truncated:
            changes = (FilenameChange(
                "", "", "", "", "conflict",
                f"Vault scan stopped after {MAX_SCAN_ENTRIES} entries; nothing was renamed"),)
        if dry_run or any(change.action == "conflict" for change in changes):
            return FilenameReport(dry_run, revert, None, None, changes)
        backup = history.backup(vault, vault_directory=directory)
        failed = _apply(vault, directory, changes)
        if failed:
            applied = _with_failures(changes, failed)
            return FilenameReport(False, revert, str(backup), None, applied)
        settings.readable_filenames = not revert
        settings.save(vault.path / ".jotline-settings.json", directory=directory)
        vault.readable_filenames = settings.readable_filenames
        vault.invalidate_cache()
        return FilenameReport(False, revert, str(backup), settings.readable_filenames, changes)


def _with_failures(changes: tuple[FilenameChange, ...],
                   failed: dict[str, FilenameChange]) -> tuple[FilenameChange, ...]:
    applied: list[FilenameChange] = []
    for change in changes:
        if change.source in failed and change.action in {"rename", "drop"}:
            applied.append(failed[change.source])
        elif change.action == "drop" and failed:
            applied.append(FilenameChange(
                change.note_id, change.title, change.source, change.target, "skip",
                "not removed because another file for this note was not renamed"))
        else:
            applied.append(change)
    return tuple(applied)


def _plan(vault: Vault, directory: int, *, revert: bool) -> tuple[tuple[FilenameChange, ...], bool]:
    files: list[_File] = []
    truncated = False
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_SCAN_ENTRIES:
                truncated = True
                break
            if not entry.name.endswith(".md"):
                continue
            try:
                raw = read_regular_at(directory, entry.name, MAX_NOTE_BYTES)
                note = vault.parse_note(entry.name[:-3], raw, vault.cipher)
            except (OSError, ValueError) as error:
                files.append(_File(entry.name, None, "", str(error)))
                continue
            note.filename = entry.name
            files.append(_File(entry.name, note, raw, ""))
    return _changes(files, revert=revert), truncated


def _changes(files: list[_File], *, revert: bool) -> tuple[FilenameChange, ...]:
    changes: list[FilenameChange] = []
    groups: dict[str, list[_File]] = {}
    for item in files:
        if item.note is None:
            changes.append(FilenameChange("", "", item.name, item.name, "skip", item.error or "could not be read"))
            continue
        groups.setdefault(item.note.id, []).append(item)
    occupied = {item.name for item in files}
    mode: FilenameMode = "opaque" if revert else "readable"
    for note_id in sorted(groups):
        group = sorted(groups[note_id], key=lambda item: item.name)
        note = group[0].note
        assert note is not None
        if any(item.note is None or not _same_note(note, item.note) for item in group):
            listed = ", ".join(item.name for item in group)
            changes.append(FilenameChange(
                note_id, note.title, listed, "", "conflict",
                "this note ID is in more than one file and the copies differ"))
            continue
        names = [item.name for item in group]
        target = filename_for(
            note.id, note.title, encrypted=note.encrypted, mode=mode,
            current=names[0], occupied=occupied)
        if target not in names and target in occupied:
            changes.append(FilenameChange(
                note.id, note.title, names[0], target, "conflict", f"{target} already exists"))
            continue
        occupied.add(target)
        source = next(item for item in group if item.name == target) if target in names else group[0]
        assert source.note is not None
        extras = [item.name for item in group if item.name != source.name]
        wanted = note.id if header_needs_id(target, note.id) else None
        try:
            rewritten = set_header_id(source.raw, wanted)
        except ValueError as error:
            changes.append(FilenameChange(note.id, note.title, source.name, target, "conflict", str(error)))
            continue
        if target == source.name and rewritten == source.raw and not extras:
            changes.append(FilenameChange(
                note.id, note.title, source.name, target, "skip", _skip_reason(note, revert=revert)))
            continue
        reason = _skip_reason(note, revert=revert) if target != source.name and (
            is_daily_id(note.id) or note.encrypted or not is_generated_id(note.id)) else ""
        changes.append(FilenameChange(note.id, note.title, source.name, target, "rename", reason))
        for extra in extras:
            changes.append(FilenameChange(
                note.id, note.title, extra, target, "drop",
                "same note left behind by an interrupted rename"))
    return tuple(changes)


def _apply(vault: Vault, directory: int, changes: tuple[FilenameChange, ...]) -> dict[str, FilenameChange]:
    """Publish planned renames. Keys are source filenames that did not complete."""
    failed: dict[str, FilenameChange] = {}
    raws = _read_sources(directory, changes)
    for change in changes:
        if change.action != "rename":
            continue
        raw = raws.get(change.source)
        if raw is None:
            failed[change.source] = FilenameChange(
                change.note_id, change.title, change.source, change.target, "failed",
                "the file disappeared before it could be renamed")
            continue
        wanted = change.note_id if header_needs_id(change.target, change.note_id) else None
        try:
            rewritten = set_header_id(raw, wanted)
            try:
                history.snapshot(vault, change.note_id, raw, vault_directory=directory)
            except OSError as error:
                vault.warnings.append(f"History {change.note_id} was not updated before rename: {error}")
            _publish_rename(directory, change.source, change.target, raw, rewritten)
        except (OSError, ValueError) as error:
            failed[change.source] = FilenameChange(
                change.note_id, change.title, change.source, change.target, "failed", str(error))
    if failed:
        return failed
    for change in changes:
        if change.action != "drop":
            continue
        unlink_quietly(directory, change.source)
    try:
        history.sync_directory(directory)
    except OSError:
        pass
    return failed


def _read_sources(directory: int, changes: tuple[FilenameChange, ...]) -> dict[str, str]:
    found: dict[str, str] = {}
    for change in changes:
        if change.action != "rename" or change.source in found:
            continue
        try:
            found[change.source] = read_regular_at(directory, change.source, MAX_NOTE_BYTES)
        except (OSError, ValueError):
            continue
    return found


def _publish_rename(directory: int, source: str, target: str, raw: str, rewritten: str) -> None:
    if rewritten == raw and source == target:
        return
    fd, temp = create_private_temp(directory, ".jotline-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(rewritten)
            stream.flush()
            os.fsync(stream.fileno())
        latest = read_regular_at(directory, source, MAX_NOTE_BYTES)
        if latest != raw:
            raise OSError(f"{source} changed while it was being renamed; it was left in place")
        if source == target:
            replace_at(directory, temp, source)
            return
        publish_new(directory, temp, target)
        latest = read_regular_at(directory, source, MAX_NOTE_BYTES)
        if latest != raw:
            raise OSError(f"{source} changed after {target} was published; both files were left in place")
        unlink_quietly(directory, source)
    finally:
        unlink_quietly(directory, temp)
