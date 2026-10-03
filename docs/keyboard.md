# Keyboard

Jotline is keyboard-first. **F1** shows a cheat sheet of the keys in effect
right now, including any you changed in Settings and the outliner's keys. It is
also in the palette as **Keyboard shortcuts**, and works from the outliner.

## Default keys

| Shortcut | Action |
| --- | --- |
| `Ctrl+N` | New thought |
| `Ctrl+D` | Today's daily log |
| `Ctrl+F` | Search across notes (results are ranked and quote the matched line) |
| `Ctrl+O` | Open a note by title |
| `Ctrl+R` | Recent notes, with the note you just left selected, so Ctrl+R then Enter goes back |
| `Ctrl+G` | Follow the `[[link]]` under the cursor |
| `Ctrl+L` | Toggle the task on this line |
| `Alt+K` | Show incoming and outgoing connections |
| `Ctrl+T` | Browse workspace tags |
| `Ctrl+W` | Switch or create workspace |
| `Ctrl+P` | Searchable command palette |
| `Ctrl+B` | Toggle quiet focus mode |
| `Ctrl+S` | Save immediately |
| `Ctrl+Q` | Save and quit |
| `F1` | Keyboard cheat sheet |
| `Ctrl+,` | Settings (fixed; also Ctrl+P → Settings) |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Move focus out of the editor to the next or previous control |
| `Tab` / `Shift+Tab` | Move between controls outside the editor |
| `Escape` | Close a dialog or palette, return to writing |

Shortcuts use **Control** on macOS too, not Command.

### The command palette

`Ctrl+P` opens on everyday capture, find and recover commands. Type to reach
format, move, export, encryption, daily-log navigation, extract and inbox
processing. Letters match in order rather than as one run, so `mtgnts` finds
*Meeting notes*. Arrows choose, Enter runs, Esc cancels. Each command shows its
key when it has one.

Copy uses the system clipboard on macOS (`pbcopy`) and on Linux when `wl-copy`,
`xclip` or `xsel` is available; otherwise it sends an OSC 52 request. Type
**Clipboard, IME, and screen-reader notes** in the palette for the limits.

### The search box

| Key | Action |
| --- | --- |
| `Enter` | Open the top result and put the cursor in the editor |
| `Down` | Move into the note list with the first row highlighted |
| `Esc` | Clear the query; a second Esc returns to writing |

Tabbing into a list with nothing highlighted highlights its first row. Enter or
Down pressed while you are still typing acts on what you typed, not the previous
results. On narrow terminals, Ctrl+F also reveals the hidden sidebar.

### Find within a note

**Ctrl+P → Find within current note** searches the open note. Opening it with a
word or phrase selected on one line fills that in and jumps to the match. Enter
or F3 goes to the next match, Shift+F3 to the previous one, and Escape returns
to writing. Find has no key by default; assign **Find in this note** in
Settings.

### In the editor

| Key | Action |
| --- | --- |
| `Enter` | Continue a bullet, numbered, task or quote line; on an empty nested item, move it up a level; on an empty top-level item, end the list |
| `Tab` / `Shift+Tab` | Indent at the cursor; on a list item or selected lines, indent or outdent the whole line |
| `Shift+arrows` | Select text |
| `Ctrl+Z` | Undo, including after switching away from the note and back |
| `[[` | Pick a note to link (not inside code) |
| `;;` | Pick a template snippet (not inside code) |
| `Ctrl+click` | Follow the link under the pointer |
| `Shift+F10` | Open the menu for a focused sidebar note ([note list menu](note-menu.md)) |
| `Delete` | Move the highlighted sidebar note to Trash (restore it from the Trash collection) |

Undo history is kept for each of the last eight notes you left. It is dropped
when the note's text changed in between (another program, `$EDITOR`, a task
ticked from the palette, a sync), and is never kept for encrypted or trashed
notes. See [Markdown editing](markdown.md) for formatting commands.

### In the outliner

| Key | Action |
| --- | --- |
| `Enter` / `F2` | Edit the selected block |
| `Ctrl+Tab`, `Ctrl+Shift+Tab` or `F6` | Switch between the tree and the block being edited |
| `Tab` / `Shift+Tab` | Indent / outdent the selected branches |
| `Alt+Shift+Up/Down`, `Ctrl+Up/Down` or `Ctrl+Shift+Up/Down` | Move branches among their siblings |
| `Ctrl+Space` | Fold or expand the branch |
| `Alt+Right` / `Alt+Left` | Focus the branch / go toward the whole note |
| `Ctrl+Enter` | Add a checkbox, then toggle it |
| `Ctrl+F` | Find a block, including folded branches |
| `Shift+Up/Down` | Extend the branch selection |
| `Ctrl+Shift+Backspace` | Delete the selected branches |
| `Ctrl+Z` / `Ctrl+Y` (or `Ctrl+Shift+Z`) | Undo / redo |
| `Ctrl+P` | Outliner commands, each with its keys |
| `Esc` | Leave the block, then return to Markdown |

The full behaviour table is in [Markdown editing → Outliner](markdown.md#outliner).

## Change a key

Open **Ctrl+, → Keyboard shortcuts**. Every application command above can be
reassigned, and these start unassigned so you can give them a key:

- Markdown preview, side-by-side preview, jump to heading, open outliner
- Every formatting command: bold, italic, strikethrough, inline code, heading,
  bullet, numbered and task lists, quote, code block, link, image, table,
  horizontal rule, indent and outdent lines
- Previous daily log, next daily log, open daily log by date
- Extract selection to new note, process next inbox note
- Edit this note in `$EDITOR`
- Back to previous note, find in this note

Use `ctrl+letter`, `alt+letter`, or `f1`–`f12` (for example `alt+n` or `f4`).
`Ctrl+,` and `Escape` stay fixed. Duplicate assignments are rejected, and so are
the editing and terminal keys `ctrl+a`, `c`, `e`, `h`, `i`, `j`, `k`, `m`, `u`,
`v`, `x`, `y` and `z`. Clear a field to unassign an optional command.

Choose **Save** (or Ctrl+S inside Settings) to apply at once; the footer,
palette and cheat sheet update too. **Reset hotkeys** restores the default keys
without changing your other preferences; save to apply or press Escape to
cancel. Hotkeys are stored in `.jotline-settings.json` inside the vault and
apply to all its workspaces.

When a release adds a default key that you had already given to something else,
yours wins and the new command starts unassigned. Ctrl+R, Ctrl+G, Ctrl+L and F1
work this way, and can be cleared.

Every outliner command also has an optional key under **Settings → Outliner
shortcuts**. A key already used by an application command cannot be assigned
to an outline command, and an outliner shortcut takes its key away from the
outliner's built-in binding.

## Terminal caveats

Your terminal, multiplexer or desktop sees a key before Jotline does. When one
of them keeps a key, use the palette or assign another key.

- **Ctrl+,** is not a standard control character, so many terminals never send
  it. Use **Ctrl+P → Settings**.
- **F1**: some terminals keep F1 for their own help. Use **Ctrl+P → Keyboard
  shortcuts**, or assign the cheat sheet another key.
- **Alt on macOS**: Alt+K, the outliner's Alt+arrows and Alt+Up/Down in
  **Arrange lines** need the Option key to send Meta. In Terminal.app turn on
  **Use Option as Meta key** (Settings → Profiles → Keyboard); in iTerm2 set
  the Left Option key to **Esc+** (Settings → Profiles → Keys). In the outliner,
  Ctrl+Up/Down and Ctrl+Shift+Up/Down move branches without Alt. If macOS
  Mission Control takes Ctrl+Up/Down, use the Ctrl+Shift form.
- **tmux**: Ctrl+B is tmux's default prefix, so focus mode never reaches
  Jotline. Press Ctrl+B twice to send it through, or assign focus mode another
  key.
- **Ctrl+Tab**: most terminals send it as plain Tab. In the outliner use F6 to
  switch between tree and block; in the editor, Ctrl+F reaches the search box.
- **Shift+Enter**: some terminals send it as Enter. In the outliner use
  **Commands → Insert continuation line**, or give it a key.
- **Readline keys**: Ctrl+W (workspaces) and Ctrl+D (daily log) are Jotline
  commands, so the editor's delete-word-left and delete-right are not on those
  keys. Alt+Backspace and Delete still work. The cheat sheet says which ones
  your current keys take over.
