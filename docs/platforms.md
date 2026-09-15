# Supported platforms

Jotline’s supported operating systems are **Linux, macOS, and Windows**.

Windows is a supported platform, not an optional CI target. Native Windows
Terminal is part of the product; WSL is optional. Do not drop Windows to make a
GitHub tag publishable.

The same pure-Python wheel (`py3-none-any`) runs on all three. Python 3.11, 3.12,
or 3.13 is required, plus a terminal with Unicode and color.

## What a tagged release must prove

Publication is gated on `ubuntu-latest`, `macos-latest`, and `windows-latest` ×
Python 3.11–3.13 (nine jobs), then an installed-wheel smoke on each OS through
`scripts/install.py`. POSIX PTY smoke runs on Linux during the tag job. A failed
Windows job blocks the GitHub Release; it does not remove the platform.

## Default vault locations

| Platform | Default notes folder |
| --- | --- |
| Linux | `~/.local/share/jotline/notes` |
| macOS | `~/Library/Application Support/jotline/notes` |
| Windows | `%LOCALAPPDATA%\jotline\notes` |

Override with `JOTLINE_VAULT` or `--vault`. Use a local filesystem with
hard-link support (NTFS, APFS, ext4). Windows rejects symlinks, junctions, and
other reparse points inside the vault.

## Known limitations (not platform removals)

- Headless CI cannot certify native clipboard, IME, or screen readers. Record
  those with [the terminal checklist](terminal-testing.md).
- PDF export needs a local Chromium-based browser, Edge, LibreOffice, or pandoc.
- Omarchy desktop theme follow is a Linux desktop integration; Windows and macOS
  use Jotline’s built-in themes.
- POSIX PTY smoke is Unix-only; Windows uses the installed-wheel TUI smoke.

See [install, update and uninstall](install.md) for the one-liner that does not
require hunting a wheel.
