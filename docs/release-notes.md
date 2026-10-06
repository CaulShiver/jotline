Jotline 0.9.10 is an everyday usability release, and it closes the last items
from the 2026-09-21 red team. Linux and macOS remain the supported operating
systems. Windows is out of scope. Publication gates on Ubuntu and macOS ×
Python 3.11–3.13.

Search, capture and the shell are easier to use without looking things up.
Enter in the search box opens the top result. A new vault shows the quick
start once. `jotline open` finds a note from part of its title, and
`jotline capture` confirms in words at a terminal. Read commands work on a
fresh install and still create nothing. Titles in lists and pickers drop
Markdown markers. F1 shows the keys in effect, including your own. Ctrl+R
returns to the note you just left, Ctrl+G follows the link under the cursor,
and Ctrl+L toggles the task on the current line. If you already use one of
those keys, yours wins. Undo survives switching among the last eight notes.
Delete in the note list moves the highlighted note to Trash.

A key file from another vault is named as such and points at a backup,
instead of a wrong passphrase. Each encrypted note records which key sealed
it. 0.9.9 still reads these files: it ignores the new fields, and the key
file checksum is unchanged. Imports keep a Jotline header only with
`jotline import --jotline-notes`; without that flag the header stays in the
note as text. Linux desktop entries write `Exec=` the way the spec reads it.
The full list is in the changelog.

Notes stay plain Markdown. A new vault records that the quick start has been
shown. Run `jotline backup` before upgrading.

- Linux / macOS: `curl -fsSL https://github.com/CaulShiver/jotline/releases/latest/download/install.py | python3`
- PyPI: `uv tool install jotline` or `pipx install jotline` after this tag
  publishes. Python 3.11+ is required; Git is not.

Download `jotline-0.9.10-py3-none-any.whl` only if you want to verify
`SHA256SUMS` by hand, then `uv tool install ./jotline-0.9.10-py3-none-any.whl`
or `pipx install ./jotline-0.9.10-py3-none-any.whl`. For an existing
installation add `--force`.

See the README, changelog, install guide, and [supported platforms](platforms.md).
