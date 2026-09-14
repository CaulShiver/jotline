# Quality backlog: backlinks and the rest of the app

Reviewed September 14, 2026 against Jotline 0.9.3, then implemented the
connect-loop slices below. Graph views, plugins, AI, dictation, and cloud
sync remain out of scope; they need separate designs, as
[ROADMAP.md](../ROADMAP.md) already states.

**Decision:** implement the five-slice sequence. This change delivers slices
1, 2, and 4 (design only). Slice 3 stays open until someone files a native
terminal or screen-reader report. Slice 5 stays parked until there is
evidence people need search OR, attachments, or unlinked mentions.

## Implementation sequence

1. **Backlinks quality slice** — done in this change. Connections panel,
   snippets, cursor-aware follow, fence-aware parse, broken-link create,
   Alt+K, and `jotline backlinks`. See `links.py`, `store.py`, `app.py`,
   `export.py`, `cli.py`, and `tests/test_connections.py`.
2. **Compact-terminal and empty-state pass** — done in this change. 80×24
   hides the connections bar but keeps `←N →N` on the status line; Alt+K and
   Ctrl+P still open the panel. Empty, broken, and locked notes have their
   own copy.
3. **Hands-on terminal and AT reports** — still open. Issues
   [#2](https://github.com/CaulShiver/jotline/issues/2) and
   [#3](https://github.com/CaulShiver/jotline/issues/3) ask for a native
   macOS or Windows terminal report and a screen-reader pass. This environment
   cannot produce those reports. Do not close the issues until a human files
   one under `docs/terminal-reports/` using
   [the terminal checklist](terminal-testing.md). Fix only the failures those
   reports name.
4. **Indexing design** — measured and written in
   [indexing-design.md](indexing-design.md). Search and backlinks already
   share `Vault.notes()` / `workspace_notes()`. Do not add an index until a
   representative vault is slower than the budget in that note.
5. **Search OR / attachments / unlinked mentions** — parked. No user evidence
   yet. Do not start these in this change.

## What backlinks do now

- `Vault.connections` lists incoming and outgoing `LinkRef`s with a one-line
  snippet and `ok` / `broken` / `ambiguous` / locked state.
- `Note.links` uses the same fence-aware parser as highlighting and export.
- The editor footer shows `← N  → N` and the first incoming titles. Click it
  or press Alt+K to open the Connections palette.
- Follow uses the `[[link]]` under the cursor. Preview clicks and Ctrl+click
  in the editor do the same.
- A missing target offers **Create note**.
- Compact terminals keep counts on the status line.
- `jotline backlinks NOTE [--json]` prints the graph.

## Remaining quality items

### Everyday use

- Newcomer study and native terminal / AT reports (slice 3, issues #2 and #3).
- Clipboard, IME, and assistive tech still need hands-on checks.
- Large-vault indexing only after the measurements in
  [indexing-design.md](indexing-design.md) say it is needed.

### Connect and find

- Search still has no OR / tag-any / regex.
- Attachments and subfolders are unsupported.
- Cross-workspace links stay invisible by design; a later pass could show
  “linked, other workspace”.

### Trust and recovery

History, backups, conflict copies, and `doctor` stay as they are. Locked
notes now say they are locked instead of `← 0 backlinks`.

### Power-user leftovers

Regex find/replace, external actions, plugins, system-wide hotkeys, Vim
emulation, dictation, and AI stay parked.

Discuss changes that alter note formats, shortcuts, or public APIs before
implementation. See [CONTRIBUTING.md](../CONTRIBUTING.md).
