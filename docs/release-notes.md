Jotline 0.9.3 fixes how the command line adds text to existing notes and makes
its error messages readable.

- `jotline append` and `jotline prepend` now put the text on its own line.
  Previously `jotline append NOTE_ID "more"` joined the text straight onto the
  last line, merging words and creating false tags such as `#ideaappended`. One
  line break is added only where the text would run into the note, in the
  note's own newline style (LF, CRLF or CR); text that already starts or ends
  with a newline is not doubled. Local actions that append to a note are
  unchanged.
- A missing note now reads `No note with ID …; run jotline list to find IDs`,
  a missing import file no longer shows `[Errno 2]` or `[WinError 2]`, and
  non-UTF-8 input names its source instead of printing a Python codec error.

**Behavior change:** scripts that relied on the exact join can pass
`--no-newline` to keep it.

Download `jotline-0.9.3-py3-none-any.whl` and install it with
`uv tool install ./jotline-0.9.3-py3-none-any.whl` or
`pipx install ./jotline-0.9.3-py3-none-any.whl`. Python 3.11+ is required; Git is not.
For an existing installation add `--force`. `SHA256SUMS` covers both packages.

Run `jotline backup` before upgrading. Existing notes and settings remain
readable; no storage format changed. See the README, changelog and install guide
for full details.

Publication is gated on the Linux/macOS/Windows Python 3.11–3.13 test and
installed-wheel smoke matrix. Native clipboard, IME and screen-reader behavior
still needs platform-specific hands-on checks; see the terminal testing guide.
