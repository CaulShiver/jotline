Jotline 0.9.6 is the first release you can install without hunting a wheel.
The `v0.9.3` tag never uploaded GitHub Release assets; 0.9.4 fixed the Windows
Python 3.11 action-builder gate but was not tagged. `v0.9.5` built the wheel
and then failed Twine's metadata check (hatchling emits 2.5; Twine 6.1 did
not accept it). 0.9.6 keeps Windows, checks with Twine 7, and attaches the
wheel, source archive, checksums, and installers.

This tag also includes dated daily logs, extract-to-note, inbox processing,
visible note connections, and Linux desktop capture (`jotline desktop install`,
`jotline desktop launch`, and `jotline desktop recipe`).

- Linux / macOS: `curl -fsSL https://github.com/CaulShiver/jotline/releases/latest/download/install.py | python3`
- Windows: `irm https://github.com/CaulShiver/jotline/releases/latest/download/install.ps1 | iex`
- PyPI: `uv tool install jotline` or `pipx install jotline` after this tag
  publishes. Python 3.11+ is required; Git is not.

Download `jotline-0.9.6-py3-none-any.whl` only if you want to verify
`SHA256SUMS` by hand, then `uv tool install ./jotline-0.9.6-py3-none-any.whl`
or `pipx install ./jotline-0.9.6-py3-none-any.whl`. For an existing
installation add `--force`.

Run `jotline backup` before upgrading. Existing notes and settings remain
readable; no storage format changed. See the README, changelog, install guide,
and [supported platforms](platforms.md).

Publication is gated on the Linux/macOS/Windows Python 3.11–3.13 test and
installed-wheel smoke matrix. Native clipboard, IME and screen-reader behavior
still needs platform-specific hands-on checks; see the terminal testing guide.
