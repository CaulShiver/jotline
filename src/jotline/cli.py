"""Launch the workspace or capture text without leaving your shell."""
import argparse
from collections import Counter
import os
from pathlib import Path
import sys

from . import __version__
from .store import MAX_NOTE_BYTES, Vault, read_regular_file
from .settings import Settings


def default_vault() -> Path:
    override = os.environ.get("JOTLINE_VAULT")
    if override:
        return Path(override)
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "jotline/notes"


def terminal_text(value: object) -> str:
    """Render diagnostics without allowing note or filename controls to affect a terminal."""
    return "".join(character if character.isprintable() else
                   character.encode("unicode_escape").decode("ascii")
                   for character in str(value))


def warning(value: object) -> None:
    print(f"warning: {terminal_text(value)}", file=sys.stderr)


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
    parser = argparse.ArgumentParser(description="Jotline — a terminal home for your thoughts")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--vault", type=Path, default=default_vault(), help="Markdown vault directory")
    sub = parser.add_subparsers(dest="command")
    capture = sub.add_parser("capture", help="Capture text, or read piped stdin")
    capture.add_argument("text", nargs="*")
    capture.add_argument("--daily", action="store_true", help="Append to today's log")
    listing = sub.add_parser("list", help="Find notes")
    listing.add_argument("query", nargs="?", default="")
    export = sub.add_parser("export", help="Write a note's Markdown body to stdout")
    export.add_argument("id")
    export.add_argument("--raw", action="store_true", help="Allow terminal control characters on an interactive terminal")
    sub.add_parser("path", help="Print the vault path")
    sub.add_parser("doctor", help="Check the vault for unreadable Markdown files")
    importing = sub.add_parser("import", help="Copy a UTF-8 Markdown file into the vault")
    importing.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        vault = Vault(args.vault)
        if args.command == "path":
            print(terminal_text(vault.path))
        elif args.command == "capture":
            body = " ".join(args.text) if args.text else (read_capture_input() if not sys.stdin.isatty() else "")
            if not body.strip():
                parser.error("Provide text or pipe text to jotline capture")
            settings, settings_warning = Settings.load(vault.path / '.jotline-settings.json')
            if settings_warning:
                warning(settings_warning)
            if args.daily:
                note = vault.append_daily(body, settings.daily_template)
            else:
                note = vault.new(body)
                note.collection = settings.default_collection
                vault.save(note)
            print(note.id)
        elif args.command == "list":
            for note in vault.search(args.query):
                # Escape control characters when printing untrusted note text to a terminal.
                title = terminal_text(note.title)
                print(f"{note.id}\t{note.collection}\t{title}")
            for item in vault.warnings:
                warning(item)
        elif args.command == "export":
            body = vault.read(args.id).body
            if sys.stdout.isatty() and has_terminal_controls(body) and not args.raw:
                raise ValueError("Refusing to print terminal controls interactively; redirect stdout or pass --raw")
            sys.stdout.write(body)
        elif args.command == "doctor":
            notes = vault.notes()
            _, settings_warning = Settings.load(vault.path / '.jotline-settings.json')
            collections = Counter(note.collection for note in notes)
            warnings = [*vault.warnings]
            if settings_warning:
                warnings.append(f"settings: {settings_warning}")
            print(f"Vault: {terminal_text(vault.path)}")
            print(f"Readable notes: {len(notes)}")
            print("Collections: " + ", ".join(f"{name}={collections[name]}" for name in sorted(collections)))
            print(f"Warnings: {len(warnings)}")
            for item in warnings:
                warning(item)
            if warnings:
                parser.exit(1)
        elif args.command == "import":
            body = read_regular_file(args.file, MAX_NOTE_BYTES)
            settings, settings_warning = Settings.load(vault.path / '.jotline-settings.json')
            if settings_warning:
                warning(settings_warning)
            note = vault.new(body)
            note.collection = settings.default_collection
            vault.save(note)
            print(note.id)
        else:
            from .app import Jotline
            Jotline(vault).run()
    except (OSError, ValueError) as error:
        parser.exit(1, f"jotline: {terminal_text(error)}\n")


if __name__ == "__main__":
    main()
