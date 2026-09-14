"""Process entry: refuse unsupported platforms before importing storage."""
from __future__ import annotations

import sys

UNSUPPORTED_WINDOWS = "Jotline supports Linux and macOS only for now. Windows is out of scope."


def main() -> None:
    if sys.platform == "win32":
        print(UNSUPPORTED_WINDOWS, file=sys.stderr)
        raise SystemExit(2)
    # Storage imports POSIX-only APIs; keep that off the Windows refusal path.
    from .cli import main as run_cli

    run_cli()
