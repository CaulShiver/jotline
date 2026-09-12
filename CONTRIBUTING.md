# Contributing

Jotline values fast capture, readable files, and a small keyboard-first interface.

Install with `uv sync --extra dev`. Before opening a pull request, run the locked
suite with `uv run --locked pytest -q`. CI also checks an unlocked latest resolve
with `uv lock --upgrade --dry-run`, a direct lower-bound environment, and a clean
installed-wheel smoke run. For local release checks, build with `uv build --clear`
and run `scripts/smoke_install.py` from a fresh venv containing the built wheel and
its dependencies.

Storage changes should cover round trips, external edits, failed saves, and doctor
diagnostics. UI changes should exercise the relevant keyboard workflow with Textual's
Pilot. Use temporary vaults for testing; never include personal notes in commits or
screenshots.

The package version is single-sourced in `src/jotline/__init__.py`; `pyproject.toml`
reads it dynamically. Release pull requests should update that value and any
user-facing status text together.

For bugs, include the Jotline/Python version, terminal, steps to reproduce, and the
error message. `jotline doctor --json` is safe to attach when it helps because it
reports counts, paths, versions, limits, and local state without note bodies. Do not
include secrets or private notes. New integrations should be explicitly
user-triggered and preserve the offline core.
