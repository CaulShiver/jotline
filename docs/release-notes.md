Jotline 0.9.8 copies through the OS clipboard and repairs the GitHub
one-liner. Linux and macOS remain the supported operating systems. Windows
is out of scope. Publication gates on Ubuntu and macOS × Python 3.11–3.13.

Copy uses `pbcopy` on macOS and `wl-copy`, `xclip`, or `xsel` on Linux when
those tools exist, and confirms only after the tool succeeds. OSC 52 remains
a fallback request. Terminal.app blocks OSC 52; macOS copy no longer depends
on it.

The installer now asks GitHub's release JSON API for
`application/vnd.github+json`. The previous `Accept: application/octet-stream`
header made tagged GitHub installs fail with HTTP 415.

A filled Terminal.app report for macOS 27 is in
`docs/terminal-reports/macos-27-terminal.md`. VoiceOver was off; that 1.0
criterion and issue #3 stay open.

- Linux / macOS: `curl -fsSL https://github.com/CaulShiver/jotline/releases/latest/download/install.py | python3`
- PyPI: `uv tool install jotline` or `pipx install jotline` after this tag
  publishes. Python 3.11+ is required; Git is not.

Download `jotline-0.9.8-py3-none-any.whl` only if you want to verify
`SHA256SUMS` by hand, then `uv tool install ./jotline-0.9.8-py3-none-any.whl`
or `pipx install ./jotline-0.9.8-py3-none-any.whl`. For an existing
installation add `--force`.

Run `jotline backup` before upgrading. Existing notes and settings remain
readable; no storage format changed. See the README, changelog, install guide,
and [supported platforms](platforms.md).
