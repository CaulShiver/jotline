Jotline 0.9.11 opens on a blank page. Linux and macOS remain the supported
operating systems. Windows is out of scope. Publication gates on Ubuntu and
macOS × Python 3.11–3.13.

The note list, formatting toolbar and hint start hidden. `Ctrl+F` brings the
list back for search, `Ctrl+O` opens a note by title, and `F8` toggles that
quiet layout. Focus mode moved from `Ctrl+B` (tmux's prefix) to `F8`. `F3`
finds in the open note. `Ctrl+W` deletes the word to the left; Switch
workspace is no longer on a key. Delete on a highlighted note asks `Move to
Trash? Enter` before it moves the note. Any other key cancels.

`jotline sync` is gone. It only printed a recipe. `jotline doctor` points at
`docs/sync.md`. `encrypt`, `decrypt` and `encryption` stay out of
`jotline --help`, including the command list, until the cryptography extra
is installed or the default vault has a key file. Typing the command still
works. The full list is in the changelog.

`Start on a blank page` is on for a new vault. A vault that already saved
that setting off keeps the list visible. If you already gave `F8` or `F3`
to another command, yours wins. Notes stay plain Markdown. Run
`jotline backup` before upgrading.

- Linux / macOS: `curl -fsSL https://github.com/CaulShiver/jotline/releases/latest/download/install.py | python3`
- PyPI: `uv tool install jotline` or `pipx install jotline` after this tag
  publishes. Python 3.11+ is required; Git is not.

Download `jotline-0.9.11-py3-none-any.whl` only if you want to verify
`SHA256SUMS` by hand, then `uv tool install ./jotline-0.9.11-py3-none-any.whl`
or `pipx install ./jotline-0.9.11-py3-none-any.whl`. For an existing
installation add `--force`.

See the README, changelog, install guide, and [supported platforms](platforms.md).
