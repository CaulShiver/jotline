# Contributing

Jotline values fast capture, readable files, and a small keyboard-first interface.

Start with [ROADMAP.md](ROADMAP.md) for priorities and scoped starter tasks.
Use the workflow-improvement issue template to describe user needs before a
large change. Recipes and terminal compatibility reports are useful contributions
alongside code. Security issues should follow [SECURITY.md](SECURITY.md).

Install with `uv sync --extra dev`. Before opening a pull request, run the locked
suite with `uv run --locked pytest -q`. CI also checks an unlocked latest resolve
with `uv lock --upgrade --dry-run`, a direct lower-bound environment, and a clean
installed-wheel smoke run. For local release checks, build with `uv build --clear`
and run `python scripts/install.py --from-dir dist --installer pip` into a fresh
venv, then `python -I scripts/smoke_install.py` from that environment.

CI runs the complete suite and installed-wheel CLI/TUI smoke checks on Linux
and macOS with Python 3.11–3.13. POSIX-only filesystem cases are marked
explicitly. Storage code uses `jotline.filesystem.fs` (native `os`). Keep file
I/O UTF-8 with explicit newlines; do not substitute unprotected path operations
for descriptor-relative storage calls. Windows is out of scope.

Storage changes should cover round trips, external edits, failed saves, and doctor
diagnostics. UI changes should exercise the relevant keyboard workflow with Textual's
Pilot. Use temporary vaults for testing; never include personal notes in commits or
screenshots.

Follow [the terminal and accessibility checklist](docs/terminal-testing.md) for
native UI verification. Headless tests cannot certify clipboard, screen-reader,
or input-method compatibility. On POSIX, the fresh wheel environment can also
run `python -I scripts/smoke_pty.py` to exercise actual terminal input and saves.

The package version is single-sourced in `src/jotline/__init__.py`; `pyproject.toml`
reads it dynamically. Release pull requests should update that value and any
user-facing status text together.

For bugs, include the Jotline/Python version, terminal, steps to reproduce, and the
error message. `jotline doctor --json` reports counts, paths, versions, limits,
and local state without note bodies. Review local paths before attaching it. Do not
include secrets or private notes. New integrations should be explicitly
user-triggered and preserve the offline core.

## Releases

Update the package version, main README, [CHANGELOG.md](CHANGELOG.md), and
`docs/release-notes.md` together. Build and exercise the installed wheel locally.
`python scripts/release_metadata.py --checksums` checks package names and writes
SHA-256 checksums after `uv build --clear`.

Push an annotated matching `vX.Y.Z` tag to start the release workflow. It runs
the complete Linux/macOS test and installer-smoke matrix, then publishes
the wheel, source archive, checksums, and `install.py` to GitHub
Releases. A later job uploads the wheel and sdist to PyPI with Trusted
Publishing. The tag must match the single-sourced package version. A failed
verification job prevents publication. Never move an already-published tag; fix
the issue and release a new patch version.

Before the first PyPI upload, add a pending publisher at
https://pypi.org/manage/account/publishing/ :

- PyPI project name: `jotline`
- Owner: `CaulShiver`
- Repository: `jotline`
- Workflow name: `release.yml`
- Environment name: `pypi`

The GitHub Release with assets is the install path that does not wait on that
one-time PyPI click. After it succeeds, `uv tool install jotline` works on
Linux and macOS.
