Jotline 0.9.9 adds an inline outliner and ranked search, and ships the fixes
from two red team passes. Linux and macOS remain the supported operating
systems. Windows is out of scope. Publication gates on Ubuntu and macOS ×
Python 3.11–3.13.

The outliner edits a note as a tree of blocks: folding, branch focus,
breadcrumbs, search through folded content, bulk selection, move-to and
optional block references. It writes plain Markdown, so the note stays readable
anywhere. Search now orders notes by match quality and quotes the matched line,
pickers match the letters you type in order, and **Edit this note in $EDITOR**
hands a note to your own editor. `jotline capture` starts in about a tenth of a
second.

The red team fixes cover saves, encryption and the terminal. A note
interrupted mid-save comes back instead of disappearing. Encrypted notes no
longer leak through extract, exports, links, history or the daily backup, and
no process Jotline starts inherits your passphrase. Note text and command-line
arguments can no longer send control sequences to your terminal. `jotline
backups` lists quarantined archives. The full list is in the changelog.

Key files now carry a checksum so a damaged file is reported as damaged rather
than as a wrong passphrase. Key files written by 0.9.8 keep working, and 0.9.8
can still read a key file written by 0.9.9. Notes and settings are unchanged.

- Linux / macOS: `curl -fsSL https://github.com/CaulShiver/jotline/releases/latest/download/install.py | python3`
- PyPI: `uv tool install jotline` or `pipx install jotline` after this tag
  publishes. Python 3.11+ is required; Git is not.

Download `jotline-0.9.9-py3-none-any.whl` only if you want to verify
`SHA256SUMS` by hand, then `uv tool install ./jotline-0.9.9-py3-none-any.whl`
or `pipx install ./jotline-0.9.9-py3-none-any.whl`. For an existing
installation add `--force`.

Run `jotline backup` before upgrading. See the README, changelog, install
guide, and [supported platforms](platforms.md).
