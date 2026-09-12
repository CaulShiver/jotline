Jotline 0.9.2 is a hardening release from a four-reviewer red team of 0.9.1.
Thirty-three confirmed defects were fixed; the full report is in
`docs/redteam-2026-09-12.md` and every fix has a regression test.

The most important repairs protect your text:

- Saving on a drive that refuses hard links (FAT/exFAT media, SMB shares,
  shared folders) no longer leaves the note under a hidden name.
- A daily backup that cannot be written (full disk) no longer blocks saves or
  recovery copies.
- One invalid settings value no longer discards actions, saved views, hotkeys
  and other preferences on the next save.
- Opening a note with unusual line separators, lone CR or mixed newlines no
  longer rewrites it or raises a false external-change dialog; task toggle and
  formatting no longer crash on CR notes or corrupt CRLF notes.
- A second Enter or a double-click on a dialog no longer ends the app.
- Markdown preview refuses block-heavy notes instead of freezing for ten
  seconds or more; Jump to heading is linear on long lines.

Also: search no longer matches short queries against note IDs, a byte-order mark
from an external editor keeps the note's metadata, `jotline run` checks
exported output before any step runs and accepts `--raw`, shell commands wait
longer for the vault lock, and read-only commands fail on a mistyped vault
path instead of creating one.

Download `jotline-0.9.2-py3-none-any.whl` and install it with
`uv tool install ./jotline-0.9.2-py3-none-any.whl` or
`pipx install ./jotline-0.9.2-py3-none-any.whl`. Python 3.11+ is required; Git is not.
For an existing installation add `--force`. `SHA256SUMS` covers both packages.

Run `jotline backup` before upgrading. Existing notes and settings remain
readable. Notes that contain U+2028, form feed or NEL are saved with those
characters normalized to newlines only after you edit them; search queries of
fewer than eight characters no longer match note IDs. See the README, changelog
and install guide for full details.

Publication is gated on the Linux/macOS/Windows Python 3.11–3.13 test and
installed-wheel smoke matrix. Native clipboard, IME and screen-reader behavior
still needs platform-specific hands-on checks; see the terminal testing guide.
