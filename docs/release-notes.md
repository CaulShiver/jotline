Jotline 0.9.4 is the first published wheel after 0.9.2. The `v0.9.3` tag exists
but never uploaded GitHub Release assets: Windows Python 3.11 failed the action
builder keyboard test on a 60×20 terminal.

- Preview, Save, and Cancel in the action builder stay on screen on short
  terminals. Tab still reaches every field; the footer no longer sits one row
  below the viewport.
- `jotline append` and `jotline prepend` put the text on its own line. Pass
  `--no-newline` for the previous exact join.
- Markdown source editing, toolbar, live preview, tasks, HTML/Word/PDF export,
  optional note encryption, and Omarchy theme follow-along. Settings opens with
  Ctrl+, (F1 still works). macOS import accepts `/tmp` and `$TMPDIR`.

**Behavior change:** scripts that relied on append/prepend joining onto the last
character can pass `--no-newline`.

Download `jotline-0.9.4-py3-none-any.whl` and install it with
`uv tool install ./jotline-0.9.4-py3-none-any.whl` or
`pipx install ./jotline-0.9.4-py3-none-any.whl`. Python 3.11+ is required; Git is not.
For an existing installation add `--force`. `SHA256SUMS` covers both packages.

Run `jotline backup` before upgrading. Existing notes and settings remain
readable; no storage format changed. See the README, changelog and install guide
for full details.

Publication is gated on the Linux/macOS/Windows Python 3.11–3.13 test and
installed-wheel smoke matrix. Native clipboard, IME and screen-reader behavior
still needs platform-specific hands-on checks; see the terminal testing guide.
