"""Launch the workspace or capture text without leaving your shell."""
import argparse
from dataclasses import dataclass
from datetime import date
import getpass
import json
import os
from pathlib import Path
import re
import sys

from . import __version__, history
from .action_history import run_recorded_action
from .actions import ActionCommitError, preview_action
from .app import Jotline
from .capture_ui import QuickCapture
from .cli_doctor import (
    check_managed_directory,
    doctor_report as _doctor_report,
    print_doctor,
)
from .cli_io import (
    decode_input,
    default_vault,
    encoding_name,
    has_terminal_controls,
    input_text as _input_text,
    report_warnings,
    terminal_text,
    utf8_error_message,
    warning,
)
from .completion import SHELLS, script
from .crypto import check_passphrase
from .desktop import DESKTOP_ACTIONS, RECIPE_NAMES, run_desktop_command
from .export import BINARY, FORMAT_NAMES, FORMATS, export_bytes, format_for, write_export
from .importing import apply_import, preview_import
from .limits import MAX_NOTE_BYTES
from .links import connection_mark
from .settings import Settings, action_dicts
from .store import (OTHER_WORKSPACE, Vault, parse_calendar_date, read_regular_file, tagged_body,
                    validate_workspace)
from .tasks import due_limit, gather, parse_reference, set_done, short_ids


def doctor_report(vault: Vault, settings_warning: str) -> dict[str, object]:
    return _doctor_report(vault, settings_warning, cli_path=__file__)


def vault_path(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("vault path must not be empty")
    return Path(value)


def windows_console_input() -> bool:
    """Whether stdin is a real Windows console.

    isatty() is also true for the NUL device, so a script run with stdin from
    NUL would otherwise be treated as a person at a terminal and getpass would
    wait on the console forever.
    """
    try:
        # Windows-only APIs; missing on POSIX and on the NUL device.
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        mode = ctypes.c_uint32()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except (AttributeError, ImportError, OSError, ValueError):
        return False


def stdin_is_interactive() -> bool:
    if sys.stdin is None:
        return True
    try:
        interactive = sys.stdin.isatty()
    except ValueError:
        return False
    if interactive and sys.platform == "win32":
        return windows_console_input()
    return interactive


def input_text(args: argparse.Namespace, encoding: str, errors: str) -> str:
    """Text from the command line, or from piped stdin when none was given."""
    return _input_text(args, encoding, errors, interactive=stdin_is_interactive())


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
        raise ValueError(OTHER_WORKSPACE)
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
    try:
        return due_limit(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def calendar_date_argument(value: str) -> date:
    try:
        return parse_calendar_date(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def can_open_editor() -> bool:
    return stdin_is_interactive() and sys.stdout.isatty()


def quick_capture(settings: Settings, daily: bool, workspace: str, when: date | None = None) -> str | None:
    if daily:
        destination = f"daily log · {(when or date.today()).isoformat()} · {workspace}"
    else:
        destination = settings.default_collection + " · " + workspace
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
    parser = argparse.ArgumentParser(prog="jotline", description="Jotline — a terminal home for your thoughts")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--vault", type=vault_path, default=default_vault(), help="Markdown vault directory")
    parser.add_argument("--workspace", help="Workspace name (defaults to the last workspace used in the app)")
    parser.add_argument("--unlock", action="store_true",
                        help="Ask for the encryption passphrase first so encrypted notes are included")
    sub = parser.add_subparsers(dest="command")
    capture = sub.add_parser("capture", help="Capture text, read piped stdin, or open a small editor")
    capture.add_argument("text", nargs="*")
    capture.add_argument("--daily", action="store_true", help="Append to a daily log (today, or --date)")
    capture.add_argument("--date", type=calendar_date_argument, metavar="DATE",
                         help="Daily log date (YYYY-MM-DD, today, or yesterday); requires --daily")
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
    daily = sub.add_parser("daily", help="Open a daily log in the terminal editor")
    daily.add_argument("--date", type=calendar_date_argument, metavar="DATE",
                       help="Log date (YYYY-MM-DD, today, or yesterday); default today")
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
    backlinks = sub.add_parser("backlinks", help="List notes that link here, and outgoing links")
    backlinks.add_argument("id", metavar="NOTE", help=NOTE_HELP)
    backlinks.add_argument("--json", action="store_true", help="Print connections as JSON")
    tasks = sub.add_parser("tasks", help="List open checkbox tasks across notes")
    tasks.add_argument("query", nargs="?", default="", help="Only notes matching this search, such as #work")
    tasks.add_argument("--done", action="store_true", help="Include completed tasks")
    tasks.add_argument("--due", type=due_argument, metavar="DATE",
                       help="Only tasks due on or before DATE (YYYY-MM-DD or today)")
    tasks.add_argument("--json", action="store_true", help="Print tasks as JSON")
    stats = sub.add_parser("stats", help="Print workspace counts without note bodies")
    stats.add_argument("--json", action="store_true", help="Print counts as JSON")
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
    backups = sub.add_parser("backups", help="List local ZIP backups and verify they open")
    backups.add_argument("--json", action="store_true", help="Print backup names and validity as JSON")
    recoveries = sub.add_parser("recoveries", help="List inbox copies saved after an external change")
    recoveries.add_argument("--json", action="store_true", help="Print recovery copies as JSON")
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
    desktop = sub.add_parser("desktop", help="Install a capture launcher or print a desktop recipe")
    desktop.add_argument("action", nargs="?", choices=DESKTOP_ACTIONS, default="status",
                         help="install, uninstall, status, recipe, or launch")
    desktop.add_argument("recipe", nargs="?", choices=RECIPE_NAMES,
                         help="Recipe name when printing a snippet")
    desktop.add_argument("--force", action="store_true",
                         help="Replace an existing capture desktop entry")
    desktop.add_argument("--daily", action="store_true",
                         help="With launch, append to today's log")
    desktop.add_argument("--output", type=Path, help="Write a recipe to this file")
    desktop.add_argument("--json", action="store_true", help="Print status as JSON")
    return parser


@dataclass
class Invocation:
    """What every command handler needs, resolved once by main()."""

    parser: argparse.ArgumentParser
    args: argparse.Namespace
    vault: Vault
    settings: Settings
    settings_warning: str
    workspace: str
    encoding: str
    errors: str


REFUSED_CONTROLS = "Refusing to print terminal controls; redirect stdout or pass --raw"


def save_new_note(run: Invocation, body: str):
    note = run.vault.new(body, workspace=run.workspace)
    note.collection = run.settings.default_collection
    run.vault.save(note)
    return note


def read_note_here(run: Invocation, note_id: str):
    """Read a note a command acts on; it must belong to the active workspace."""
    return run.vault.read(note_id, workspace=run.workspace)


def run_capture(run: Invocation) -> None:
    args, vault, settings = run.args, run.vault, run.settings
    if args.date is not None and not args.daily:
        run.parser.error("--date is only used with --daily")
    when = args.date or date.today()
    if args.daily and vault.has_key() and vault.daily(settings.daily_template, run.workspace, when=when).locked:
        unlock_vault(vault)
    body = input_text(args, run.encoding, run.errors)
    if not body.strip() and not args.text and can_open_editor():
        body = quick_capture(settings, args.daily, run.workspace, when=when if args.daily else None)
        if body is None:
            run.parser.exit(1, "jotline: Nothing captured\n")
    if not body.strip():
        run.parser.error("Provide text or pipe text to jotline capture")
    if args.daily:
        note = vault.append_daily(body, settings.daily_template, run.workspace, when=when)
    else:
        note = save_new_note(run, body)
    print(note.id)


def run_import(run: Invocation) -> None:
    args = run.args
    library = (args.preview or args.apply or args.recursive or args.file.is_dir()
               or args.file.suffix.lower() == ".draftsexport")
    if not library:
        body = decode_input(str(args.file), run.encoding, lambda: read_regular_file(
            args.file, MAX_NOTE_BYTES, ancestor_safe=True, encoding=run.encoding, errors=run.errors))
        print(save_new_note(run, body).id)
        return
    if args.preview and args.apply:
        run.parser.error("Choose --preview or --apply")
    plan = preview_import(run.vault, args.file, run.workspace, run.settings.default_collection,
                          args.duplicates, args.recursive, encoding=run.encoding, errors=run.errors)
    print(plan.summary())
    for item in plan.items:
        decision = "skip" if item.duplicate and plan.duplicates == "skip" else "import"
        print(terminal_text(f"{decision}\t{item.source}\t{item.note.collection}\t{item.note.title}"))
    for message in plan.warnings:
        warning(message)
    if not args.apply:
        print("Preview only. Repeat with --apply to create notes. Originals remain untouched.")
        return
    result = apply_import(run.vault, plan)
    print(result.summary())
    for message in result.errors:
        warning(message)
    if result.errors or plan.warnings:
        raise SystemExit(1)


def run_backup(run: Invocation) -> None:
    print(terminal_text(run.vault.backup()))


def run_backups(run: Invocation) -> None:
    archives = history.list_archives(run.vault)
    if run.args.json:
        print(json.dumps([
            dict(name=archive.name, size=archive.size, valid=archive.valid, reason=archive.reason)
            for archive in archives
        ], ensure_ascii=True))
    elif not archives:
        print("No local ZIP backups yet. Run jotline backup.")
    else:
        for archive in archives:
            status = "ok" if archive.valid else "invalid"
            detail = archive.name if archive.valid else f"{archive.name} ({archive.reason})"
            print(f"{status}\t{terminal_text(detail)}")
    if any(not archive.valid for archive in archives):
        raise SystemExit(1)
    report_warnings(run.vault)


def run_recoveries(run: Invocation) -> None:
    copies = [note for note in run.vault.recoveries() if note.workspace == run.workspace]
    if run.args.json:
        print(json.dumps([
            dict(id=note.id, title=note.title, collection=note.collection,
                 recovery_of=note.recovery_of, created=note.created)
            for note in copies
        ], ensure_ascii=True))
    elif not copies:
        print("No recovery copies in this workspace.")
    else:
        for note in copies:
            print(f"{note.id}\t{note.recovery_of}\t{terminal_text(note.title)}")
    report_warnings(run.vault)


def run_append(run: Invocation) -> None:
    args = run.args
    body = input_text(args, run.encoding, run.errors)
    if not body:
        run.parser.error('Provide text or pipe UTF-8 text to append/prepend')
    note = run.vault.append_note(args.id, body, run.workspace, prepend=args.command == 'prepend',
                                 line_break=not args.no_newline)
    print(note.id)


def run_actions(run: Invocation) -> None:
    actions = action_dicts(run.settings.actions)
    if run.args.json:
        print(json.dumps([dict(name=name, steps=steps) for name, steps in actions.items()], ensure_ascii=True))
    else:
        for name in actions:
            print(name)


def run_action(run: Invocation) -> None:
    args = run.args
    if args.action not in run.settings.actions:
        raise ValueError('Unknown action; use jotline actions')
    note = read_note_here(run, args.id)
    steps = action_dicts({args.action: run.settings.actions[args.action]})[args.action]
    guard_output = sys.stdout.isatty() and not args.raw
    if guard_output and any(step['type'] == 'export' for step in steps):
        # Decide before any step runs, so a refused export cannot leave
        # an append applied and then repeat it on every retry.
        _, effects = preview_action(run.vault, note, steps)
        if any(has_terminal_controls(effect) for effect in effects):
            raise ValueError(REFUSED_CONTROLS)

    def output(body):
        if guard_output and has_terminal_controls(body):
            raise ValueError(REFUSED_CONTROLS)
        sys.stdout.write(body)

    try:
        run_recorded_action(run.vault, note, steps, name=args.action, history_warning=warning, export=output)
    except ActionCommitError as error:
        raise ValueError(f'{error}. Review action history before retrying.') from error
    except (ValueError, OSError) as error:
        raise ValueError(f'Action stopped: {error}. Earlier completed steps remain applied.') from error


def run_list(run: Invocation) -> None:
    args = run.args
    notes = run.vault.search(args.query, workspace=run.workspace)
    if args.json:
        print(json.dumps([dict(id=n.id, title=n.title, collection=n.collection, workspace=n.workspace,
                               created=n.created, updated=n.updated, starred=n.starred, tags=sorted(n.tags),
                               encrypted=n.encrypted)
                          for n in notes], ensure_ascii=True))
    else:
        for note in notes:
            # Escape control characters when printing untrusted note text to a terminal.
            print(f"{note.id}\t{note.collection}\t{terminal_text(note.title)}")
    report_warnings(run.vault)


def run_tag(run: Invocation) -> None:
    note = read_note_here(run, run.args.id)
    note.body = tagged_body(note.body, " ".join(run.args.tags))
    run.vault.save(note)
    print(note.id)


def run_export(run: Invocation) -> None:
    args = run.args
    note = read_note_here(run, args.id)
    fmt = format_for(args.format, args.output)
    if fmt in BINARY and args.output is None:
        raise ValueError(f"{FORMAT_NAMES[fmt]} export needs --output FILE")
    titles = {} if fmt == "markdown" else run.vault.titles(run.workspace)
    if args.output is not None:
        written = write_export(args.output, export_bytes(note.title, note.body, fmt, titles), force=args.force)
        print(terminal_text(written))
        return
    body = note.body if fmt == "markdown" else export_bytes(note.title, note.body, fmt, titles).decode("utf-8")
    if sys.stdout.isatty() and has_terminal_controls(body) and not args.raw:
        raise ValueError(REFUSED_CONTROLS)
    sys.stdout.write(body)


def run_tasks(run: Invocation) -> None:
    args, vault = run.args, run.vault
    notes = vault.search(args.query, workspace=run.workspace)
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
    report_warnings(vault)


def run_done(run: Invocation) -> None:
    args, vault = run.args, run.vault
    reference, line = parse_reference(args.task)
    note_id = resolve_note(vault, reference, run.workspace)
    if vault.read(note_id).locked:
        unlock_vault(vault)
    checked = {}

    def check(body: str) -> str:
        updated, checked["task"] = set_done(body, line, not args.undo)
        return updated

    vault.update_body(note_id, run.workspace, check)
    print(("[ ]" if args.undo else "[x]") + "\t" + terminal_text(checked["task"].text))


def run_sealing(run: Invocation) -> None:
    encrypting = run.args.command == "encrypt"
    if encrypting:
        unlock_vault(run.vault)
    note, changed = run.vault.set_encrypted(run.args.id, run.workspace, encrypting)
    print(note.id)
    if not changed:
        warning("The note was already " + ("encrypted" if encrypting else "stored as plain text"))
    elif encrypting:
        warning("Its unencrypted saved versions were removed; backups made before now still "
                "contain the old text")


def run_encryption(run: Invocation) -> None:
    vault, action = run.vault, run.args.action
    if action == "setup":
        if vault.has_key():
            raise ValueError("Encryption is already set up for this vault; "
                             "use jotline encryption passphrase to change the passphrase")
        vault.setup_encryption(new_passphrase("JOTLINE_PASSPHRASE"))
        print("Encryption is set up. Encrypt a note with: jotline encrypt NOTE")
        warning("There is no way to recover encrypted notes without this passphrase; keep it somewhere safe")
    elif action == "passphrase":
        old = ask_passphrase("Current passphrase: ")
        vault.change_passphrase(old, new_passphrase("JOTLINE_NEW_PASSPHRASE"))
        print("Passphrase changed")
    elif vault.has_key():
        count = sum(note.encrypted for note in vault.notes())
        print(f"Encryption is set up; {count} encrypted note{'' if count == 1 else 's'}")
    else:
        print("Encryption is not set up")


def run_stats(run: Invocation) -> None:
    data = run.vault.stats(run.workspace)
    if run.args.json:
        print(json.dumps(data, ensure_ascii=True))
    else:
        for key in ("workspace", "notes", "inbox", "inbox_captures", "daily_logs",
                    "open_tasks", "tagged", "starred"):
            print(f"{key}\t{data[key]}")
    report_warnings(run.vault)


def run_workspaces(run: Invocation) -> None:
    names = sorted(run.vault.workspaces() | set(run.settings.workspace_names) | {run.workspace})
    if run.args.json:
        print(json.dumps([dict(name=name, active=name == run.workspace) for name in names]))
    else:
        for name in names:
            print(name + (" *" if name == run.workspace else ""))
    report_warnings(run.vault)


def run_backlinks(run: Invocation) -> None:
    note = read_note_here(run, run.args.id)
    info = run.vault.connections(note)
    if run.args.json:
        print(json.dumps({
            "id": note.id,
            "title": note.title,
            "locked": info.locked,
            "incoming": [item.as_dict() for item in info.incoming],
            "outgoing": [item.as_dict() for item in info.outgoing],
        }, ensure_ascii=True))
    else:
        if info.locked:
            print("Encrypted note (locked). Unlock with --unlock to see outgoing links.")
        if not info.incoming and not info.outgoing:
            print("No links yet")
        for item in info.incoming:
            print("\t".join(terminal_text(field) for field in
                            ("←", item.note_id or "-", item.title, item.snippet)))
        for item in info.outgoing:
            print("\t".join(terminal_text(field) for field in
                            (connection_mark(item.status), item.note_id or item.target,
                             item.title or item.status, item.snippet)))
    report_warnings(run.vault)


def run_tags(run: Invocation) -> None:
    counts = sorted(run.vault.tags(run.workspace).items())
    if run.args.json:
        print(json.dumps([dict(tag=tag, count=count) for tag, count in counts], ensure_ascii=True))
    else:
        for tag, count in counts:
            print(f"#{tag}\t{count}")
    report_warnings(run.vault)


def run_doctor(run: Invocation) -> None:
    report = doctor_report(run.vault, run.settings_warning)
    if run.args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_doctor(report)
    if report["warnings"]:
        run.parser.exit(1)


def run_app(run: Invocation) -> None:
    if run.args.command == "daily":
        when = run.args.date or date.today()
        note = run.vault.daily(run.settings.daily_template, run.workspace, when=when)
        if note.locked:
            unlock_vault(run.vault)
            note = run.vault.daily(run.settings.daily_template, run.workspace, when=when)
        initial_note = note
    elif run.args.command == "open":
        initial_note = read_note_here(run, run.args.id)
    else:
        initial_note = None
    Jotline(run.vault, workspace=run.workspace, initial_note=initial_note).run()


COMMANDS = {
    "capture": run_capture, "import": run_import, "backup": run_backup,
    "backups": run_backups, "recoveries": run_recoveries,
    "append": run_append, "prepend": run_append, "actions": run_actions, "run": run_action,
    "list": run_list, "tag": run_tag, "export": run_export, "backlinks": run_backlinks,
    "tasks": run_tasks, "done": run_done, "stats": run_stats, "daily": run_app,
    "encrypt": run_sealing, "decrypt": run_sealing, "encryption": run_encryption,
    "workspaces": run_workspaces, "tags": run_tags, "doctor": run_doctor,
    "open": run_app, None: run_app,
}
# Commands that only read must not turn a mistyped path into a new vault.
READ_ONLY_COMMANDS = {"list", "actions", "export", "workspaces", "tags", "tasks", "doctor",
                      "stats", "backlinks", "backups", "recoveries"}


def prepare(parser: argparse.ArgumentParser, args: argparse.Namespace) -> Invocation:
    """Open the vault and settings, unlock when asked, and resolve the note a command names."""
    vault = Vault(args.vault, create=args.command not in READ_ONLY_COMMANDS)
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
    return Invocation(parser, args, vault, settings, settings_warning, workspace,
                      encoding=getattr(args, "encoding", "utf-8"),
                      errors="replace" if getattr(args, "replace_invalid", False) else "strict")


def main() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", newline="")
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "path":
            print(terminal_text(args.vault.expanduser().resolve()))
            return
        if args.command == "completion":
            sys.stdout.write(script(args.shell, parser))
            return
        if args.command == "desktop":
            run_desktop_command(args)
            return
        run = prepare(parser, args)
        COMMANDS[args.command](run)
        if run.vault.backup_warning:
            warning(run.vault.backup_warning)
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
