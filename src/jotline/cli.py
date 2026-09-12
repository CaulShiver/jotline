"""Launch the workspace or capture text without leaving your shell."""
import argparse
from collections import Counter
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import stat
import sys

from . import __version__
from .store import (
    LOCK_TIMEOUT_SECONDS,
    MAX_CACHE_BYTES,
    MAX_CACHED_NOTES,
    MAX_NOTE_BYTES,
    MAX_SCAN_BYTES,
    MAX_SCAN_ENTRIES,
    MAX_SETTINGS_BYTES,
    Vault,
    read_regular_file,
    tagged_body,
    validate_workspace,
)
from .settings import Settings
from .templates import MAX_TEMPLATE_ENTRIES, Templates


def default_vault() -> Path:
    override = os.environ.get("JOTLINE_VAULT")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "jotline/notes"
    # Keep existing XDG vaults discoverable when upgrading on macOS.
    xdg = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "jotline/notes"
    if sys.platform == "darwin" and not os.environ.get("XDG_DATA_HOME") and not xdg.exists():
        return Path.home() / "Library/Application Support/jotline/notes"
    return xdg


def terminal_text(value: object) -> str:
    """Render diagnostics without allowing note or filename controls to affect a terminal."""
    return "".join(character if character.isprintable() else
                   character.encode("unicode_escape").decode("ascii")
                   for character in str(value))


def warning(value: object) -> None:
    print(f"warning: {terminal_text(value)}", file=sys.stderr)


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
        except (OSError, UnicodeError, ValueError) as error:
            warnings.append(f"templates/{path.name}: {error}")
    return state


def check_history(vault: Vault, warnings: list[str]) -> dict[str, object]:
    from . import history

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
            vault.file(folder.name)
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
            except (OSError, UnicodeError, ValueError) as error:
                warnings.append(f"history/{folder.name}/{revision.name}: {error}")
    return state


def check_backups(vault: Vault, warnings: list[str]) -> dict[str, object]:
    from . import history

    root = check_managed_directory(vault.path / ".jotline-backups", "backups", warnings)
    state = {"path": str(vault.path / ".jotline-backups"), "archives": 0}
    if root is None:
        state["exists"] = False
        return state
    state["exists"] = True
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


def doctor_report(vault: Vault, settings_warning: str) -> dict[str, object]:
    from . import history

    notes = vault.notes()
    collections = Counter(note.collection for note in notes)
    warnings = [*vault.warnings]
    if vault.permission_warning and vault.permission_warning not in warnings:
        warnings.append(vault.permission_warning)
    if settings_warning:
        warnings.append(f"settings: {settings_warning}")
    vault_state = check_vault_access(vault, warnings)
    ancillary = {
        "settings": {"path": str(vault.path / ".jotline-settings.json"), "loaded": not settings_warning},
        "lock": check_lock(vault, warnings),
        "templates": check_templates(vault, warnings),
        "history": check_history(vault, warnings),
        "backups": check_backups(vault, warnings),
    }
    if vault.backup_warning and vault.backup_warning not in warnings:
        warnings.append(vault.backup_warning)
    return {
        "jotline": {"version": __version__, "module": str(Path(__file__).resolve())},
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


def read_capture_input() -> str:
    """Read a bounded piped capture, retaining line endings when stdin exposes bytes."""
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(MAX_NOTE_BYTES + 1)
    if isinstance(raw, bytes):
        if len(raw) > MAX_NOTE_BYTES:
            raise ValueError(f"Capture exceeds the {MAX_NOTE_BYTES}-byte file limit")
        return raw.decode("utf-8")
    if len(raw.encode("utf-8")) > MAX_NOTE_BYTES:
        raise ValueError(f"Capture exceeds the {MAX_NOTE_BYTES}-byte file limit")
    return raw


def has_terminal_controls(body: str) -> bool:
    return any(character not in "\n\t" and not character.isprintable() for character in body)


def main() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", newline="")
    parser = argparse.ArgumentParser(description="Jotline — a terminal home for your thoughts")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--vault", type=Path, default=default_vault(), help="Markdown vault directory")
    parser.add_argument("--workspace", help="Workspace name (defaults to the last workspace used in the app)")
    sub = parser.add_subparsers(dest="command")
    capture = sub.add_parser("capture", help="Capture text, or read piped stdin")
    capture.add_argument("text", nargs="*")
    capture.add_argument("--daily", action="store_true", help="Append to today's log")
    listing = sub.add_parser("list", help="Find notes")
    listing.add_argument("query", nargs="?", default="")
    export = sub.add_parser("export", help="Write a note's Markdown body to stdout")
    export.add_argument("id")
    export.add_argument("--raw", action="store_true", help="Allow terminal control characters on an interactive terminal")
    sub.add_parser("workspaces", help="List workspaces")
    sub.add_parser("tags", help="List tags and note counts in this workspace")
    tagging = sub.add_parser("tag", help="Add inline tags to a note")
    tagging.add_argument("id")
    tagging.add_argument("tags", nargs="+")
    sub.add_parser("backup", help="Back up notes, settings and templates to a local ZIP")
    sub.add_parser("path", help="Print the vault path")
    doctor = sub.add_parser("doctor", help="Check the vault, runtime and local Jotline state")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable diagnostics")
    importing = sub.add_parser("import", help="Copy a UTF-8 Markdown file into the vault")
    importing.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        vault = Vault(args.vault)
        settings, settings_warning = Settings.load(vault.path / ".jotline-settings.json")
        workspace = validate_workspace(settings.active_workspace if args.workspace is None else args.workspace)
        if settings_warning and args.command not in (None, "doctor"):
            warning(settings_warning)
        if args.command == "path":
            print(terminal_text(vault.path))
        elif args.command in {"capture", "import"}:
            if args.command == "import":
                body = read_regular_file(args.file, MAX_NOTE_BYTES, ancestor_safe=True)
            else:
                body = " ".join(args.text) if args.text else (read_capture_input() if not sys.stdin.isatty() else "")
                if not body.strip():
                    parser.error("Provide text or pipe text to jotline capture")
            if args.command == "capture" and args.daily:
                note = vault.append_daily(body, settings.daily_template, workspace)
            else:
                note = vault.new(body, workspace=workspace)
                note.collection = settings.default_collection
                vault.save(note)
            print(note.id)
        elif args.command == "backup":
            print(terminal_text(vault.backup()))
        elif args.command == "list":
            for note in vault.search(args.query, workspace=workspace):
                # Escape control characters when printing untrusted note text to a terminal.
                title = terminal_text(note.title)
                print(f"{note.id}\t{note.collection}\t{title}")
            for item in vault.warnings:
                warning(item)
        elif args.command in {"export", "tag"}:
            note = vault.read(args.id)
            if note.workspace != workspace:
                raise ValueError("Note is in another workspace; pass --workspace NAME")
            if args.command == "tag":
                note.body = tagged_body(note.body, " ".join(args.tags))
                vault.save(note)
                print(note.id)
                if vault.backup_warning:
                    warning(vault.backup_warning)
                return
            body = note.body
            if sys.stdout.isatty() and has_terminal_controls(body) and not args.raw:
                raise ValueError("Refusing to print terminal controls interactively; redirect stdout or pass --raw")
            sys.stdout.write(body)
        elif args.command == "workspaces":
            for name in sorted(vault.workspaces() | set(settings.workspace_names) | {workspace}):
                print(name + (" *" if name == workspace else ""))
            for item in vault.warnings:
                warning(item)
        elif args.command == "tags":
            for tag, count in sorted(vault.tags(workspace).items()):
                print(f"#{tag}\t{count}")
            for item in vault.warnings:
                warning(item)
        elif args.command == "doctor":
            report = doctor_report(vault, settings_warning)
            if args.json:
                print(json.dumps(report, sort_keys=True))
            else:
                print_doctor(report)
            if report["warnings"]:
                parser.exit(1)
        else:
            from .app import Jotline
            Jotline(vault, workspace=workspace).run()
        if vault.backup_warning:
            warning(vault.backup_warning)
    except (OSError, ValueError) as error:
        parser.exit(1, f"jotline: {terminal_text(error)}\n")


if __name__ == "__main__":
    main()
