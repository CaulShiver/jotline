"""Launch the workspace or capture text without leaving your shell."""
import argparse
import codecs
from collections import Counter
import getpass
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys
import unicodedata

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
    decode_problem,
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
    # The XDG specification says a relative XDG_DATA_HOME must be ignored.
    xdg_home = os.environ.get("XDG_DATA_HOME") or ""
    if not Path(xdg_home).is_absolute():
        xdg_home = ""
    xdg = Path(xdg_home or Path.home() / ".local/share") / "jotline/notes"
    # Keep existing XDG vaults discoverable when upgrading on macOS.
    if sys.platform == "darwin" and not xdg_home and not xdg.exists():
        return Path.home() / "Library/Application Support/jotline/notes"
    return xdg


def vault_path(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("vault path must not be empty")
    return Path(value)


# Bidirectional overrides and line/paragraph separators can reorder or split
# what a terminal shows; every other format character (joiners, soft hyphen,
# byte-order mark) is ordinary text.
DISRUPTIVE_FORMAT = frozenset("\u2028\u2029\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def is_terminal_control(character: str) -> bool:
    return (unicodedata.category(character) in ("Cc", "Cs", "Cn") and character not in "\t\n\r") \
        or character in DISRUPTIVE_FORMAT


def terminal_text(value: object) -> str:
    """Render diagnostics without allowing note or filename controls to affect a terminal."""
    return "".join(character.encode("unicode_escape").decode("ascii")
                   if is_terminal_control(character) or character in "\n\r\t" else character
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


def check_stale_temps(folder: Path, label: str, limit: int, warnings: list[str]) -> int:
    from . import history

    count = 0
    for path in bounded_children(folder, label, limit, warnings):
        if history.STALE_TEMP.fullmatch(path.name):
            count += 1
            warnings.append(f"{label}: {path.name} was left by an interrupted write; "
                            f"it is removed automatically after {history.STALE_TEMP_SECONDS // 60} minutes")
    return count


def check_backups(vault: Vault, warnings: list[str]) -> dict[str, object]:
    from . import history

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


def read_capture_input(encoding: str = "utf-8", errors: str = "strict") -> str:
    """Read a bounded piped capture, retaining line endings when stdin exposes bytes."""
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(MAX_NOTE_BYTES + 1)
    if isinstance(raw, bytes):
        if len(raw) > MAX_NOTE_BYTES:
            raise ValueError(f"Capture exceeds the {MAX_NOTE_BYTES}-byte file limit")
        return raw.decode(encoding, errors)
    if len(raw.encode("utf-8")) > MAX_NOTE_BYTES:
        raise ValueError(f"Capture exceeds the {MAX_NOTE_BYTES}-byte file limit")
    return raw


def has_terminal_controls(body: str) -> bool:
    return any(is_terminal_control(character) for character in body)


def stdin_is_interactive() -> bool:
    return sys.stdin is None or sys.stdin.isatty()


def encoding_name(value: str) -> str:
    try:
        # Decoding real bytes also rejects bytes-to-bytes codecs such as base64.
        codecs.lookup(value)
        b"a".decode(value, "replace")
    except LookupError:
        raise argparse.ArgumentTypeError(f"unknown text encoding: {value}") from None
    return value


def command_text(words: list[str], encoding: str, errors: str) -> str:
    text = " ".join(words)
    if sys.platform == "win32":
        return text
    # POSIX passes argument bytes through; Python keeps undecodable ones as
    # surrogates, so recover the bytes and decode them as the user asked.
    return os.fsencode(text).decode(encoding, errors)


def decode_input(source: str, encoding: str, read):
    try:
        return read()
    except UnicodeDecodeError as error:
        raise ValueError(f"{source} is {decode_problem(error, encoding)}; pass --encoding NAME if it uses "
                         "another encoding, or --replace-invalid to substitute bad bytes") from None


def input_text(args: argparse.Namespace, encoding: str, errors: str) -> str:
    """Text from the command line, or from piped stdin when none was given."""
    if args.text:
        return decode_input("Command-line text", encoding, lambda: command_text(args.text, encoding, errors))
    if stdin_is_interactive():
        return ""
    return decode_input("Piped input", encoding, lambda: read_capture_input(encoding, errors))


def utf8_error_message(error: UnicodeDecodeError) -> str:
    # Command input is decoded by decode_input, so this came from a stored note.
    return f"The note file is {decode_problem(error)}; convert it to UTF-8 and retry"


MIN_ID_PREFIX = 4


class NoMatchingNote(ValueError):
    """No note has this ID, prefix or title."""


def resolve_note(vault: Vault, reference: str, workspace: str) -> str:
    """Accept a full note ID, a unique ID prefix, an exact title, or `last`."""
    if re.fullmatch(r"[a-zA-Z0-9_-]+", reference) and os.path.lexists(vault.path / f"{reference}.md"):
        return reference
    notes = [note for note in vault.notes() if note.collection != "trash"]
    if reference == "last":
        recent = [note for note in notes if note.workspace == workspace]
        if not recent:
            raise ValueError(f"No notes in workspace {workspace} yet")
        return max(recent, key=lambda note: (note.updated, note.id)).id
    folded = reference.strip().casefold()
    matches = [note for note in notes
               if (len(reference) >= MIN_ID_PREFIX and note.id.startswith(reference))
               or folded in (note.heading.casefold(), note.title.casefold())]
    here = [note for note in matches if note.workspace == workspace]
    if matches and not here:
        raise ValueError("Note is in another workspace; pass --workspace NAME")
    if not here:
        raise NoMatchingNote(f"No note with ID or title {reference}; run jotline list to find IDs")
    if len(here) > 1:
        shown = ", ".join(note.id for note in here[:5]) + (", …" if len(here) > 5 else "")
        raise ValueError(f"{reference} matches {len(here)} notes ({shown}); use more of the ID")
    return here[0].id


PASSPHRASE_NEEDED = ("This needs the passphrase for encrypted notes; run it in a terminal, "
                     "or set JOTLINE_PASSPHRASE for scripts")


def terminal_available() -> bool:
    if sys.platform == "win32":
        return stdin_is_interactive()
    try:
        with open("/dev/tty", "rb"):
            return True
    except OSError:
        return False


def can_ask_passphrase() -> bool:
    return bool(os.environ.get("JOTLINE_PASSPHRASE")) or terminal_available()


def ask_passphrase(prompt: str = "Passphrase for encrypted notes: ", variable: str = "JOTLINE_PASSPHRASE") -> str:
    """Read a passphrase from the environment or the terminal itself, never from piped input."""
    if value := os.environ.get(variable):
        return value
    if not terminal_available():
        raise ValueError(PASSPHRASE_NEEDED)
    try:
        passphrase = getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt):
        passphrase = ""
    if not passphrase:
        raise ValueError("No passphrase entered")
    return passphrase


def new_passphrase(variable: str) -> str:
    from .crypto import check_passphrase

    if value := os.environ.get(variable):
        return check_passphrase(value)
    first = check_passphrase(ask_passphrase("New passphrase (8+ characters): ", variable))
    if ask_passphrase("Repeat the new passphrase: ", variable) != first:
        raise ValueError("The passphrases did not match; nothing was changed")
    return first


def unlock_vault(vault: Vault) -> None:
    if vault.cipher is None:
        if not vault.has_key():
            raise ValueError("Encryption is not set up; run jotline encryption setup first")
        vault.unlock(ask_passphrase())


def due_argument(value: str) -> str:
    from .tasks import due_limit

    try:
        return due_limit(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def can_open_editor() -> bool:
    return stdin_is_interactive() and sys.stdout.isatty()


def quick_capture(settings: Settings, daily: bool, workspace: str) -> str | None:
    from .capture_ui import QuickCapture

    destination = ("today's log" if daily else settings.default_collection) + " · " + workspace
    return QuickCapture(destination, settings.theme).run()


def missing_file_message(args: argparse.Namespace, error: FileNotFoundError) -> str:
    # Windows reports a missing file without its name, so check the target itself.
    note_id = getattr(args, "id", None)
    vault = Path(args.vault).expanduser()
    if note_id and vault.is_dir() and not (vault / f"{note_id}.md").exists():
        return f"No note with ID {terminal_text(note_id)}; run jotline list to find IDs"
    if args.command == "import" and not args.file.exists():
        return f"No such file or directory: {terminal_text(args.file)}"
    if error.filename is None:
        return terminal_text(error)
    return f"No such file or directory: {terminal_text(os.fsdecode(error.filename))}"


NOTE_HELP = "Note ID, a unique ID prefix (4+ characters), an exact title, or last"


def add_encoding_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--encoding", type=encoding_name, default="utf-8",
                         help="Decode input with this encoding instead of UTF-8, such as latin-1 or cp1252")
    command.add_argument("--replace-invalid", action="store_true",
                         help="Replace bytes that cannot be decoded instead of stopping")


def build_parser() -> argparse.ArgumentParser:
    from .completion import SHELLS
    from .export import FORMATS

    parser = argparse.ArgumentParser(prog="jotline", description="Jotline — a terminal home for your thoughts")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--vault", type=vault_path, default=default_vault(), help="Markdown vault directory")
    parser.add_argument("--workspace", help="Workspace name (defaults to the last workspace used in the app)")
    parser.add_argument("--unlock", action="store_true",
                        help="Ask for the encryption passphrase first so encrypted notes are included")
    sub = parser.add_subparsers(dest="command")
    capture = sub.add_parser("capture", help="Capture text, read piped stdin, or open a small editor")
    capture.add_argument("text", nargs="*")
    capture.add_argument("--daily", action="store_true", help="Append to today's log")
    add_encoding_options(capture)
    listing = sub.add_parser("list", help="Find notes")
    listing.add_argument("query", nargs="?", default="")
    listing.add_argument("--json", action="store_true", help="Print note metadata as JSON")
    for command in ('append', 'prepend'):
        update = sub.add_parser(command, help=f'{command.title()} text to an existing note')
        update.add_argument('id', metavar='NOTE', help=NOTE_HELP)
        update.add_argument('text', nargs='*')
        update.add_argument('--no-newline', action='store_true',
                            help='Join the text exactly, without adding a line break')
        add_encoding_options(update)
    opening = sub.add_parser('open', help='Open a note in the terminal editor')
    opening.add_argument('id', metavar='NOTE', help=NOTE_HELP)
    actions = sub.add_parser('actions', help='List local actions')
    actions.add_argument("--json", action="store_true", help="Print action names and steps as JSON")
    action = sub.add_parser('run', help='Run a named local action on a note')
    action.add_argument('action')
    action.add_argument('id', metavar='NOTE', help=NOTE_HELP)
    action.add_argument('--raw', action='store_true', help='Allow terminal control characters in exported output')
    export = sub.add_parser("export", help="Write a note's Markdown to stdout, or save it as HTML, Word or PDF")
    export.add_argument("id", metavar="NOTE", help=NOTE_HELP)
    export.add_argument("--format", choices=FORMATS,
                        help="markdown (default), html, docx or pdf; guessed from the --output file extension")
    export.add_argument("-o", "--output", type=Path, help="Write this file instead of stdout; needed for docx and pdf")
    export.add_argument("--force", action="store_true", help="Replace the output file if it already exists")
    export.add_argument("--raw", action="store_true", help="Allow terminal control characters on an interactive terminal")
    workspaces = sub.add_parser("workspaces", help="List workspaces")
    workspaces.add_argument("--json", action="store_true", help="Print workspaces as JSON")
    tag_list = sub.add_parser("tags", help="List tags and note counts in this workspace")
    tag_list.add_argument("--json", action="store_true", help="Print tags and counts as JSON")
    tagging = sub.add_parser("tag", help="Add inline tags to a note")
    tagging.add_argument("id", metavar="NOTE", help=NOTE_HELP)
    tagging.add_argument("tags", nargs="+")
    tasks = sub.add_parser("tasks", help="List open checkbox tasks across notes")
    tasks.add_argument("query", nargs="?", default="", help="Only notes matching this search, such as #work")
    tasks.add_argument("--done", action="store_true", help="Include completed tasks")
    tasks.add_argument("--due", type=due_argument, metavar="DATE",
                       help="Only tasks due on or before DATE (YYYY-MM-DD or today)")
    tasks.add_argument("--json", action="store_true", help="Print tasks as JSON")
    finish = sub.add_parser("done", help="Check off a task listed by jotline tasks")
    finish.add_argument("task", metavar="NOTE:LINE", help="The reference printed by jotline tasks")
    finish.add_argument("--undo", action="store_true", help="Mark the task as not done again")
    for command, text in (("encrypt", "Encrypt a note's text on disk"),
                          ("decrypt", "Store an encrypted note as plain text again")):
        sealing = sub.add_parser(command, help=text)
        sealing.add_argument("id", metavar="NOTE", help=NOTE_HELP)
    encryption = sub.add_parser("encryption", help="Set up encryption, change its passphrase, or show status")
    encryption.add_argument("action", choices=("status", "setup", "passphrase"))
    sub.add_parser("backup", help="Back up notes, settings and templates to a local ZIP")
    sub.add_parser("path", help="Print the vault path")
    doctor = sub.add_parser("doctor", help="Check the vault, runtime and local Jotline state")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable diagnostics")
    importing = sub.add_parser("import", help="Import UTF-8 text, a folder, or a Drafts export")
    importing.add_argument("file", type=Path)
    import_mode = importing.add_mutually_exclusive_group()
    import_mode.add_argument("--preview", action="store_true", help="Preview without creating notes")
    import_mode.add_argument("--apply", action="store_true", help="Apply a folder or Drafts import after reviewing preview")
    importing.add_argument("--recursive", action="store_true", help="Include subfolders without following links")
    importing.add_argument("--duplicates", choices=("skip", "copy"), default="skip",
                           help="Skip matching bodies/UUIDs (default), or create separate copies")
    add_encoding_options(importing)
    completion = sub.add_parser("completion", help="Print a shell completion script")
    completion.add_argument("shell", choices=SHELLS)
    return parser


def main() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", newline="")
    parser = build_parser()
    args = parser.parse_args()
    # Commands that only read must not turn a mistyped path into a new vault.
    read_only = {"list", "actions", "export", "workspaces", "tags", "tasks", "doctor"}
    try:
        if args.command == "path":
            print(terminal_text(args.vault.expanduser().resolve()))
            return
        if args.command == "completion":
            from .completion import script
            sys.stdout.write(script(args.shell, parser))
            return
        vault = Vault(args.vault, create=args.command not in read_only)
        # Shell captures can wait; only the interactive app needs a short lock timeout.
        vault.lock_timeout = 10.0
        settings, settings_warning = Settings.load(vault.path / ".jotline-settings.json")
        workspace = validate_workspace(settings.active_workspace if args.workspace is None else args.workspace)
        if settings_warning and args.command not in (None, "doctor"):
            warning(settings_warning)
        if args.command != "encryption" and (
                args.unlock or (os.environ.get("JOTLINE_PASSPHRASE") and vault.has_key())):
            unlock_vault(vault)
        if getattr(args, "id", None) is not None:
            try:
                args.id = resolve_note(vault, args.id, workspace)
            except NoMatchingNote:
                # Locked notes' titles are sealed; unlock and look again when that is possible.
                if (vault.cipher is not None or not vault.has_key() or not can_ask_passphrase()
                        or not any(note.locked for note in vault.notes())):
                    raise
                unlock_vault(vault)
                args.id = resolve_note(vault, args.id, workspace)
            if vault.read(args.id).locked:
                unlock_vault(vault)
        encoding = getattr(args, "encoding", "utf-8")
        errors = "replace" if getattr(args, "replace_invalid", False) else "strict"
        if args.command == "import" and (args.preview or args.apply or args.recursive or args.file.is_dir()
                                           or args.file.suffix.lower() == ".draftsexport"):
            from .importing import preview_import, apply_import
            if args.preview and args.apply:
                parser.error("Choose --preview or --apply")
            plan = preview_import(vault, args.file, workspace, settings.default_collection,
                                  args.duplicates, args.recursive, encoding=encoding, errors=errors)
            print(plan.summary())
            for item in plan.items:
                decision = "skip" if item.duplicate and plan.duplicates == "skip" else "import"
                print(terminal_text(f"{decision}\t{item.source}\t{item.note.collection}\t{item.note.title}"))
            for message in plan.warnings:
                warning(message)
            if args.apply:
                result = apply_import(vault, plan)
                print(result.summary())
                for message in result.errors:
                    warning(message)
                if result.errors or plan.warnings:
                    raise SystemExit(1)
            else:
                print("Preview only. Repeat with --apply to create notes. Originals remain untouched.")
        elif args.command in {"capture", "import"}:
            if args.command == "import":
                body = decode_input(str(args.file), encoding, lambda: read_regular_file(
                    args.file, MAX_NOTE_BYTES, ancestor_safe=True, encoding=encoding, errors=errors))
            else:
                if args.daily and vault.has_key() and vault.daily(settings.daily_template, workspace).locked:
                    unlock_vault(vault)
                body = input_text(args, encoding, errors)
                if not body.strip() and not args.text and can_open_editor():
                    body = quick_capture(settings, args.daily, workspace)
                    if body is None:
                        parser.exit(1, "jotline: Nothing captured\n")
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
        elif args.command in {'append', 'prepend'}:
            body = input_text(args, encoding, errors)
            if not body:
                parser.error('Provide text or pipe UTF-8 text to append/prepend')
            note = vault.append_note(args.id, body, workspace, prepend=args.command == 'prepend',
                                     line_break=not args.no_newline)
            print(note.id)
        elif args.command == 'actions':
            if args.json:
                print(json.dumps([dict(name=name, steps=steps) for name, steps in settings.actions.items()],
                                 ensure_ascii=True))
            else:
                for name in settings.actions:
                    print(name)
        elif args.command == 'run':
            from .actions import ActionCommitError, preview_action
            from .action_history import run_recorded_action
            if args.action not in settings.actions:
                raise ValueError('Unknown action; use jotline actions')
            note = vault.read(args.id)
            if note.workspace != workspace:
                raise ValueError('Note is in another workspace; pass --workspace NAME')
            steps = settings.actions[args.action]
            guard_output = sys.stdout.isatty() and not args.raw
            if guard_output and any(step['type'] == 'export' for step in steps):
                # Decide before any step runs, so a refused export cannot leave
                # an append applied and then repeat it on every retry.
                _, effects = preview_action(vault, note, steps)
                if any(has_terminal_controls(effect) for effect in effects):
                    raise ValueError('Refusing to print terminal controls; redirect stdout or pass --raw')
            def output(body):
                if guard_output and has_terminal_controls(body):
                    raise ValueError('Refusing to print terminal controls; redirect stdout or pass --raw')
                sys.stdout.write(body)
            try:
                run_recorded_action(vault, note, steps, name=args.action,
                                    history_warning=warning, export=output)
            except ActionCommitError as error:
                raise ValueError(f'{error}. Review action history before retrying.') from error
            except (ValueError, OSError) as error:
                raise ValueError(f'Action stopped: {error}. Earlier completed steps remain applied.') from error
        elif args.command == "list":
            notes = vault.search(args.query, workspace=workspace)
            if args.json:
                print(json.dumps([dict(id=n.id, title=n.title, collection=n.collection, workspace=n.workspace,
                                       created=n.created, updated=n.updated, starred=n.starred, tags=sorted(n.tags),
                                       encrypted=n.encrypted)
                                  for n in notes], ensure_ascii=True))
            for note in ([] if args.json else notes):
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
            from .export import BINARY, FORMAT_NAMES, export_bytes, format_for, write_export
            fmt = format_for(args.format, args.output)
            if fmt in BINARY and args.output is None:
                raise ValueError(f"{FORMAT_NAMES[fmt]} export needs --output FILE")
            titles = {} if fmt == "markdown" else {other.id: other.title for other in vault.search(workspace=workspace)}
            if args.output is not None:
                written = write_export(args.output, export_bytes(note.title, note.body, fmt, titles), force=args.force)
                print(terminal_text(written))
                return
            body = note.body if fmt == "markdown" else export_bytes(note.title, note.body, fmt, titles).decode("utf-8")
            if sys.stdout.isatty() and has_terminal_controls(body) and not args.raw:
                raise ValueError("Refusing to print terminal controls interactively; redirect stdout or pass --raw")
            sys.stdout.write(body)
        elif args.command == "tasks":
            from .tasks import gather, short_ids
            notes = vault.search(args.query, workspace=workspace)
            found = gather(notes, include_done=args.done, due_by=args.due)
            if args.json:
                print(json.dumps([dict(note=task.note_id, line=task.line, text=task.text, done=task.done,
                                       due=task.due, title=task.note_title) for task in found], ensure_ascii=True))
            else:
                prefixes = short_ids(note.id for note in vault.notes())
                for task in found:
                    print("\t".join(terminal_text(field) for field in (
                        task.reference(prefixes.get(task.note_id)), "[x]" if task.done else "[ ]",
                        task.due or "-", task.text, task.note_title)))
            if locked := sum(note.locked for note in notes):
                warning(f"{locked} encrypted note{'' if locked == 1 else 's'} locked; "
                        "pass --unlock to include their tasks")
            for item in vault.warnings:
                warning(item)
        elif args.command == "done":
            from .tasks import parse_reference, set_done
            reference, line = parse_reference(args.task)
            note_id = resolve_note(vault, reference, workspace)
            if vault.read(note_id).locked:
                unlock_vault(vault)
            checked = {}

            def check(body: str) -> str:
                updated, checked["task"] = set_done(body, line, not args.undo)
                return updated

            vault.update_body(note_id, workspace, check)
            print(("[ ]" if args.undo else "[x]") + "\t" + terminal_text(checked["task"].text))
        elif args.command in {"encrypt", "decrypt"}:
            encrypting = args.command == "encrypt"
            if encrypting:
                unlock_vault(vault)
            note, changed = vault.set_encrypted(args.id, workspace, encrypting)
            print(note.id)
            if not changed:
                warning("The note was already " + ("encrypted" if encrypting else "stored as plain text"))
            elif encrypting:
                warning("Its unencrypted saved versions were removed; backups made before now still "
                        "contain the old text")
        elif args.command == "encryption":
            if args.action == "setup":
                if vault.has_key():
                    raise ValueError("Encryption is already set up for this vault; "
                                     "use jotline encryption passphrase to change the passphrase")
                vault.setup_encryption(new_passphrase("JOTLINE_PASSPHRASE"))
                print("Encryption is set up. Encrypt a note with: jotline encrypt NOTE")
                warning("There is no way to recover encrypted notes without this passphrase; keep it somewhere safe")
            elif args.action == "passphrase":
                old = ask_passphrase("Current passphrase: ")
                vault.change_passphrase(old, new_passphrase("JOTLINE_NEW_PASSPHRASE"))
                print("Passphrase changed")
            elif vault.has_key():
                count = sum(note.encrypted for note in vault.notes())
                print(f"Encryption is set up; {count} encrypted note{'' if count == 1 else 's'}")
            else:
                print("Encryption is not set up")
        elif args.command == "workspaces":
            names = sorted(vault.workspaces() | set(settings.workspace_names) | {workspace})
            if args.json:
                print(json.dumps([dict(name=name, active=name == workspace) for name in names]))
            for name in ([] if args.json else names):
                print(name + (" *" if name == workspace else ""))
            for item in vault.warnings:
                warning(item)
        elif args.command == "tags":
            counts = sorted(vault.tags(workspace).items())
            if args.json:
                print(json.dumps([dict(tag=tag, count=count) for tag, count in counts], ensure_ascii=True))
            for tag, count in ([] if args.json else counts):
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
            initial_note = None
            if args.command == 'open':
                initial_note = vault.read(args.id)
                if initial_note.workspace != workspace:
                    raise ValueError('Note is in another workspace; pass --workspace NAME')
            Jotline(vault, workspace=workspace, initial_note=initial_note).run()
        if vault.backup_warning:
            warning(vault.backup_warning)
    except BrokenPipeError:
        # The reader closed early (for example `jotline list | head`); that is
        # not an error, and Python must not print one while flushing at exit.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0)
    except UnicodeDecodeError as error:
        parser.exit(1, f"jotline: {utf8_error_message(error)}\n")
    except FileNotFoundError as error:
        parser.exit(1, f"jotline: {missing_file_message(args, error)}\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"jotline: {terminal_text(error)}\n")


if __name__ == "__main__":
    main()
