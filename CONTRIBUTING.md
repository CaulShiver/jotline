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
and run `scripts/smoke_install.py` from a fresh venv containing the built wheel and
its dependencies.

CI runs the complete suite and installed-wheel CLI/TUI smoke checks on Linux
and macOS with Python 3.11–3.13. POSIX-only filesystem cases are marked
explicitly. Storage code uses `jotline.filesystem.fs` (native `os` with
descriptor-relative calls). Keep file I/O UTF-8 with explicit newlines; do not
substitute unprotected path operations for descriptor-relative storage calls.
Windows is out of scope; do not add Windows runners, classifiers, or install
instructions.

Storage changes should cover round trips, external edits, failed saves, and doctor
diagnostics. UI changes should exercise the relevant keyboard workflow with Textual's
Pilot. Use temporary vaults for testing; never include personal notes in commits or
screenshots.

Follow [the terminal and accessibility checklist](docs/terminal-testing.md) for
native UI verification. Headless tests cannot certify clipboard, screen-reader,
or input-method compatibility. File hands-on results with
[docs/terminal-reports/TEMPLATE.md](docs/terminal-reports/TEMPLATE.md); do not
invent platform or assistive-technology outcomes. On POSIX, the fresh wheel
environment can also run `python -I scripts/smoke_pty.py` to exercise actual
terminal input and saves.

The package version is single-sourced in `src/jotline/__init__.py`; `pyproject.toml`
reads it dynamically. Release pull requests should update that value, Status
text, [CHANGELOG.md](CHANGELOG.md), and `docs/release-notes.md` together.
README and [docs/install.md](docs/install.md) should keep install examples as
`jotline-<version>-py3-none-any.whl` and point at
[GitHub Releases](https://github.com/CaulShiver/jotline/releases/latest), not a
filename whose assets have not been published. Jotline is not on PyPI.

For bugs, include the Jotline/Python version, terminal, steps to reproduce, and the
error message. `jotline doctor --json` reports counts, paths, versions, limits,
and local state without note bodies. Review local paths before attaching it. Do not
include secrets or private notes. New integrations should be explicitly
user-triggered and preserve the offline core.

## Releases

Update the package version, Status text in the main README, [CHANGELOG.md](CHANGELOG.md),
and `docs/release-notes.md` together. Keep README/install wheel examples on the
`<version>` placeholder so they stay valid before assets exist. Build and
exercise the installed wheel locally. `python scripts/release_metadata.py --checksums`
checks package names and writes SHA-256 checksums after `uv build --clear`.

Push a matching `vX.Y.Z` tag to start the release workflow. It runs the Linux
and macOS test and wheel-smoke matrix before publishing the pure-Python wheel,
source archive, and checksums to GitHub Releases. Do not push a tag until the
intended commit is on `main`. The tag must match the single-sourced package
version. A failed verification job prevents publication. A tag without uploaded
Release assets is not an installable release; do not advertise that wheel until
the publish job succeeds. Never move an already-published tag; fix the issue
and release a new patch version. The `v0.9.3` tag was pushed but did not
publish assets (Windows CI blocked it); do not reuse that tag.
