# Find your way around Jotline

Start typing to capture a thought. Jotline opens the editor directly. The **Quick start** walkthrough opens by itself the first time `jotline` runs on an empty vault, and after that is available above the note list or through Commands. It never adds a guide note to your vault.

The sidebar exposes **Collections**, **Views**, **Filters**, **Actions**, **Import**, and **Quick start**. Tab moves between controls; Enter activates a focused button. On small terminals the sidebar stays hidden until you use your search shortcut (Ctrl+F by default); Esc returns to writing. Collection commands continue to work through the palette. Connections stay reachable too: the status line shows `←N →N`, and Alt+K (or Ctrl+P → Show connections) opens incoming and outgoing notes with the line that contains each link.

**Collections** chooses inbox, projects, areas, resources, archive, trash, starred, or all. The list heading shows the collection and result count. Empty inbox, trash, starred, and PARA lists say what to do next; malformed searches clear stale results and show an error. On 80×24 terminals those messages stay to one line.

The search box searches as you type. Enter opens the top result with the cursor in the editor, Down moves into the list, and Esc clears the query (a second Esc returns to writing). See [keyboard](keyboard.md#the-search-box).

**Filters** edits the search, collection, sort order, and theme in a form. Search supports words, tags, exclusions, and date operators. Invalid queries stay in the form with an explanation. Applying filters does not create a saved view.

While a search with words in it is running, the note list orders results by how
well each note matches rather than by your sort order, and each row gains a
third line quoting the text that matched, with the words in bold. A title hit
counts for more than a body hit, matching more of the query counts for more
than matching less, and a word near the top of a note counts for more than the
same word at the bottom; your sort order still decides between notes that match
equally. A query of only tags or dates matches everything it returns equally
well, so it leaves the order and the two-line rows alone. This is still an
in-memory scan with no index: see [vault scale](vault-scale.md).

Every picker in the app, including the command palette and **Open a note**,
matches the letters you type in order rather than as one run, so `mtgnts`
finds *Meeting notes*. Results are ordered best first and the matched letters
are underlined. Anything the old substring filter found is still found.

**Views** opens saved searches, saves current filters, manages existing views, or clears the current search. **Manage saved views** lets you edit or rename a view, duplicate it, replace its filters with your current settings, or delete its configuration. Edits are validated before saving; name collisions never overwrite another view. Names use lowercase letters, numbers, hyphens, or underscores.

Opening a saved view displays its name beside the collection. Changing its filters adds **(modified)**. Use **Update active saved view from current filters** in Commands to review and save those changes. Switching workspaces, selecting another collection, or clearing the view removes that active-view label. Views remain scoped to their workspace; deleting a view does not delete any notes.

## Search syntax

Search matches all entered words across note bodies; terms are ANDed. `#work`
matches an exact tag, and `planning #work` combines a word and a tag. Search
includes archived notes and excludes the trash unless the trash collection is
selected.

| Syntax | Matches |
| --- | --- |
| `word` | Notes containing the word |
| `"exact phrase"` | The phrase as written |
| `-word`, `-#tag` | Notes without it |
| `#tag`, `tag:work` | Notes with that tag |
| `title:"meeting notes"` | Notes whose title contains it |
| `created-after:2026-09-01`, `created-before:2026-09-30` | Creation date, inclusive |
| `updated-after:today`, `updated-before:today` | Last update, inclusive |

Dates use `YYYY-MM-DD` or `today` (the current local date) and compare against
the calendar date stored in note metadata. Compact dates such as `20260912` are
rejected with a format hint. Regex and OR queries are not supported. The same
queries work in `jotline list` and `jotline tasks`.

## Saved views

**Save current search as a view** keeps its query, collection, sort, workspace
and theme. **Open saved view** lists views in the active workspace, and **Clear
view and search** restores the vault theme and sort. **Delete saved view**
removes a saved configuration. Views persist in vault settings and are included
in backups.

## Tags and workspaces

Press **Ctrl+T** to browse tags and note counts in the current workspace. Pick a
tag to filter notes, or use **Ctrl+P → Add tags to this note** to append tags such
as `#work #ideas #project/topic`. Tags are case-insensitive, can be nested, and
stay in the Markdown body, so edit or remove them in the note itself.

Press **Ctrl+W** to switch or create a workspace, such as `work`, `personal` or
`research`. **Ctrl+P → Move note to workspace** moves the current regular note.
Switching saves pending edits first and stops if saving fails. Jotline remembers
the workspace for your next launch and for shell commands run without
`--workspace`.

Each workspace scopes its collections, tag browser, search, note pickers and
links. Daily logs are separate per workspace and stay in their original
workspace; copy their text into a regular note to move it. Appearance and editor
preferences stay shared across the vault. Existing notes belong to `default`. A
link to a moved note becomes visible again when both notes are in the same
workspace.

Workspace names use 1–48 lowercase letters, numbers, hyphens or underscores,
starting with a letter or number. Workspaces are organization, not access
control: see [your vault](vault.md#what-is-in-the-folder). From the shell, pass
`--workspace NAME`; see [global options](shell.md#global-options) for when
`--new-workspace` is needed.
