Jotline 0.9.12 adds shell edit, trash and rename, and optional readable
filenames. Linux and macOS remain the supported operating systems. Windows
is out of scope. Publication gates on Ubuntu and macOS × Python 3.11–3.13.

`export`, `append`, `tag`, `done`, `encrypt`, `decrypt`, `trash` and
`rename` now fall back to the closest title match, the way `open` already
did. A unique ID prefix or an exact title is used as named. When several
notes fit, the error lists each candidate. `trash` and `rename` use that
fallback only with confirmation: `--yes`, or a question at a terminal.

`jotline edit` opens the note in `$EDITOR`. `jotline trash` moves it to
Trash and does not delete the file. `jotline rename` changes the title and
keeps the ID. All three accept `--json`. `open` and `daily` refuse when
there is no terminal. `export` to stdout ends with a newline. `list` takes
`--limit` and `--sort`.

Note files can be named with a title slug and a short ID. This stays off
until `jotline filenames migrate`, which renames `a1b2c3….md` to
`buy-milk--a1b2c3.md`, writes the full ID in the header, and turns the
setting on. It asks first in a terminal and refuses without `--yes` when
there is no terminal. A real run backs up first. `jotline filenames revert`
puts the ID back in the filename, with the same confirmation. Links,
history, backups, recovery and encryption keep using the note ID. Daily
logs stay `daily-YYYY-MM-DD.md`. Encrypted notes stay `<id>.md`. Do not
edit a migrated vault with Jotline 0.9.11 or earlier: it treats the
filename as the ID. The full list is in the changelog.

Notes stay plain Markdown until you opt in to readable filenames. Run
`jotline backup` before upgrading, and again before migrating filenames.

- Linux / macOS: `curl -fsSL https://github.com/CaulShiver/jotline/releases/latest/download/install.py | python3`
- PyPI: `uv tool install jotline` or `pipx install jotline` after this tag
  publishes. Python 3.11+ is required; Git is not.

Download `jotline-0.9.12-py3-none-any.whl` only if you want to verify
`SHA256SUMS` by hand, then `uv tool install ./jotline-0.9.12-py3-none-any.whl`
or `pipx install ./jotline-0.9.12-py3-none-any.whl`. For an existing
installation add `--force`.

See the README, changelog, install guide, and [supported platforms](platforms.md).
