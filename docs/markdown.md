# Markdown editing

The editor colours Markdown as you type: headings, bold, italic, strikethrough,
inline and fenced code, links, `[[note links]]`, tags, lists, tasks, quotes,
rules and tables. Code inside a fence is shown as code, not formatted. Notes stay
plain `.md` files.

Enter continues a bullet (`- `), numbered (`1. ` becomes `2. `), task (`- [ ] `)
or quote (`> `) line. Press Enter on an empty item to end the list.

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
