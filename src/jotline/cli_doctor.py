"""Vault, runtime, and local Jotline diagnostics."""
from __future__ import annotations

from collections import Counter
from importlib import metadata
import os
from pathlib import Path
import platform
import stat
import sys

from . import __version__, history
from .cli_io import default_vault, terminal_text, warning
from .limits import (
    LOCK_TIMEOUT_SECONDS,
    MAX_CACHE_BYTES,
    MAX_CACHED_NOTES,
    MAX_NOTE_BYTES,
    MAX_SCAN_BYTES,
    MAX_SCAN_ENTRIES,
    MAX_SETTINGS_BYTES,
)
from .store import Vault, validate_note_id, validate_workspace
from .templates import MAX_TEMPLATE_ENTRIES, Templates


def distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def module_path(name: str) -> str:
    try:
        module = __import__(name)
        path = getattr(module, "__file__", "")
        return str(Path(path).resolve()) if path else "built-in"
    except Exception as error:
        return f"unavailable: {error}"


def check_managed_directory(path: Path, label: str, warnings: list[str]) -> Path | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            warnings.append(f"{label}: Not a safe directory: {path.name}")
            return None
        return path
    except OSError as error:
        warnings.append(f"{label}: {error}")
        return None


def bounded_children(path: Path, label: str, limit: int, warnings: list[str]):
    try:
        for index, child in enumerate(path.iterdir()):
            if index >= limit:
                warnings.append(f"{label}: stopped after {limit} entries; results are incomplete")
                break
            yield child
    except OSError as error:
        warnings.append(f"{label}: {error}")


def check_vault_access(vault: Vault, warnings: list[str]) -> dict[str, object]:
    mode = None
    writable = False
    try:
        info = vault.path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        writable = stat.S_ISDIR(info.st_mode) and os.access(vault.path, os.W_OK | os.X_OK) and bool(mode & 0o222)
        if not writable:
            warnings.append("vault: Vault directory is not writable; captures and app saves will fail")
    except OSError as error:
        warnings.append(f"vault: {error}")
    return {"path": str(vault.path), "mode": oct(mode) if mode is not None else "unknown", "writable": writable}


def check_lock(vault: Vault, warnings: list[str]) -> dict[str, object]:
    path = vault.path / ".jotline.lock"
    state = {"path": str(path), "exists": path.exists() or path.is_symlink(), "acquired": False}
    try:
        with vault.locked():
            state["acquired"] = True
    except OSError as error:
        warnings.append(f"lock: {error}")
        state["error"] = str(error)
    return state


def check_templates(vault: Vault, warnings: list[str]) -> dict[str, object]:
    templates = Templates(vault.path)
    folder = check_managed_directory(templates.path, "templates", warnings)
    state = {"path": str(templates.path), "files": 0}
    if folder is None:
        state["exists"] = False
        return state
    state["exists"] = True
    for path in bounded_children(folder, "templates", MAX_TEMPLATE_ENTRIES, warnings):
        if not path.name.endswith(".md"):
            continue
        state["files"] += 1
        name = path.stem
        try:
            validate_workspace(name)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise OSError(f"Not a regular template file: {path.name}")
            templates.read(name)
        except (OSError, ValueError) as error:
            warnings.append(f"templates/{path.name}: {error}")
    return state


def check_history(vault: Vault, warnings: list[str]) -> dict[str, object]:
    root = check_managed_directory(vault.path / ".jotline-history", "history", warnings)
    state = {"path": str(vault.path / ".jotline-history"), "notes": 0, "revisions": 0}
    if root is None:
        state["exists"] = False
        return state
    state["exists"] = True
    for folder in bounded_children(root, "history", history.MAX_HISTORY_ENTRIES, warnings):
        try:
            info = folder.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise OSError(f"Not a safe history directory: {folder.name}")
            validate_note_id(folder.name)
            state["notes"] += 1
        except (OSError, ValueError) as error:
            warnings.append(f"history/{folder.name}: {error}")
            continue
        for revision in bounded_children(folder, f"history/{folder.name}", history.MAX_HISTORY_ENTRIES, warnings):
            if not revision.name.endswith(".md"):
                continue
            try:
                info = revision.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise OSError(f"Not a regular revision file: {revision.name}")
                if not history.REVISION_ID.fullmatch(revision.stem):
                    raise ValueError("Invalid revision ID")
                vault.read_revision(folder.name, revision.stem)
                state["revisions"] += 1
            except (OSError, ValueError) as error:
                warnings.append(f"history/{folder.name}/{revision.name}: {error}")
    return state


def check_stale_temps(folder: Path, label: str, limit: int, warnings: list[str]) -> int:
    count = 0
    for path in bounded_children(folder, label, limit, warnings):
        if history.STALE_TEMP.fullmatch(path.name):
            count += 1
            warnings.append(f"{label}: {path.name} was left by an interrupted write; "
                            f"it is removed automatically after {history.STALE_TEMP_SECONDS // 60} minutes")
    return count


def check_backups(vault: Vault, warnings: list[str]) -> dict[str, object]:
    root = check_managed_directory(vault.path / ".jotline-backups", "backups", warnings)
    state = {"path": str(vault.path / ".jotline-backups"), "archives": 0}
    if root is None:
        state["exists"] = False
        return state
    state["exists"] = True
    state["stale_temps"] = check_stale_temps(root, "backups", history.MAX_BACKUP_ENTRIES, warnings)
    for path in bounded_children(root, "backups", history.MAX_BACKUP_ENTRIES, warnings):
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise OSError(f"Not a regular backup file: {path.name}")
            if not history.BACKUP_NAME.fullmatch(path.name):
                continue
            valid, reason = history.validate_backup(path)
            if not valid:
                raise ValueError(reason)
            state["archives"] += 1
        except (OSError, ValueError) as error:
            warnings.append(f"backups/{path.name}: {error}")
    return state


def doctor_report(vault: Vault, settings_warning: str, *, cli_path: str | None = None) -> dict[str, object]:
    notes = vault.notes()
    collections = Counter(note.collection for note in notes)
    warnings = [*vault.warnings]
    if vault.permission_warning and vault.permission_warning not in warnings:
        warnings.append(vault.permission_warning)
    if settings_warning:
        warnings.append(f"settings: {settings_warning}")
    vault_state = check_vault_access(vault, warnings)
    vault_state["stale_temps"] = check_stale_temps(vault.path, "vault", MAX_SCAN_ENTRIES, warnings)
    ancillary = {
        "settings": {"path": str(vault.path / ".jotline-settings.json"), "loaded": not settings_warning},
        "lock": check_lock(vault, warnings),
        "templates": check_templates(vault, warnings),
        "history": check_history(vault, warnings),
        "backups": check_backups(vault, warnings),
        "encryption": {"set_up": vault.has_key(), "encrypted_notes": sum(note.encrypted for note in notes),
                       "cryptography": distribution_version("cryptography")},
    }
    if ancillary["encryption"]["encrypted_notes"] and not ancillary["encryption"]["set_up"]:
        warnings.append("encryption: encrypted notes exist but .jotline-key.json is missing; restore it from a backup")
    if ancillary["encryption"]["encrypted_notes"] and ancillary["encryption"]["cryptography"] == "unknown":
        warnings.append("encryption: encrypted notes need the cryptography package to open")
    if vault.backup_warning and vault.backup_warning not in warnings:
        warnings.append(vault.backup_warning)
    return {
        "jotline": {"version": __version__, "module": str(Path(cli_path or __file__).resolve())},
        "python": {"version": sys.version.split()[0], "executable": sys.executable},
        "textual": {"version": distribution_version("textual"), "module": module_path("textual")},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "paths": {"vault": str(vault.path), "default_vault": str(default_vault()), "cwd": str(Path.cwd())},
        "limits": {
            "note_bytes": MAX_NOTE_BYTES,
            "settings_bytes": MAX_SETTINGS_BYTES,
            "lock_timeout_seconds": LOCK_TIMEOUT_SECONDS,
            "cache_bytes": MAX_CACHE_BYTES,
            "cached_notes": MAX_CACHED_NOTES,
            "scan_entries": MAX_SCAN_ENTRIES,
            "scan_bytes": MAX_SCAN_BYTES,
            "template_entries": MAX_TEMPLATE_ENTRIES,
            "history_entries": history.MAX_HISTORY_ENTRIES,
            "backup_entries": history.MAX_BACKUP_ENTRIES,
            "backup_bytes": history.MAX_BACKUP_BYTES,
        },
        "vault": {**vault_state, "readable_notes": len(notes),
                  "collections": {name: collections[name] for name in sorted(collections)}},
        "ancillary": ancillary,
        "warnings": warnings,
    }


def print_doctor(report: dict[str, object]) -> None:
    vault = report["vault"]
    collections = vault["collections"]
    print(f"Jotline: {terminal_text(report['jotline']['version'])}")
    print(f"Python: {terminal_text(report['python']['version'])} ({terminal_text(report['python']['executable'])})")
    print(f"Textual: {terminal_text(report['textual']['version'])}")
    print("Platform: " + " ".join(terminal_text(report["platform"][key]) for key in ("system", "release", "machine")))
    print(f"Vault: {terminal_text(vault['path'])}")
    print(f"Writable vault: {'yes' if vault['writable'] else 'no'}")
    print(f"Readable notes: {vault['readable_notes']}")
    print("Collections: " + ", ".join(f"{name}={collections[name]}" for name in sorted(collections)))
    limits = report["limits"]
    print(f"Limits: notes={limits['note_bytes']} bytes, settings={limits['settings_bytes']} bytes, "
          f"lock={limits['lock_timeout_seconds']}s")
    print(f"Warnings: {len(report['warnings'])}")
    for item in report["warnings"]:
        warning(item)
