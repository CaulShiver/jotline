Jotline 0.9.7 drops Windows. Linux and macOS remain the supported operating
systems. `jotline` and `scripts/install.py` refuse Windows at process entry.
There is no PowerShell installer. Publication gates on Ubuntu and macOS ×
Python 3.11–3.13.

This tag also includes the Unreleased work from after 0.9.6: vault-scale
benchmarks and stronger doctor/backups/recoveries, quieter palette and empty
states, accessibility labels, Git/Syncthing sync recipes, and richer example
actions.

- Linux / macOS: `curl -fsSL https://github.com/CaulShiver/jotline/releases/latest/download/install.py | python3`
- PyPI: `uv tool install jotline` or `pipx install jotline` after this tag
  publishes. Python 3.11+ is required; Git is not.

Download `jotline-0.9.7-py3-none-any.whl` only if you want to verify
`SHA256SUMS` by hand, then `uv tool install ./jotline-0.9.7-py3-none-any.whl`
or `pipx install ./jotline-0.9.7-py3-none-any.whl`. For an existing
installation add `--force`.

Run `jotline backup` before upgrading. Existing notes and settings remain
readable; no storage format changed. See the README, changelog, install guide,
and [supported platforms](platforms.md).

Native clipboard, IME and screen-reader behavior still needs Linux and macOS
hands-on checks; see the terminal testing guide. Windows reports are no longer
a 1.0 requirement.
