"""Launch the workspace or capture text without leaving your shell.

Textual is imported where a screen is actually drawn, not at the top of this
module. It costs about 0.3 of the 0.4 seconds a bare `jotline capture` used to
take, and capture is bound to a desktop hotkey: that is the gap between the
key press and the thought being caught. `list`, `tasks`, `backlinks`, `stats`
and `done` never draw anything at all and were paying it too.
"""
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
from .cli_doctor import (
    doctor_report as _doctor_report,
    missing_vault_report,
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
from .fuzzy import match as fuzzy_match
from .importing import apply_import, preview_import
from .limits import MAX_NOTE_BYTES
from .links import connection_mark
from .settings import Settings, action_dicts
from .store import (OTHER_WORKSPACE, Vault, parse_calendar_date, read_regular_file, tagged_body,
                    validate_workspace)
from .sync import sync_guide
from .tasks import due_limit, gather, parse_reference, set_done, short_ids


def doctor_report(vault: Vault, settings_warning: str) -> dict[str, object]:
    return _doctor_report(vault, settings_warning, cli_path=__file__)


def no_vault_message(path: Path) -> str:
    return f"No vault yet at {path}; it is created on first capture or launch"


def interactive_note(message: str) -> None:
    """Say why the output is empty, on stderr and only to a person at a terminal."""
    if sys.stdout.isatty():
        print(terminal_text(message), file=sys.stderr)


def vault_path(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("vault path must not be empty")
    return Path(value)


WINDOWS_UNSUPPORTED = "Jotline supports Linux and macOS only. Windows is out of scope."


def stdin_is_interactive() -> bool:
    if sys.stdin is None:
        return True
    try:
        return sys.stdin.isatty()
    except ValueError:
        return False


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


# How far the best fuzzy title match must lead the next one to be opened unasked.
CLEAR_LEAD = 1.5


def fuzzy_note(vault: Vault, reference: str, workspace: str, missing: NoMatchingNote) -> str:
    """The one note whose title clearly matches, or the top candidates on stderr."""
    terms = reference.casefold().split()
    notes = [note for note in vault.notes()
             if note.collection != "trash" and note.workspace == workspace and not note.locked]
    scored = sorted(((score, note) for note in notes if (score := fuzzy_match(terms, note.title)[0])),
                    key=lambda item: (-item[0], item[1].title))
    if not scored:
        raise missing
    if len(scored) == 1 or scored[0][0] >= scored[1][0] * CLEAR_LEAD:
        return scored[0][1].id
    prefixes = short_ids(note.id for note in vault.notes())
    for _, note in scored[:5]:
        print(terminal_text(f"  {prefixes[note.id]}  {note.title}"), file=sys.stderr)
    more = f" (showing 5 of {len(scored)})" if len(scored) > 5 else ""
    raise ValueError(f"{reference} matches several titles{more}; run jotline open with one of these IDs")


PASSPHRASE_NEEDED = ("This needs the passphrase for encrypted notes; run it in a terminal, "
                     "or set JOTLINE_PASSPHRASE for scripts")


def terminal_available() -> bool:
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
    from .capture_ui import QuickCapture  # Deferred: see the note on run_workspace.

    if daily:
        destination = f"daily log · {(when or date.today()).isoformat()} · {workspace}"
    else:
        destination = settings.default_collection + " · " + workspace
    return QuickCapture(destination, settings.theme).run()


def missing_file_message(args: argparse.Namespace, error: FileNotFoundError) -> str:
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


class Parser(argparse.ArgumentParser):
    # argparse builds messages such as "unrecognized arguments" from raw argv.
    # Subparsers inherit this class, so every usage error goes through here.
    def error(self, message: str):
        super().error(terminal_text(message))


DESCRIPTION = ("Jotline — a terminal home for your thoughts. Run it with no command to open\n"
               "the workspace, or use a command below from your shell and scripts.")
EPILOG = """\
commands by task:
  Capture          capture, append, prepend, daily
  Find             list (or search), open, backlinks, tags, workspaces
  Tasks            tasks, done
  Notes            tag, actions, run, encrypt, decrypt
  Export & import  export, import
  Vault care       backup, backups, recoveries, doctor, stats, encryption
  Setup            path, sync, completion, desktop

examples:
  jotline capture "Call Sam about the venue #work"
  echo "half an idea" | jotline capture --daily
  jotline search venue
  jotline open venue
  jotline tasks --due today
  jotline export last -o plan.pdf

Global options such as --vault and --workspace work before or after the command.
Run jotline COMMAND --help for a command's own options."""

CAPTURE_DESCRIPTION = ("Save text as a new note in your default collection, or add it to a daily log with --daily. "
                       "With no text, piped stdin is read; at a terminal with nothing piped, a small editor opens.")


def add_global_options(container, *, defaults: bool) -> None:
    """Options accepted before the command, and again after it, where only a value actually given counts."""
    def default(value):
        return value if defaults else argparse.SUPPRESS

    container.add_argument("--vault", type=vault_path, default=default(default_vault()),
                           help="Markdown vault directory")
    container.add_argument("--workspace", default=default(None),
                           help="Workspace name (defaults to the last workspace used in the app)")
    container.add_argument("--new-workspace", action="store_true", default=default(False),
                           help="Let --workspace name a workspace that does not exist yet")
    container.add_argument("--unlock", action="store_true", default=default(False),
                           help="Ask for the encryption passphrase first so encrypted notes are included")


COMMAND_ALIASES = {"search": "list"}


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="jotline", description=DESCRIPTION, epilog=EPILOG,
                    formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=__version__)
    add_global_options(parser, defaults=True)
    shared = argparse.ArgumentParser(add_help=False)
    add_global_options(shared.add_argument_group("global options"), defaults=False)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    def add_command(name, **options):
        # Every command also takes the global options, and describes itself in its own --help.
        options.setdefault("description", options.get("help"))
        return commands.add_parser(name, parents=[shared], **options)

    parser.command_parsers = commands.choices
    capture = add_command("capture", help="Capture text, read piped stdin, or open a small editor",
                          description=CAPTURE_DESCRIPTION)
    capture.add_argument("text", nargs="*",
                         help="Text to save; the words are joined with spaces. Omit it to read piped stdin")
    capture.add_argument("--daily", action="store_true", help="Append to a daily log (today, or --date)")
    capture.add_argument("--date", type=calendar_date_argument, metavar="DATE",
                         help="Daily log date (YYYY-MM-DD, today, or yesterday); requires --daily")
    add_encoding_options(capture)
    listing = add_command("list", aliases=["search"], help="Find notes")
    listing.add_argument("query", nargs="?", default="")
    listing.add_argument("--json", action="store_true", help="Print note metadata as JSON")
    for command in ('append', 'prepend'):
        update = add_command(command, help=f'{command.title()} text to an existing note')
        update.add_argument('id', metavar='NOTE', help=NOTE_HELP)
        update.add_argument('text', nargs='*')
        update.add_argument('--no-newline', action='store_true',
                            help='Join the text exactly, without adding a line break')
        add_encoding_options(update)
    opening = add_command('open', help='Open a note in the terminal editor')
    opening.add_argument('id', metavar='NOTE', help=NOTE_HELP)
    daily = add_command("daily", help="Open a daily log in the terminal editor")
    daily.add_argument("--date", type=calendar_date_argument, metavar="DATE",
                       help="Log date (YYYY-MM-DD, today, or yesterday); default today")
    actions = add_command('actions', help='List local actions')
    actions.add_argument("--json", action="store_true", help="Print action names and steps as JSON")
    action = add_command('run', help='Run a named local action on a note')
    action.add_argument('action')
    action.add_argument('id', metavar='NOTE', help=NOTE_HELP)
    action.add_argument('--raw', action='store_true', help='Allow terminal control characters in exported output')
    export = add_command("export", help="Write a note's Markdown to stdout, or save it as HTML, Word or PDF")
    export.add_argument("id", metavar="NOTE", help=NOTE_HELP)
    export.add_argument("--format", choices=FORMATS,
                        help="markdown (default), html, docx or pdf; guessed from the --output file extension")
    export.add_argument("-o", "--output", type=Path, help="Write this file instead of stdout; needed for docx and pdf")
    export.add_argument("--force", action="store_true", help="Replace the output file if it already exists")
    export.add_argument("--raw", action="store_true", help="Allow terminal control characters on an interactive terminal")
    workspaces = add_command("workspaces", help="List workspaces")
    workspaces.add_argument("--json", action="store_true", help="Print workspaces as JSON")
    tag_list = add_command("tags", help="List tags and note counts in this workspace")
    tag_list.add_argument("--json", action="store_true", help="Print tags and counts as JSON")
    tagging = add_command("tag", help="Add inline tags to a note")
    tagging.add_argument("id", metavar="NOTE", help=NOTE_HELP)
    tagging.add_argument("tags", nargs="+")
    backlinks = add_command("backlinks", help="List notes that link here, and outgoing links")
    backlinks.add_argument("id", metavar="NOTE", help=NOTE_HELP)
    backlinks.add_argument("--json", action="store_true", help="Print connections as JSON")
    tasks = add_command("tasks", help="List open checkbox tasks across notes")
    tasks.add_argument("query", nargs="?", default="", help="Only notes matching this search, such as #work")
    tasks.add_argument("--done", action="store_true", help="Include completed tasks")
    tasks.add_argument("--due", type=due_argument, metavar="DATE",
                       help="Only tasks due on or before DATE (YYYY-MM-DD or today)")
    tasks.add_argument("--json", action="store_true", help="Print tasks as JSON")
    stats = add_command("stats", help="Print workspace counts without note bodies")
    stats.add_argument("--json", action="store_true", help="Print counts as JSON")
    finish = add_command("done", help="Check off a task listed by jotline tasks")
    finish.add_argument("task", metavar="NOTE:LINE", help="The reference printed by jotline tasks")
    finish.add_argument("--undo", action="store_true", help="Mark the task as not done again")
    for command, text in (("encrypt", "Encrypt a note's text on disk"),
                          ("decrypt", "Store an encrypted note as plain text again")):
        sealing = add_command(command, help=text)
        sealing.add_argument("id", metavar="NOTE", help=NOTE_HELP)
    encryption = add_command("encryption", help="Set up encryption, change its passphrase, or show status")
    encryption.add_argument("action", choices=("status", "setup", "passphrase"))
    add_command("backup", help="Back up notes, settings and templates to a local ZIP")
    backups = add_command("backups", help="List local ZIP backups and verify they open")
    backups.add_argument("--json", action="store_true", help="Print backup names and validity as JSON")
    recoveries = add_command("recoveries", help="List inbox copies saved after an external change")
    recoveries.add_argument("--json", action="store_true", help="Print recovery copies as JSON")
    add_command("path", help="Print the vault path")
    doctor = add_command("doctor", help="Check the vault, runtime and local Jotline state")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable diagnostics")
    syncing = add_command("sync", help="Print a Git or Syncthing recipe for this vault (not a Jotline cloud)")
    syncing.add_argument("tool", nargs="?", choices=("git", "syncthing"),
                         help="Show only the Git or Syncthing recipe")
    importing = add_command("import", help="Import UTF-8 text, a folder, or a Drafts export")
    importing.add_argument("file", type=Path)
    import_mode = importing.add_mutually_exclusive_group()
    import_mode.add_argument("--preview", action="store_true", help="Preview without creating notes")
    import_mode.add_argument("--apply", action="store_true", help="Apply a folder or Drafts import after reviewing preview")
    importing.add_argument("--recursive", action="store_true", help="Include subfolders without following links")
    importing.add_argument("--duplicates", choices=("skip", "copy"), default="skip",
                           help="Skip matching bodies/UUIDs (default), or create separate copies")
    add_encoding_options(importing)
    completion = add_command("completion", help="Print a shell completion script")
    completion.add_argument("shell", choices=SHELLS)
    desktop = add_command("desktop", help="Install a capture launcher or print a desktop recipe")
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
    vault: Vault | None  # None for a read command before the vault folder exists
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
    if not sys.stdout.isatty():
        print(note.id)
    elif args.daily:
        print(f"Added to daily log {when.isoformat()}")
    else:
        print(terminal_text(f"Saved to {note.collection}: {note.title} ({note.id[:8]})"))


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
        print("\t".join(terminal_text(field) for field in (decision, item.source, item.note.collection,
                                                           item.note.title)))
    for message in plan.warnings:
        warning(message)
    if not args.apply:
        print("Preview only. Repeat with --apply to create notes. Originals remain untouched.")
        return
    result = apply_import(run.vault, plan)
    print(result.summary())
    for message in result.errors:
        warning(message)
    # Warnings alone are printed above; the import failed only if a write did or nothing could be imported.
    if result.errors or (plan.needs_review and not result.imported):
        raise SystemExit(1)


def run_backup(run: Invocation) -> None:
    print(terminal_text(run.vault.backup()))


def run_backups(run: Invocation) -> None:
    archives = history.list_archives(run.vault)
    # A quarantined daily archive was already replaced, so it is listed for the
    # record but does not fail the command the way an invalid live archive does.
    quarantined = history.list_quarantined(run.vault)
    if run.args.json:
        print(json.dumps([
            dict(name=archive.name, size=archive.size, valid=archive.valid, reason=archive.reason,
                 quarantined=False)
            for archive in archives
        ] + [
            dict(name=name, size=None, valid=False, reason="set aside after failing validation",
                 quarantined=True)
            for name in quarantined
        ], ensure_ascii=True))
    elif not archives and not quarantined:
        print("No local ZIP backups yet. Run jotline backup.")
    else:
        for archive in archives:
            status = "ok" if archive.valid else "invalid"
            detail = archive.name if archive.valid else f"{archive.name} ({archive.reason})"
            print(f"{status}\t{terminal_text(detail)}")
        for name in quarantined:
            print(f"quarantined\t{terminal_text(name)}")
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


NO_ACTIONS = "No local actions yet; see docs/actions.md"


def run_actions(run: Invocation) -> None:
    actions = action_dicts(run.settings.actions)
    if run.args.json:
        print(json.dumps([dict(name=name, steps=steps) for name, steps in actions.items()], ensure_ascii=True))
    else:
        for name in actions:
            print(name)
        if not actions:
            interactive_note(NO_ACTIONS)


def run_action(run: Invocation) -> None:
    args = run.args
    if not run.settings.actions:
        raise ValueError(NO_ACTIONS + " to add one")
    if args.action not in run.settings.actions:
        raise ValueError('Unknown action; use jotline actions to list them')
    note = read_note_here(run, args.id)
    steps = action_dicts({args.action: run.settings.actions[args.action]})[args.action]
    guard_output = sys.stdout.isatty() and not args.raw
    if guard_output and any(step['type'] == 'export' for step in steps):
        # Decide before any step runs, so a refused export cannot leave
        # an append applied and then repeat it on every retry. Check what
        # would actually be written: the effect strings stop at 20,000
        # characters, so a control character past that was invisible here
        # and the append committed anyway, once more on each retry.
        printed = []
        preview_action(run.vault, note, steps, printed=printed)
        if any(has_terminal_controls(body) for body in printed):
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
        if not notes:
            interactive_note(f"No notes match {args.query}" if args.query.strip()
                             else f"No notes in workspace {run.workspace} yet; add one with jotline capture")
    report_warnings(run.vault)


def run_tag(run: Invocation) -> None:
    tags = " ".join(run.args.tags)
    note = run.vault.update_body(run.args.id, run.workspace, lambda body: tagged_body(body, tags))
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
        if not found:
            interactive_note(("No tasks" if args.done else "No open tasks")
                             + (f" due by {args.due}" if args.due else "")
                             + (f" in notes matching {args.query}" if args.query.strip() else ""))
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


STAT_KEYS = ("workspace", "notes", "inbox", "inbox_captures", "daily_logs", "open_tasks", "tagged", "starred")


def print_stats(data: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=True))
    else:
        for key in STAT_KEYS:
            print(f"{key}\t{data[key]}")


def run_stats(run: Invocation) -> None:
    print_stats(run.vault.stats(run.workspace), run.args.json)
    report_warnings(run.vault)


def known_workspaces(vault: Vault | None, settings: Settings, workspace: str) -> set[str]:
    """Workspaces the app lists: any with notes, any created in the app, the active one and default."""
    return ({"default", workspace, settings.active_workspace, *settings.workspace_names}
            | (vault.workspaces() if vault is not None else set()))


def print_workspaces(names: list[str], active: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps([dict(name=name, active=name == active) for name in names]))
    else:
        for name in names:
            print(name + (" *" if name == active else ""))


def run_workspaces(run: Invocation) -> None:
    print_workspaces(sorted(run.vault.workspaces() | set(run.settings.workspace_names) | {run.workspace}),
                     run.workspace, run.args.json)
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
        if not counts:
            interactive_note(f"No tags in workspace {run.workspace} yet")
    report_warnings(run.vault)


def run_doctor(run: Invocation) -> None:
    report = doctor_report(run.vault, run.settings_warning)
    if run.args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_doctor(report)
    if report["warnings"]:
        run.parser.exit(1)


def run_without_vault(run: Invocation) -> None:
    """A read command before the first capture: an empty result, and no folder created."""
    args, command = run.args, run.args.command
    path = args.vault.expanduser().resolve()
    if command == "doctor":
        if args.json:
            print(json.dumps(missing_vault_report(path, cli_path=__file__), sort_keys=True))
        else:
            print(terminal_text(no_vault_message(path)))
        return
    if command in ("export", "backlinks"):
        raise NoMatchingNote(f"No note with ID or title {args.id}; there is no vault yet at {path}")
    if command == "actions":
        run_actions(run)
        return
    if command == "stats":
        print_stats(dict.fromkeys(STAT_KEYS, 0) | {"workspace": run.workspace}, args.json)
    elif command == "workspaces":
        print_workspaces(sorted(known_workspaces(None, run.settings, run.workspace)), run.workspace, args.json)
    elif args.json:
        print("[]")
    elif command == "backups":
        print("No local ZIP backups yet. Run jotline backup.")
    elif command == "recoveries":
        print("No recovery copies in this workspace.")
    interactive_note(no_vault_message(path))


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
    from .app import Jotline  # Deferred: see the note on this module's imports.

    Jotline(run.vault, workspace=run.workspace, initial_note=initial_note,
            first_run=run.args.command is None).run()


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
# Commands that do not look inside a workspace, so --workspace is not checked for them.
ANY_WORKSPACE_COMMANDS = {"actions", "backup", "backups", "doctor", "encryption"}


def check_workspace(args: argparse.Namespace, vault: Vault | None, settings: Settings) -> str:
    """The workspace a command uses; a mistyped --workspace must not quietly start a new one."""
    if args.workspace is None:
        return validate_workspace(settings.active_workspace)
    name = validate_workspace(args.workspace)
    if (args.new_workspace or args.command in ANY_WORKSPACE_COMMANDS
            or name in known_workspaces(vault, settings, settings.active_workspace)):
        return name
    hint = "" if args.command in READ_ONLY_COMMANDS else ", or pass --new-workspace to start it"
    raise ValueError(f"No workspace named {name}; run jotline workspaces{hint}")


def prepare(parser: argparse.ArgumentParser, args: argparse.Namespace) -> Invocation:
    """Open the vault and settings, unlock when asked, and resolve the note a command names."""
    folder = args.vault.expanduser()
    if folder.exists() and not folder.is_dir():
        raise ValueError(f"{folder} is a file, not a vault folder")
    if args.command in READ_ONLY_COMMANDS and not folder.exists():
        settings = Settings()
        return Invocation(parser, args, None, settings, "", check_workspace(args, None, settings),
                          encoding="utf-8", errors="strict")
    vault = Vault(args.vault, create=args.command not in READ_ONLY_COMMANDS)
    # Shell captures can wait; only the interactive app needs a short lock timeout.
    vault.lock_timeout = 10.0
    settings, settings_warning = Settings.load(vault.path / ".jotline-settings.json")
    validate_workspace(settings.active_workspace if args.workspace is None else args.workspace)
    if settings_warning and args.command not in (None, "doctor"):
        warning(settings_warning)
    passphrase_failed = False
    if args.command != "encryption":
        if args.unlock:
            unlock_vault(vault)
        elif os.environ.get("JOTLINE_PASSPHRASE") and vault.has_key():
            # Only a command that reaches an encrypted note needs the key; it asks again and fails then.
            try:
                unlock_vault(vault)
            except ValueError as error:
                passphrase_failed = True
                warning(f"JOTLINE_PASSPHRASE did not unlock the vault ({error}); encrypted notes stay locked")
    workspace = check_workspace(args, vault, settings)
    if getattr(args, "id", None) is not None:
        reference = args.id
        try:
            try:
                args.id = resolve_note(vault, reference, workspace)
            except NoMatchingNote:
                # Locked notes' titles are sealed; unlock and look again when that is possible.
                if (passphrase_failed or vault.cipher is not None or not vault.has_key()
                        or not can_ask_passphrase() or not any(note.locked for note in vault.notes())):
                    raise
                unlock_vault(vault)
                args.id = resolve_note(vault, reference, workspace)
        except NoMatchingNote as missing:
            if args.command != "open":
                raise
            args.id = fuzzy_note(vault, reference, workspace, missing)
        if vault.read(args.id).locked:
            unlock_vault(vault)
    return Invocation(parser, args, vault, settings, settings_warning, workspace,
                      encoding=getattr(args, "encoding", "utf-8"),
                      errors="replace" if getattr(args, "replace_invalid", False) else "strict")


def main() -> None:
    if sys.platform == "win32":
        print(WINDOWS_UNSUPPORTED, file=sys.stderr)
        raise SystemExit(2)
    parser = build_parser()
    args, extras = parser.parse_known_args()
    args.command = COMMAND_ALIASES.get(args.command, args.command)
    # A usage error shows the usage of the command it is about, not every command.
    command_parser = parser.command_parsers.get(args.command, parser)
    if extras:
        command_parser.error("unrecognized arguments: " + " ".join(extras))
    try:
        if args.command == "path":
            print(terminal_text(args.vault.expanduser().resolve()))
            return
        if args.command == "sync":
            print(sync_guide(args.vault, args.tool).rstrip())
            return
        if args.command == "completion":
            sys.stdout.write(script(args.shell, parser))
            return
        if args.command == "desktop":
            run_desktop_command(args)
            return
        run = prepare(command_parser, args)
        if run.vault is None:
            run_without_vault(run)
            return
        COMMANDS[args.command](run)
        if run.vault.backup_warning:
            warning(run.vault.backup_warning)
    except BrokenPipeError:
        # The reader closed early (for example `jotline list | head`); that is
        # not an error, and Python must not print one while flushing at exit.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        raise SystemExit(0) from None
    except UnicodeDecodeError as error:
        parser.exit(1, f"jotline: {utf8_error_message(error)}\n")
    except FileNotFoundError as error:
        parser.exit(1, f"jotline: {missing_file_message(args, error)}\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"jotline: {terminal_text(error)}\n")


if __name__ == "__main__":
    main()
