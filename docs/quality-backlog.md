# Quality backlog: backlinks and the rest of the app

Reviewed September 14, 2026 against Jotline 0.9.3 (`store.py`, `app.py`,
`export.py`, `cli.py`, `markdown_editor.py`, `ROADMAP.md`, and the README
status section). This is an audit, not a delivery estimate. Graph views,
plugins, AI, dictation, and cloud sync remain out of scope; they need
separate designs, as [ROADMAP.md](../ROADMAP.md) already states.

**Decision for this pass:** leave the audit as documentation. The recommended
later implementation slice is **backlinks quality** (item 1 in the sequence
below). Do not start a graph, plugin host, or AI layer to make 1.0 feel
finished.

Jotline already has the bones of a quality local notes app: capture, autosave,
workspaces, tags, search, Markdown editing, history, backups, and
`[[note links]]`. The linking loop is the weakest part of the advertised
capture → connect → review story.

## What backlinks do today

The feature exists, but it is a status line plus a palette picker.

- `Vault.backlinks` in `store.py` scans every note in the workspace, skips
  trash, and matches `[[id]]`, `[[title]]`, or `[[heading]]`.
- `Jotline.connections` in `app.py` shows `← N backlinks` and the first three
  titles. The line is not clickable.
- On terminals 24 rows or shorter, that footer is hidden entirely.
- Opening a backlink is `Ctrl+P → Open a backlink`. There is no default hotkey.
- Follow is also a palette: it lists every link in the note, not the one under
  the cursor.
- Preview keeps `open_links=False`, so rendered `[[links]]` cannot be followed.
- There is no CLI: `jotline list` cannot answer “what points here?”

```
write → insert [[id|title]] → save → scan workspace
     → footer (count + 3 titles) → Ctrl+P Open a backlink → open source
```

## Backlink gaps that keep this from feeling finished

These are the items that would make connecting notes feel like a product, not
a command.

1. **The connections surface is not a UI.** A muted one-line count cannot be
   opened, scrolled, or clicked. After three titles the rest disappear unless
   you remember the palette command. On the common 80×24 terminal, even that
   line is gone.
2. **No context snippets.** Quality backlink panels show the sentence or
   bullet that contains the link. Jotline only shows note titles, so you
   cannot tell why something points here.
3. **Outgoing links are invisible.** The footer is incoming-only. There is no
   “this note links to…” list, so a hub can look isolated.
4. **Follow is not cursor-aware.** Wiki links are underlined in the editor, but
   clicking or placing the cursor on `[[…]]` does not open the target. You
   must hunt through a palette of every link in the note.
5. **Broken and ambiguous links are silent.** `[[Exact title]]` can match
   several notes. Missing targets produce no warning. There is no “create
   note from this link” path.
6. **Link parsing is inconsistent.** Highlighting and export already ignore
   `[[links]]` inside fenced code and code spans. `Note.links` still scans the
   raw body, so documentation examples become fake backlinks.
7. **Refresh cost and freshness.** `connections()` rescans the vault on
   load, save, and move. Unsaved `[[links]]` in the editor do not update the
   footer until save. Large vaults already need indexing; backlinks are the
   same full scan as search.
8. **Locked encrypted notes disappear from the graph.** A locked note has an
   empty body, so it neither contributes nor displays real links. That is
   correct for secrecy, but the UI should say so instead of `← 0 backlinks`.
9. **No scriptable inspection.** Shell users can `list`, `tags`, and `tasks`,
   but cannot print backlinks as text or JSON.

A quality bar that still fits Jotline (terminal, local Markdown, no graph
product):

- A Connections panel or palette section with incoming and outgoing notes
- One-line context for each backlink
- Follow the link under the cursor, and click in preview
- Shared fence-aware parser for index, highlight, and export
- Visible broken or ambiguous targets, with optional “create note”
- Default hotkey plus `jotline backlinks NOTE --json`
- Honest empty, locked, and hidden-on-narrow states

Unlinked mentions and a graph view are optional later. They are not required
to make the current feature feel finished.

## Other items that still need to feel like a quality app

Grouped by how much they affect daily use. Several are already named in the
README status section and [ROADMAP.md](../ROADMAP.md).

### Everyday use (do these before new product surfaces)

- **Install and first hour.** Wheel-only install is documented, but there is
  no newcomer study proving someone can install, capture, find, connect, and
  recover a note without the README. Open issues
  [#2](https://github.com/CaulShiver/jotline/issues/2) and
  [#3](https://github.com/CaulShiver/jotline/issues/3) still need a native
  macOS or Windows terminal report and a screen-reader pass.
- **Clipboard, IME, and assistive tech.** Automated PTY smoke does not certify
  OSC 52 copy, CJK/IME composition, or VoiceOver/NVDA announcements.
- **Compact-terminal chrome.** At 80×24 the sidebar, hints, connections, and
  footer hide. Search is still reachable with `Ctrl+F`, but backlinks,
  collections, and status disappear. Keep one obvious way to reach each core
  action when the window is small.
- **Empty and error states.** Some lists already explain themselves.
  Connections, follow, and broken links still say little more than “No
  matching notes yet.”
- **Large-vault performance.** Every search, tag count, and backlink pass
  walks all notes. The in-memory cache helps rereads; very large vaults need
  indexing before more storage complexity.

### Connect and find (the product promise after capture)

- **Backlinks quality slice** above. This is the highest-leverage product gap.
- **Search still has no OR / tag-any / regex.** Phrase, exclusion, and date
  filters exist. The [Drafts review](drafts-feature-review.md) already deferred
  these on purpose.
- **Attachments and subfolders.** Vault files must be flat `*.md`. Images in
  preview and export are not loaded (by design). That is safe, but it blocks
  dropping a screenshot into a note.
- **Cross-workspace links.** Links are workspace-scoped by design. A moved
  note vanishes until you switch workspace. A quality treatment would show
  “linked, other workspace” rather than nothing.

### Trust and recovery (already strong; remaining sharp edges)

History, daily ZIP backups, conflict copies, and `doctor` are real strengths.
Remaining polish:

- Conflict and recovery flows are powerful but easy to fear. The copy-first
  wording helps; newcomers still need a shorter in-app explanation.
- Encryption has no recovery and locked notes fall out of search and
  backlinks. The warnings are honest; the UI around locked notes could be
  clearer.
- Simultaneous edits via Dropbox or iCloud are still not a sync protocol.
  That is fine if stated loudly in Settings, not only in the README.

### Power-user leftovers (only after the writing loop feels done)

From the Drafts review and README future work:

- Regex find/replace
- External executable action steps, action groups
- Plugin / MCP APIs
- System-wide capture hotkeys (docs exist for Hyprland, GNOME, and KDE; not
  first-class)
- Full Vim emulation
- Dictation and AI

These should stay parked. They expand surface area without fixing connect,
discover, or first-run quality.

## Suggested sequence if implementing later

1. **Backlinks quality slice** — panel, snippets, cursor-aware follow,
   fence-aware parse, broken-link state, hotkey, and CLI. Touches `store.py`,
   `app.py`, `export.py`, `cli.py`, and the existing link tests.
2. **Compact-terminal and empty-state pass** — keep connect and search
   reachable at 80×24; better “no backlinks / broken link / locked note” copy.
3. **Hands-on terminal and AT reports** — close issues #2 and #3; fix only
   the failures those reports name.
4. **Indexing design** — measure representative vaults before adding an
   index; backlinks and search should share it.
5. **Search OR / attachments / unlinked mentions** — only with evidence
   people need them.

Discuss changes that alter note formats, shortcuts, or public APIs before
implementation. See [CONTRIBUTING.md](../CONTRIBUTING.md).
