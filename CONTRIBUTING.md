# Contributing

Jotline values fast capture, readable files, and a small keyboard-first interface.

Install with `uv sync --extra dev`. Run `uv run pytest` before opening a pull request.
Storage changes should cover round trips, external edits, and failed saves. UI changes
should exercise the relevant keyboard workflow with Textual's Pilot. Use temporary
vaults for testing; never include personal notes in commits or screenshots.

For bugs, include the Jotline/Python version, terminal, steps to reproduce, and the
error message. Do not include secrets or private notes. New integrations should be
explicitly user-triggered and preserve the offline core.
