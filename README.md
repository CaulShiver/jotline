# ›_ jotline

**A little room to think.** A keyboard-first terminal app for Linux, macOS, and Windows for capturing thoughts, writing, and connecting notes. Inspired by the quick-capture spirit of Drafts, with an original terminal interface.

![Jotline terminal workspace](docs/screenshot.svg)

Jotline opens to a blank page. Start typing; your writing saves automatically to local Markdown files. Press `Ctrl+P` when you want to do something with it.

## Install

Requires Python 3.11+ and a terminal with Unicode and color support on Linux,
macOS, or Windows. Windows runs natively; WSL is optional. Download the wheel from
the [latest release](https://github.com/CaulShiver/jotline/releases/latest), then
run one of these commands in its download folder. Git is not required.

With [uv](https://docs.astral.sh/uv/):

```sh
uv tool install ./jotline-0.9.3-py3-none-any.whl
jotline
```

Or with pipx:

```sh
pipx install ./jotline-0.9.3-py3-none-any.whl
jotline
```

To update, download the new wheel and repeat your install command with `--force`.
Run `jotline backup` first. Uninstall with `uv tool uninstall jotline` or
`pipx uninstall jotline`; your vault remains on disk. See the
[install, update and rollback guide](docs/install.md) for PATH help, plain Python
installation, and checksums.

For development (requires Git):

```sh
git clone https://github.com/CaulShiver/jotline.git
cd jotline
uv sync --extra dev
uv run jotline
uv run pytest
```

## The everyday loop

1. **Capture.** `Ctrl+N` starts a thought. No required title, folder, or tags.
2. **Log.** `Ctrl+D` opens today's page. Mix observations with Markdown tasks: `- [ ] Follow up`.
3. **Connect.** Keep durable ideas in separate notes. Insert links and follow backlinks through the command palette.
4. **Review.** Run **Start weekly review** for a checklist. Move notes into projects, areas, resources, or archive when useful.

These are optional practices, not a compulsory system. An inbox and search are enough to start.

The sidebar offers **Collections**, **Views**, **Filters**, **Actions**, **Import**,
and **Quick start**. The optional walkthrough opens without creating a note or
replacing your writing. On narrow terminals, Ctrl+F reveals the sidebar; Escape
returns to writing. Empty lists explain how to find other notes or adjust filters.
All features also remain available from Ctrl+P. See [navigation and saved
views](docs/navigation.md).

The design draws on [Drafts' quick capture](https://docs.getdrafts.com/gettingstarted/), [GTD's capture and reflection](https://gettingthingsdone.com/what-is-gtd/), [Bullet Journal's daily rapid logging](https://bulletjournal.com/pages/how-to-bullet-journal), [Zettelkasten's connected ideas](https://zettelkasten.de/overview/), and [PARA's organization by use](https://fortelabs.com/blog/para/). Jotline is independent of these products and authors.

## Keyboard

| Shortcut | Action |
| --- | --- |
| `F1` | Open Settings (always available) |
| `Ctrl+N` | New thought |
| `Ctrl+T` | Browse workspace tags |
| `Ctrl+W` | Switch or create workspace |
| `Ctrl+P` | Searchable command palette |
| `Ctrl+O` | Open a note by title |
| `Ctrl+D` | Today's daily log |
| `Ctrl+F` | Search across notes |
| `Ctrl+B` | Toggle quiet focus mode |
| `Ctrl+S` | Save immediately |
| `Ctrl+Q` | Save and quit |
| `Tab` / `Shift+Tab` | Move between controls |
| `Escape` | Close palette / return to writing |

The palette also offers star, move, restore from trash, task toggle, link insertion/navigation, backlinks, recovery copies, and a writing guide. Type words to narrow commands, use arrows to choose, then Enter. Standard text selection, undo, and redo are provided by the editor. Clipboard copy uses OSC 52 and depends on your terminal's permissions and support.

## Move or delete with the mouse

Right-click a note in the sidebar to open its action menu. Choose **Move to
collection…**, **Move to workspace…**, or **Delete · Move to Trash**. The menu
acts on the clicked note, even when another note is open. Pending editor changes
are saved before a move; a failed save leaves the note in place.

In Trash, right-click and choose **Restore to Inbox**. Daily logs can move between
collections but stay in their original workspace. Create workspaces with Ctrl+W.
Click outside the menu or press Escape to cancel. You can also focus a sidebar
note and press **Shift+F10** to open the menu, then use arrows and Enter.

## Make it yours

Open **Ctrl+P → Settings**. Change preferences with Tab, arrows, and Space; choose
**Save** (or Ctrl+S) to apply them. Escape cancels. **Use defaults** fills the form
with the original settings; nothing changes until you save.

- **Seventeen themes:** Jotline, Nord, Gruvbox, Dracula, Tokyo Night, Monokai,
  Flexoki, Catppuccin Mocha/Latte/Frappé/Macchiato, Rosé Pine/Moon/Dawn,
  Solarized dark/light, and Textual light. For a light background, try
  Catppuccin Latte, Rosé Pine Dawn, Solarized light, or Textual light.
- **Editor:** line numbers, wrapping, and current-line highlighting.
- **Layout:** sidebar width, writing hints, and starting in focus mode.
- **Workflow:** open a blank thought or today's log, choose the collection for new
  thoughts, and sort notes by last edit, creation date, or title (stars stay first).
- **Autosave:** choose an interval from 0.2 to 5 seconds.
- **Daily template:** write your own Markdown structure. `{{date}}` inserts the
  current date. Existing daily logs are never replaced when the template changes.

Settings live in `.jotline-settings.json` inside each vault and survive restarts.
Shell capture uses the same default collection and daily template. Daily logs stay
in the inbox unless you move them. Font family and size come from your terminal.

![Jotline settings](docs/settings.svg)

## Search and links

Search matches all entered words across note bodies. `#work` matches an exact tag; `planning #work` combines a word and a tag. Search includes archived notes and excludes trash unless the trash collection is selected. Tags are case-insensitive and can be nested, such as `#project/launch`.

Use **Ctrl+P → Find within current note** to search the current document without
changing the vault search. Enter or F3 advances to the next match, Shift+F3 goes
back, and Escape returns to writing. Navigation moves past the selected match
whether you selected its text forwards or backwards. Clearing the search leaves
the editor selection in place. **Refresh vault** updates the list and backlinks after
shell captures or external changes while retaining the current editor buffer.

![Find within a note](docs/find.svg)

Inserted links use `[[stable-id|Readable title]]`. Renaming a heading does not break these links. Manually entered `[[Exact title]]` links also work, but ambiguous titles can match several notes. Use **Follow a link in this note** and **Open a backlink** in the palette.

## Use it from your shell

```sh
jotline capture "A thought before I forget"
printf 'Meeting notes\n\nNext step: draft the outline\n' | jotline capture
jotline capture --daily "- [ ] Send the outline"
jotline list '#work'
jotline doctor
jotline doctor --json
jotline import ~/Downloads/meeting.md
jotline export NOTE_ID > note.md
jotline path
jotline --vault ~/Notes/Jotline
```

Set `JOTLINE_VAULT` to use a different vault by default, or pass
`jotline --vault "path/to/notes"`. Run `jotline path` to see the active location.

| Platform | Default vault |
| --- | --- |
| Linux | `$XDG_DATA_HOME/jotline/notes`, normally `~/.local/share/jotline/notes` |
| macOS | `~/Library/Application Support/jotline/notes` |
| Windows | `%LOCALAPPDATA%\jotline\notes` |

On macOS, an explicitly set `XDG_DATA_HOME` or an existing vault at the old
`~/.local/share/jotline/notes` location continues to be used.
In PowerShell, set an override with `$env:JOTLINE_VAULT = 'C:\Notes'`; in a
macOS/Linux shell, use `export JOTLINE_VAULT="$HOME/Notes"`.

Use a local filesystem with hard-link support (such as NTFS on Windows or APFS
on macOS). Windows rejects symlinks, junctions, and other reparse points inside
storage; cloud placeholder files must be copied to a regular local vault.
File contents are flushed before publication on every platform. Windows does
not provide POSIX directory flushing, so metadata durability after a power loss
depends on the filesystem. Unix permission warnings apply only on Linux/macOS;
Windows access is controlled by the folder's ACLs.

Shortcuts use **Control** on macOS too. If a terminal intercepts a shortcut,
use F1 to customize it in Settings.

`jotline doctor` checks the runtime, vault path, settings, lock, templates, history,
backups, limits, and readable note counts. It prints diagnostics rather than note
bodies, reports unsafe or broken local state, and exits nonzero when it finds a
problem. Use `jotline doctor --json` for machine-readable output in bug reports or
scripts. `jotline import FILE` copies a regular UTF-8 file into a new note in your
default collection; the original file is left untouched. Imports refuse symlinked
files and symlinked source directories.

Use **Import** in the sidebar to preview a file, folder, or Drafts `.draftsExport`
library, then confirm the import. Folder imports include subfolders in the app.
Drafts imports preserve dates, inbox/archive/trash state and flags, and map tags
into the note text. Matching bodies or Drafts IDs are skipped by default.
Warnings and partial failures are reported; existing notes are never overwritten.

```sh
jotline import ~/Downloads/notes --recursive          # preview
jotline import ~/Downloads/notes --recursive --apply  # import
jotline import ~/Downloads/library.draftsExport      # preview
jotline import ~/Downloads/library.draftsExport --apply
```

CLI imports also support `--preview` for a single text file and
`--duplicates copy` to create separate copies. See [import and recovery
details](docs/import-recovery.md) for limits and metadata mapping.

Redirected export preserves the note body, including line endings. Export and
`run` to an interactive terminal refuse control characters (escape sequences,
bidirectional overrides) unless you explicitly pass `--raw`; ordinary text such
as CRLF endings, joined emoji and soft hyphens prints normally. Diagnostics
escape terminal control characters.

## Customize hotkeys

Open **F1 → Settings → Keyboard shortcuts**. Change shortcuts for new notes,
tags, workspaces, commands, opening notes, daily logs, search, save, focus, and quit.
Optional fields also support Markdown preview and formatting actions.
Use `ctrl+letter`, `alt+letter`, or `f2`–`f12` (for example `alt+n` or `f4`).
Duplicate assignments and reserved editing/navigation keys are rejected.

Choose **Save** (or Ctrl+S inside Settings) to apply immediately; the footer and
command hints update too. **Reset hotkeys** restores shortcut defaults without
changing your other preferences; save to apply or Escape to cancel. **F1** always
opens Settings, and **Escape** remains fixed for closing dialogs. Editor shortcuts
and dialog navigation are unchanged. Your terminal may intercept some combinations;
use another supported key if it does.

Hotkeys persist locally in `.jotline-settings.json` inside the vault and apply to
all its workspaces. The shortcut table above shows the defaults.

## Tags and workspaces

Press **Ctrl+T** to browse tags and note counts in the current workspace. Select a
tag to filter notes, or use **Ctrl+P → Add tags to this note** to append tags such
as `#work #ideas #project/topic`. Tags are case-insensitive and stay in the Markdown
body: edit or remove them directly in the note. Search can combine words and tags.

Press **Ctrl+W** to switch or create a workspace, such as `work`, `personal`, or
`research`. **Ctrl+P → Move note to workspace** moves the current regular note.
Switching saves pending edits first and stops if saving fails. Jotline remembers
the workspace for your next launch and shell captures.

Each workspace scopes its collections, tag browser, search, note pickers, and
links. Daily logs are separate per workspace and stay in their original workspace;
copy their text into a regular note if you want to move that content. Appearance
and editor preferences remain shared for the vault.

Existing notes belong to `default`. Workspaces are organization, not access control:
**all Markdown files remain directly in your existing local notes folder**, with
workspace membership recorded in their front matter. Moving a note preserves its
filename and contents. A link to a moved note becomes visible again when both
notes are in the same workspace. No account, database, or new dependency is needed.
Workspace names use 1–48 lowercase letters, numbers, hyphens, or underscores,
starting with a letter or number. Use this version or later when editing workspace
notes; older versions do not preserve the new metadata field.

```bash
jotline workspaces
jotline --workspace work                  # open the terminal app
jotline --workspace work capture 'Meeting #team'
jotline --workspace work capture --daily 'Today’s progress'
jotline --workspace work tags
jotline --workspace work list '#team'
jotline --workspace work tag NOTE_ID ideas project/topic
```

Put `--workspace` before the subcommand. Without it, commands use the last
workspace selected in the app. `path` reports the shared vault folder and `doctor`
checks the entire vault.

## Your data

- Local `.md` files; no account, telemetry, hosted backend, or network requirement at runtime.
- Small Jotline front matter with JSON-valued fields stores collection, timestamps, and starred state.
- Atomic, fsynced saves. Normal exit saves pending edits. Abrupt termination may lose the last autosave interval (0.7 seconds by default; configurable).
- Jotline coordinates its own writers and detects external edits before saving. It will block navigation/exit on a save failure so the buffer remains available. **Save recovery copy** preserves your buffer as a new inbox note.
- Trash is reversible. There is no permanent-delete command.
- Keep a backup of your vault. Sync and encryption are up to your existing tools; simultaneous edits through an external editor or sync provider are not a collaborative editing protocol.
- Only the source code is published to GitHub. Your notes are stored separately.

On a save conflict, a comparison dialog offers **Save copy, then review external
version**, **Save and open recovery copy**, or **Keep editing**. Both save options
preserve your full local draft before changing what is open. If recovery fails,
the unsaved editor text stays available. Use **Review external change and recover
draft** in Commands to reopen the dialog. Large comparisons show excerpts while
preserving the complete draft.

Notes are limited to 10 MiB including metadata; settings to 256 KiB. Symbolic links
and special files are skipped and reported. A busy vault lock returns an error after
about one second so the app can recover instead of hanging. `jotline doctor` also
warns when the vault directory is not writable, because capture and app saves need
write permission even though reading existing notes may still work.

External Markdown files can be placed directly in the vault with filenames containing letters, numbers, underscores, or hyphens. Existing non-Jotline front matter remains part of their body. Subdirectories and attachment management are not supported in this version. An in-memory cache avoids reparsing unchanged notes. Each scan still checks file
metadata for changes. Cached content expires after one second and is reread on the
next scan, even if an external edit preserves all tracked timestamps. Refresh vault
clears the cache immediately. Very large vaults may
still need further indexing work.

## Local backups and note history

Jotline automatically saves note revisions inside your vault's
`.jotline-history/` folder. It retains the first saved version from each of the
latest 30 minutes with edits, plus the two latest saves (up to 32 versions per note).
Intermediate autosaves within a minute are consolidated. This begins with this
release; it cannot recover edits made before history was enabled.

Use `Ctrl+P` → **History of this note**, select a version, inspect its text, and
choose **Restore as new note**. Restoration creates a separate inbox note and
preserves your current writing. **Browse saved note history** also finds history
for notes deleted outside Jotline, within the active workspace.

A ZIP backup is created before the first changed note save each day. It contains
the vault's current Markdown notes, settings and custom templates. Use `Ctrl+P` →
**Back up vault now** or `jotline backup` for an immediate snapshot. The latest
seven archives remain in `.jotline-backups/`, including today's automatic archive.
Archives exclude history and other backups. Each archive has a manifest listing
any unreadable or unsafe files that were skipped.

For whole-vault recovery, extract a ZIP into a separate folder and launch
`jotline --vault /path/to/recovered-folder`. All backups stay on this computer;
copy an archive elsewhere if you want protection against disk loss.

## Reusable templates

`Ctrl+P` → **New note from template** offers meeting, project, and journal
starters alongside your own templates. Templates create a new note in the active
workspace and default collection, after saving your current writing.

To make your own, write its structure in a note and choose **Save this note as a
template**. Give it a unique lowercase name such as `weekly-planning`. Custom
files live in `.jotline-templates/<name>.md` within your vault and are shared
across workspaces. Existing names are never overwritten by this command.

Use `{{date}}`, `{{time}}`, and `{{workspace}}` for the current local date, time,
and workspace. **Copy template source to new note** preserves these placeholders
so you can customize a starter and save it under a new name. You can also edit
custom template files directly in your text editor. Built-in starters are bundled
with the app; your saved templates stay local and are included in ZIP backups.

## Markdown formatting

Select text with Shift + arrow keys, then open `Ctrl+P` and choose **Format bold**,
**Format italic**, or **Format inline code**. With no selection, a selected `text`
placeholder is inserted. **Format heading**, **Format bullet list**, and
**Format blockquote** apply to the current line or selected lines. Use the editor's
normal Undo shortcut (`Ctrl+Z`) to reverse a formatting change.

Open `F1` → **Keyboard shortcuts** to assign keys for preview, bold, italic,
inline code, headings, bullet lists and quotes. These optional shortcuts start
blank, preserving your existing key choices. Clear a field to unassign it;
**Reset hotkeys** clears these additions and restores the original shortcuts.

Choose **Preview rendered Markdown** from `Ctrl+P` to see headings, emphasis,
lists, quotes, tables, and fenced code blocks inside the terminal. Preview includes
unsaved writing. Scroll with the arrow/Page Up/Page Down keys or mouse; press
`Esc` to return to the same editor selection. Preview is a read-only snapshot;
reopen it after editing. Notes stay plain Markdown on disk.

Preview supports notes up to 256 KiB to keep rendering responsive. Larger notes
remain editable and saveable. Images, raw HTML, and interactive task checkboxes
are not rendered as browser content. Preview links do not open files or browsers;
use **Follow a link** for Jotline's `[[note links]]`.

## More writing and review tools

The command palette now includes:

- **Find within current note:** enter replacement text and choose Replace or
  Replace all. Match case is optional. Replacements are literal; Undo reverses
  one replacement operation. F3/Shift+F3 still navigate matches. If replacement
  would exceed the note size limit, the text stays unchanged and the dialog
  shows **Not replaced**. A rejected single replacement keeps the selected match
  so you can shorten the replacement and retry.
- **Jump to heading**, **Previous note**, and **Recent notes:** move around
  Markdown headings and the notes visited this session. Returning to a note
  restores its cursor position; recent notes stay scoped to the workspace.
- **Insert template at cursor** and **Insert note text at cursor:** replace the
  current selection, or insert at the cursor. Type `[[` for note-link suggestions
  or `;;` for template snippets; arrows and Enter choose, Escape cancels.
- **Arrange lines / Arrange paragraphs:** arrows select an item, Alt+Up/Down moves
  it, Ctrl+D duplicates it, Ctrl+S applies, and Escape cancels. Apply is one Undo
  operation. Arrangement supports up to 256 KiB and 5,000 items.
- **Select notes for bulk operations:** Space selects notes from the current
  search, Ctrl+S opens operations. Archive, trash, star, tag, or merge. Merge
  creates a new inbox note and keeps originals. Other operations report partial
  failures; successfully processed notes remain changed.

Search supports `"exact phrases"`, `-excluded`, `-#tag`, `tag:work`, and
`title:"meeting notes"`. Combine these with `created-after:2026-09-01`,
`created-before:2026-09-30`, `updated-after:today`, or `updated-before:today`.
Dates must use `YYYY-MM-DD` or `today`; compact dates such as `20260912` are
rejected with a format hint. Date boundaries are inclusive and use the calendar
date stored in note metadata; `today` is the current local date. Terms are ANDed.
Regex and OR queries are not supported.

Choose **Save current search as a view** to keep its query, collection, sort,
workspace and theme. **Open saved view** lists views in the active workspace;
**Clear view and search** restores the vault theme and sort. Views can overlap
without moving notes between workspaces. **Delete saved view** removes a saved
configuration. Views persist in vault settings and are included in backups.

**Views → Edit, rename or duplicate views** opens a form for existing views.
**Filters** adjusts the query, collection, sort and theme without saving a view.
The list heading names the active view and marks it modified when filters differ.
Use **Update active saved view from current filters** to save those changes.

Templates additionally accept `{{title}}`, `{{body}}`, `{{selection}}`,
`{{date:%Y-%m-%d}}` (strftime formatting), and `{{template:other-name}}`.
Title/body/selection refer to the current note when inserting a template or
running an action; they are empty when creating a new note from a template.
Inserted context is literal, and unknown placeholders stay unchanged. Includes
are limited to eight levels and 64 expansions, with a 10 MiB output limit.

## Local actions and shell automation

Open **Actions → Start from a recipe** for copy-clean-text, copy-markdown-quote,
create-from-template, or append-and-archive. The builder lets you name the action,
choose operations, edit values, reorder steps and select append targets by note
title. **Preview** shows intended effects and output without changing notes or
using the clipboard. Save the recipe, then choose **Run a saved action** to run it.
Copy/create starter recipes preserve your source text.

**Actions → Edit or share an action** supports editing, renaming, duplication and
export to a portable JSON file. **Import recipes** adds recipes without running
them. **Action history** shows up to 100 runs and the outcome of each step, without
storing note bodies or template values. Logs are limited to 256 KiB in
`.jotline-action-history.json`. Earlier side effects can remain after a failed
action; inspect its history before retrying.

See the [action builder and sharing guide](docs/actions.md) and
[community recipes](examples/actions/README.md). You can also define actions
directly as JSON:

Write a JSON step list in a note and choose **Save action recipe from this note**,
then give it a unique name. **Run local action** lists saved recipes; **Delete
local action** removes one. Recipes are shared across the vault, run in the active
workspace, and are stored in settings and included in backups. For example:

```json
[
  {"type": "template", "value": "{{body}}\n"},
  {"type": "append", "value": "TARGET_NOTE_ID"},
  {"type": "archive"}
]
```

Replace `TARGET_NOTE_ID` with a project note's actual ID. The recipe appends the
current text followed by a newline, then archives the source after success.

Available step types are `uppercase`, `lowercase`, `strip`, `template` (with a
`value` containing template text), `append` (with a target note ID in `value`),
`archive`, `copy`, `export`, `quote`, and `restore`. `quote` prefixes each line for
a Markdown blockquote. `restore` resets the working text to
the source text without undoing earlier effects or collection changes; copy/create
recipes use it to preserve the source. There can be up to 16 steps per recipe. Copy uses
the terminal clipboard and is available in the app. Export creates a new inbox
note in the app, or writes to stdout in the CLI. To create a plain Markdown file,
redirect CLI output. Text transforms and archive status are saved to the source
only after all steps succeed. If a later step fails, earlier append/export/copy
side effects remain applied; review before retrying to avoid duplicate output.
Actions cannot append a note to itself or access a different workspace.

```sh
jotline append NOTE_ID 'Next step'
printf 'Introduction' | jotline prepend NOTE_ID
jotline open NOTE_ID
jotline list 'tag:work -blocked' --json
jotline actions
jotline run ACTION_NAME NOTE_ID > output.md
jotline run ACTION_NAME NOTE_ID --raw
```

Append/prepend put the text on its own line: when it would otherwise run into
the note, they add one line break in the note's newline style. Pass
`--no-newline` to join the text exactly as supplied.
`list --json` returns metadata and tags, not note bodies. `open` takes precedence
over the startup-page preference. Use `--workspace NAME` before a subcommand to
choose a different workspace. All updates use normal locking, history and conflict
detection. Recipes execute only these built-in steps; there is no shell evaluation.

## Status

Version 0.9.3 is an early release. It offers Markdown source editing, rendered
preview, configurable local actions, and guided import/recovery workflows. See
[CHANGELOG.md](CHANGELOG.md) and [ROADMAP.md](ROADMAP.md). Full Vim emulation,
cloud sync, plugins, dictation and system-wide capture hotkeys remain future work.
Automated cross-platform checks and a POSIX terminal smoke test complement the
[native terminal and accessibility checklist](docs/terminal-testing.md);
clipboard, IME and screen-reader compatibility still needs hands-on verification.
See [Release verification](docs/release-verification.md) for the local test results
and the limits of that coverage.

## Contributing

See the [multi-model review](docs/redteam-review.md) for findings, fixes, and test coverage.
The [September 12 hardening and usability review](docs/hardening-2026-09-12/hardening.md)
documents the replacement feedback, selection navigation, and date-validation
fixes. This focused pass passed 254 tests with 3 platform-specific skips on Linux,
plus a fresh installed-wheel CLI and terminal workflow smoke check.

Bug reports and focused pull requests are welcome. The package version is sourced
from `src/jotline/__init__.py`; release builds and `jotline --version` use that same
value. See [CONTRIBUTING.md](CONTRIBUTING.md) for development and release checks,
[ROADMAP.md](ROADMAP.md) for starter contributions, and [SECURITY.md](SECURITY.md)
for private vulnerability reporting. Licensed under [MIT](LICENSE).
