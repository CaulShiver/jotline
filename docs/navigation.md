# Find your way around Jotline

Start typing to capture a thought. Jotline opens the editor directly; the optional **Quick start** walkthrough is available above the note list or through Commands. It opens a preview without adding a guide note to your vault.

The sidebar exposes **Collections**, **Views**, **Filters**, **Actions**, **Import**, and **Quick start**. Tab moves between controls; Enter activates a focused button. On small terminals the sidebar stays hidden until you use your search shortcut (Ctrl+F by default); Esc returns to writing. Collection commands continue to work through the palette. Connections stay reachable too: the status line shows `←N →N`, and Alt+K (or Ctrl+P → Show connections) opens incoming and outgoing notes with the line that contains each link.

**Collections** chooses inbox, projects, areas, resources, archive, trash, starred, or all. The list heading shows the collection and result count. Empty inbox, trash, starred, and PARA lists say what to do next; malformed searches clear stale results and show an error. On 80×24 terminals those messages stay to one line.

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
