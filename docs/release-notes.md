Jotline 0.9.1 fixes stale search results when an external edit preserves all
tracked timestamps. Cached notes expire after one second and are reread on the
next scan; Refresh vault forces an immediate reread. Direct reads and save-conflict
checks continue to read the file directly.

The 0.9 series makes the everyday capture, find, process and recover workflow more
discoverable in the terminal.

- Build and preview local actions without writing JSON; start from useful recipes.
- Edit, rename and duplicate actions/views, and share action recipe files.
- Browse collections and filters with visible controls and an optional quick start.
- Compare save conflicts and preserve your draft before reviewing external text.
- Preview folder and Drafts imports, with duplicate handling and metadata mapping.
- Inspect bounded action history to understand completed and failed steps.

Download `jotline-0.9.1-py3-none-any.whl` and install it with
`uv tool install ./jotline-0.9.1-py3-none-any.whl` or
`pipx install ./jotline-0.9.1-py3-none-any.whl`. Python 3.11+ is required; Git is not.
For an existing installation add `--force`. `SHA256SUMS` covers both packages.

Run `jotline backup` before upgrading. Existing notes remain readable. Date
filters require `YYYY-MM-DD` or `today`; compact date strings are rejected with
a format hint. See the README, changelog and install guide for full details.

Publication is gated on the Linux/macOS/Windows Python 3.11–3.13 test and
installed-wheel smoke matrix. Native clipboard, IME and screen-reader behavior
still needs platform-specific hands-on checks; see the terminal testing guide.
