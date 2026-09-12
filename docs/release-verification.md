# Release verification

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
