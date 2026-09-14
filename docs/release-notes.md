Jotline 0.9.4 is an early release for Linux and macOS. Windows is out of scope.

This is the first GitHub Release after v0.9.2: the v0.9.3 tag never uploaded
wheels because Windows CI blocked the publish job. 0.9.4 drops Windows from the
product surface and publishes a pure-Python wheel (`jotline-0.9.4-py3-none-any.whl`)
once the Linux and macOS Python 3.11–3.13 matrix passes.

Since 0.9.2 it also includes:

- `jotline append` / `prepend` put text on its own line (`--no-newline` keeps the old join).
- Full Markdown editing: highlighting, list continuation, toolbar, live preview.
- Optional note encryption, tasks, shell completion, HTML/Word/PDF export, and quick capture.
- Settings on Ctrl+, (Mac-friendly), Omarchy theme follow, and macOS `/tmp` imports.

**Install:** Jotline is not on PyPI. Download `jotline-0.9.4-py3-none-any.whl`
from this GitHub Release and run
`uv tool install ./jotline-0.9.4-py3-none-any.whl` or
`pipx install ./jotline-0.9.4-py3-none-any.whl`. Python 3.11+ on Linux or macOS
is required; Git is not. For an existing installation add `--force`.
`SHA256SUMS` covers both packages.

Run `jotline backup` before upgrading. Existing notes and settings remain
readable. See the README, changelog and install guide for full details.

Native clipboard, IME and screen-reader behavior still needs hands-on checks
on Linux and macOS; see the terminal testing guide.
