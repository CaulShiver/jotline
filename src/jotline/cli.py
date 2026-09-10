"""Launch the workspace or capture text without leaving your shell."""
import argparse
import os
from pathlib import Path
import sys

from . import __version__
from .store import Vault
from .settings import Settings


def default_vault() -> Path:
    override = os.environ.get("JOTLINE_VAULT")
    if override:
        return Path(override)
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "jotline/notes"


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
    sub.add_parser("path", help="Print the vault path")
    args = parser.parse_args()
    try:
        vault = Vault(args.vault)
        if args.command == "path":
            print(vault.path)
        elif args.command == "capture":
            body = " ".join(args.text) if args.text else (sys.stdin.read() if not sys.stdin.isatty() else "")
            if not body.strip():
                parser.error("Provide text or pipe text to jotline capture")
            settings, warning = Settings.load(vault.path / '.jotline-settings.json')
            if warning:
                print(warning, file=sys.stderr)
            if args.daily:
                note = vault.daily(settings.daily_template)
                note.body = note.body.rstrip() + "\n\n" + body + "\n"
            else:
                note = vault.new(body)
                note.collection = settings.default_collection
            vault.save(note)
            print(note.id)
        elif args.command == "list":
            for note in vault.search(args.query):
                # Escape control characters when printing untrusted note text to a terminal.
                title = "".join(c if c.isprintable() else " " for c in note.title)
                print(f"{note.id}\t{note.collection}\t{title}")
            for warning in vault.warnings:
                print(f"warning: {warning!r}", file=sys.stderr)
        elif args.command == "export":
            sys.stdout.write(vault.read(args.id).body)
        else:
            from .app import Jotline
            Jotline(vault).run()
    except (OSError, ValueError) as error:
        parser.exit(1, f"jotline: {error}\n")


if __name__ == "__main__":
    main()
