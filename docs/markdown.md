# Markdown editing

The editor colours Markdown as you type: headings, bold, italic, strikethrough,
inline and fenced code, links, `[[note links]]`, tags, lists, tasks, quotes,
rules and tables. Code inside a fence is shown as code, not formatted. Notes stay
plain `.md` files.

Enter continues a bullet (`- `), numbered (`1. ` becomes `2. `), task (`- [ ] `)
or quote (`> `) line. Press Enter on an empty item to end the list.

**Tab** inserts indentation at the cursor. On a list item or selected lines it
indents the whole line or selection by two spaces; **Shift+Tab** removes one
level. Enter keeps the current indentation, including in plain text and code
blocks. Use **Ctrl+Tab** / **Ctrl+Shift+Tab** to move focus out of the editor,
or **Ctrl+F** to search notes. Hover descriptions stay hidden.

Select text with the mouse or Shift + arrow keys, then click **Bold**, **Italic**,
**H**, **List**, **Task**, **Link**, or **Code** above the editor. **More** opens
all formats, and **Preview** shows the rendered note. The toolbar scrolls in
narrow windows and hides in focus mode. Selections keep Markdown's theme colours
over a tinted background; the cursor also uses the active theme's accent.

You can also open **Format** in the sidebar for the Markdown menu, or type
**format** in Ctrl+P. Each command toggles, so running it again removes the
formatting:

| Command | Result |
| --- | --- |
| Format bold / italic / strikethrough / inline code | `**text**`, `*text*`, `~~text~~`, `` `text` `` around the selection, or a selected placeholder |
| Format heading, heading level 1–6 | `#` to `######` on the current or selected lines; a different level replaces the old one |
| Format bullet / numbered / task list, blockquote | `- `, `1. 2. 3.`, `- [ ] `, `> ` on each selected line |
| Format indent lines / outdent lines | Two spaces in or out, for nested lists |
| Format code block | Wraps the selected lines in a fence long enough for any backticks inside |
| Format link / image | `[text](url)` or `![alt text](path)`; a selected URL becomes the target |
| Format table · insert or tidy | Inserts a table, or lines up the columns of the table under the cursor (alignment colons kept) |
| Format horizontal rule | `---` on its own line |

**Preview rendered Markdown** opens a full-screen preview. **Toggle side-by-side
Markdown preview** keeps a live preview beside the editor that follows your
typing and cursor; it needs a terminal wider than 80 columns, and below that the
full preview opens instead. Both previews show checkboxes as ☐/☒ and note links
as note titles, and neither opens links or loads images. **Jump to heading**
lists the note's headings for quick navigation.

Every formatting command, both previews and the heading outline can have its own
key in **Ctrl+, → Keyboard shortcuts**; they start unassigned. **Ctrl+, → Editor**
turns Markdown highlighting or list continuation off.

There is no second Vim editor. Optional motions are out of scope.

## Outliner

Choose **Outliner** above the editor, or **Ctrl+P → Outliner**. Blocks wrap in
one outline surface. Use arrows or click to navigate, then **Enter** or **F2**
to edit directly on the selected row. **Ctrl+Tab** switches between editing
text and navigating branches. **F7** selects the block's text without selecting
its children. **Commands** exposes every outline operation by name.

| Control | Result |
| --- | --- |
| Enter at the beginning of nonempty text | Insert an empty preceding sibling; the original block keeps its children |
| Enter in the middle or at the end | Split into a sibling after the branch; children stay with the first block |
| Enter in an empty child | Outdent one level |
| + Child / Insert child block | Add a child and start editing it |
| Shift+Enter / Commands → Insert continuation line | Insert a line within the block |
| Backspace at the start / Merge block | Join with the previous sibling when safe; preserve descendants |
| Up / Down while editing | Move within wrapped text, then to the neighboring visible block at the boundary |
| Tab / Shift+Tab | Indent / outdent the selected branches |
| Alt+Shift+↑ / ↓ | Move selected branches among their siblings |
| Ctrl+Space / Fold / disclosure arrow | Collapse or expand the branch |
| Left / Right while navigating | Collapse or go to parent; expand or go to first child |
| Home / End while navigating | First / last visible block |
| Type a letter while navigating | Next visible block beginning with that letter |
| Alt+→ / Focus | Focus the current branch |
| Alt+← / clickable breadcrumb | Navigate toward the whole note |
| Ctrl+Enter / Task | Add a checkbox, then toggle it |
| Ctrl+F / Find | Search all blocks and ancestor paths, including folded branches |
| Shift+↑ / ↓ while navigating | Extend branch selection |
| Ctrl+click / Select or deselect branch | Toggle branch selection |
| Ctrl+Shift+Backspace / Delete selected branches | Delete selected branches and descendants |
| Ctrl+Z / Ctrl+Y | Undo / redo text edits and structural changes |
| Ctrl+S | Save immediately; autosave also runs while outlining |
| Esc | Leave text editing, then return to Markdown |

If a terminal sends Shift+Enter as ordinary Enter, use **Commands → Insert
continuation line** or assign that command a portable shortcut in Settings.
Every outline command has an optional override under **Settings → Outliner
shortcuts**. A shortcut already used by an application command cannot also be
assigned to an outline operation. The command palette and Save honor their
application shortcut preferences.

**Working with several blocks.** Selected rows are highlighted independently
of the caret. Selecting both a parent and a descendant operates on the parent
once. The command menu includes **Move selected branches to…**, **Group selected
sibling branches**, **Duplicate**, **Copy**, **Cut**, and **Paste clipboard as
outline branches**. Move destinations are within the current note. A parent
cannot be moved into its own descendant. Grouping preserves branch order.

**Pasting.** Outline paste uses text copied within Jotline and retains its
hierarchy. **Paste clipboard as literal block text** escapes leading structural
Markdown markers. Multiline terminal paste also defaults to escaping those
markers, so pasted bullets do not unexpectedly absorb or rearrange children.
Ordinary text editing still supports Markdown; typing structural Markdown
updates the outline to match the saved source. A full-height block inspector
is available in Commands for long passages.

**Navigation and saving.** Note commands, daily logs, formatting, note-link
completion (`[[`), and snippets (`;;`) are available while outlining. Search
reveals the result's ancestors; **Restore folds after search** restores the
previous folding state. **Previous / Next outline location** return through
branch-focus history. Folds, focused branch, caret, and scroll position are
remembered for unencrypted notes in `.jotline-outline.json`. That file contains
positions and a revision hash. Encrypted notes keep view state only while open;
encrypting a note removes its saved view state. External edits invalidate stored positions.
View operations do not enter text undo history; undo preserves unrelated folds.
Enable **Settings → Open notes in outliner mode** to make this the default.

**Markdown ownership.** List structure follows CommonMark marker widths,
four-column tab stops, and code-container boundaries. Parent paragraphs after
nested lists remain part of the parent when a child moves or is deleted.
Existing Markdown opens without conversion. Non-list containers, including
block quotes and code, remain editable Markdown blocks. Restructuring a plain
block explicitly converts it to a bullet. Empty or non-1 numbered children may
need a blank separator to remain nested in CommonMark; Jotline inserts it.
Very deep input beyond the parser's nesting limit remains preserved as text
inside the deepest recognized block. Splitting a block keeps children with the
first half; merging fenced blocks or completed tasks requires an explicit text
edit rather than an automatic join.

**Permanent block references.** **Copy permanent block reference** adds a unique
`^id` only when needed and copies `[[note-id#^id]]`. References survive edits and
moves within the note. Duplicating or pasting branches creates fresh session
identities and removes copied anchors. **Open block reference** navigates to the
target; **Preview referenced branch** opens a read-only preview of its current
text. Preview is one level deep, so cyclic references do not recurse. This is
Jotline's explicit Markdown extension, not a promise of complete Logseq graph
compatibility. Embeds are previews, not independently editable mirrors.
