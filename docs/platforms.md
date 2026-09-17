# Supported platforms

Jotline’s supported operating systems are **Linux and macOS**.

Windows is out of scope. Native Windows Terminal, PowerShell installers, and
the Windows CI matrix are not part of the product. WSL is not a supported
target; use Linux or macOS.

The same pure-Python wheel (`py3-none-any`) runs on both supported systems.
Python 3.11, 3.12, or 3.13 is required, plus a terminal with Unicode and color.
On Windows, `jotline` and `scripts/install.py` exit with a short unsupported
message.

## What a tagged release must prove

Publication is gated on `ubuntu-latest` and `macos-latest` × Python 3.11–3.13
(six jobs), then an installed-wheel smoke on each OS through
`scripts/install.py`. POSIX PTY smoke runs on Linux during the tag job. A failed
job blocks the GitHub Release.

## Default vault locations

| Platform | Default notes folder |
| --- | --- |
| Linux | `~/.local/share/jotline/notes` |
| macOS | `~/Library/Application Support/jotline/notes` |

Override with `JOTLINE_VAULT` or `--vault`. Use a local filesystem with
hard-link support (APFS, ext4).

## Known limitations

- Headless CI cannot certify native clipboard, IME, or screen readers. Record
  those with [the terminal checklist](terminal-testing.md).
- PDF export needs a local Chromium-based browser, LibreOffice, or pandoc.
- Omarchy desktop theme follow is a Linux desktop integration; macOS uses
  Jotline’s built-in themes.
- POSIX PTY smoke is Unix-only and runs on the Linux tag job.

See [install, update and uninstall](install.md) for the one-liner that does not
require hunting a wheel.
