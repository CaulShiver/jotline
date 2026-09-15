# Release verification

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

The release workflow separately gates publication on the Linux/macOS/Windows
Python 3.11–3.13 matrix and smoke-tests the exact wheel it uploads. Consult the
GitHub Actions run for the remote results associated with a tag.

Native clipboard, input-method composition, screen-reader behavior and newcomer
task studies still require hands-on reports using
[the terminal checklist](terminal-testing.md). Headless and PTY tests do not
certify those capabilities.
