# Release verification

## 0.9.10

- Package version `0.9.10`. Publication gates on Ubuntu and macOS × Python
  3.11–3.13, as for 0.9.9.
- Local locked suite on Linux / Python 3.12: **1145 passed, 43 skipped**.
  `ruff check`, `uv lock --check` and `git diff --check` passed.
- `uv build --clear` produced the wheel and sdist; `release_metadata.py
  --checksums` verified `v0.9.10` and wrote `SHA256SUMS`; `twine==7.0.0 check`
  passed. `install.py --from-dir dist` installed the wheel into a clean venv,
  `jotline --version` reported `0.9.10`, and the installed-wheel and POSIX PTY
  smoke tests passed. The PTY smoke closes the first-run quick start with Esc
  before it pastes; Ctrl+Q does not quit while that guide is open.
- Key files and encrypted notes gain a key id. 0.9.9 ignores those fields, and
  the key file checksum is unchanged. A new vault records that the quick start
  has been shown. Notes stay plain Markdown.
- VoiceOver remains untested; issue #3 stays open.

## 0.9.9

- Package version `0.9.9`. Publication gates on Ubuntu and macOS × Python
  3.11–3.13, as for 0.9.8.
- Local locked suite on macOS 27 / Python 3.13: **1053 passed, 21 skipped**.
  `ruff check`, `uv lock --check` and `git diff --check` passed.
- `uv build --clear` produced the wheel and sdist; `release_metadata.py
  --checksums` verified `v0.9.9` and wrote `SHA256SUMS`; `twine==7.0.0 check`
  passed. `install.py --from-dir dist` installed the wheel into a clean venv,
  `jotline --version` reported `0.9.9`, and the installed-wheel and POSIX PTY
  smoke tests passed.
- Key files gain a `checksum` field. 0.9.8 ignores it, and 0.9.9 reads key
  files without one. Notes and settings are unchanged.
- VoiceOver remains untested; issue #3 stays open.

## 0.9.8

- Package version `0.9.8`. Publication still gates on Ubuntu and macOS ×
  Python 3.11–3.13. Native copy uses `pbcopy` on macOS; OSC 52 is a fallback.
  The GitHub installer JSON Accept header is `application/vnd.github+json`.
- Local locked suite on macOS 27 / Python 3.13: **690 passed, 19 skipped**,
  including clipboard native/fallback tests. POSIX PTY smoke passed. Terminal.app
  Copy updated `pbpaste` with the synthetic note body.
- No storage format change. VoiceOver remains untested; issue #3 stays open.

## 0.9.7

- Windows is out of scope. Publication gates on Ubuntu and macOS × Python
  3.11–3.13. `scripts/install.py` is the only tagged installer; there is no
  `install.ps1`. `jotline` exits 2 on Windows.
- Unreleased work after 0.9.6 (vault doctor, quiet palette, accessibility
  labels, sync recipes, example actions) ships in this version.

## 0.9.6

- Same locked suite as 0.9.5. The `v0.9.5` package job failed because
  `twine==6.1.0` rejected Metadata-Version 2.5. Local `uvx twine==7.0.0 check`
  passed on the built wheel and sdist. The release workflow now uses Twine 7.
- `v0.9.5` is not moved. This is a new patch tag.

## 0.9.5

- Complete locked suite on Linux/Python 3.12: **562 passed, 30 platform-specific skips**,
  including installer checksum/one-liner tests, the supported-OS contract, and
  the newcomer open-type-find-process-recover path.
- `uv build --clear` produced `jotline-0.9.5-py3-none-any.whl` and
  `jotline-0.9.5.tar.gz`. `scripts/release_metadata.py --checksums` copied
  `install.py` and `install.ps1` and wrote `SHA256SUMS` covering all four
  artifacts.
- `scripts/install.py --from-dir dist` installed that wheel into a clean venv
  and `jotline --version` reported `0.9.5`.
- Locked dependency resolution and `git diff --check` passed.
- Publication still gates on Linux/macOS/Windows Python 3.11–3.13. The tag
  workflow attaches GitHub Release assets, then publishes the wheel and sdist
  to PyPI via Trusted Publishing. Windows stays in the matrix.

## 0.9.4

- Complete locked suite on Linux/Python 3.12: **552 passed, 30 platform-specific skips**,
  including the compact-terminal action-builder footer test and packaging checks
  that install docs name the current wheel.
- Fresh 0.9.4 installed-wheel application smoke and POSIX PTY smoke passed.
- Release identity verified: `v0.9.4`. `uv build --clear` produced
  `jotline-0.9.4-py3-none-any.whl` and `jotline-0.9.4.tar.gz`.
- Locked dependency resolution and `git diff --check` passed.
- The `v0.9.3` tag still exists without GitHub Release assets. This version is
  the publishable replacement. The tag workflow continues to gate publication
  on Linux/macOS/Windows Python 3.11–3.13.

## 0.9.3

- Complete locked suite on Linux/Python 3.12: **372 passed, 3 platform-specific skips**,
  including 12 new tests for append/prepend line joining and CLI error messages.
- Fresh 0.9.3 installed-wheel application smoke and POSIX PTY smoke passed.
- Installed wheel checked by hand: `append` puts text on its own line and a
  missing note ID prints the plain-language message.
- Locked dependency resolution, release identity, checksum generation, workflow
  validation (`actionlint`) and `git diff --check` passed.
- Windows reports missing files without a filename, so the new messages check
  the note or import path directly; the tag workflow's Windows jobs verify this.

## 0.9.2

- Complete locked suite on Linux/Python 3.12: **360 passed, 3 platform-specific skips**,
  including 49 new regression tests from the 2026-09-12 red team.
- Fresh 0.9.2 installed-wheel application smoke and POSIX PTY smoke passed.
- Locked dependency resolution, release identity, checksum generation, workflow
  validation (`actionlint`) and `git diff --check` passed.
- Filesystems without hard links were simulated by refusing `link(2)`; disk-full
  by refusing the backup write; clock steps by fixed revision stamps.
- The tag workflow gates publication on all nine OS/Python combinations and
  repeats smoke tests against the exact wheel uploaded.

## 0.9.1

- Complete locked suite on Linux/Python 3.12: **311 passed, 3 platform-specific skips**.
- Fresh 0.9.1 installed-wheel application smoke and POSIX PTY smoke passed.
- Deterministic tests cover identical file signatures, expiry after one second,
  repeated cache hits that do not extend expiry, and immediate forced refresh.
- Locked dependency resolution, release identity, workflow validation and
  `git diff --check` passed.
- The tag workflow gates publication on all nine OS/Python combinations and
  repeats smoke tests against the exact wheel uploaded.

## 0.9.0

Local verification on Linux with Python 3.12:

- Complete locked suite: **310 passed, 3 platform-specific skips**.
- Fresh installed wheel: capture/export, terminal writing, tags, workspaces,
  hotkeys, Markdown, templates, backups, action builder/run history, filters,
  and import smoke passed.
- POSIX PTY: startup, Unicode bracketed paste, autosave and Ctrl+Q passed.
- Isolated uv tool install, force reinstall and uninstall passed; the synthetic
  vault remained after uninstall.
- All new import/recovery buttons, filter Apply, and action builder preview/save
  were exercised with keyboard navigation at 60×20 and 80×24.
- Updated main screenshot visually inspected; narrow view screenshot inspected.
- Workflow validation (`actionlint`), local Markdown links, package metadata,
  checksums, release-tag mismatch rejection and `git diff --check` passed.

The local sandbox denies asyncio's internal socket wakeups, which can stall
executor shutdown after a test has passed. The final full suite and wheel smoke
were therefore run outside that sandbox. No production workaround was added for
this environment restriction.

The release workflow separately gates publication on the Linux/macOS
Python 3.11–3.13 matrix and smoke-tests the exact wheel it uploads. Consult the
GitHub Actions run for the remote results associated with a tag.

Native clipboard, input-method composition, screen-reader behavior and newcomer
task studies still require hands-on reports using
[the terminal checklist](terminal-testing.md). Headless and PTY tests do not
certify those capabilities.
