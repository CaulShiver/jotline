# ›_ jotline

**A little room to think.** A keyboard-first terminal app for Linux, macOS, and Windows for capturing thoughts, writing, and connecting notes. Inspired by the quick-capture spirit of Drafts, with an original terminal interface.

![Jotline terminal workspace](docs/screenshot.svg)

Jotline opens to a blank page. Start typing; your writing saves automatically to local Markdown files. Press `Ctrl+P` when you want to do something with it.

## Install

Linux, macOS, and Windows. Python 3.11+. Git is not required. Windows runs
natively; WSL is optional. The same package is published for every supported OS.

Linux / macOS:

```sh
curl -fsSL https://github.com/CaulShiver/jotline/releases/latest/download/install.py | python3
jotline
```

Windows (PowerShell):

```powershell
irm https://github.com/CaulShiver/jotline/releases/latest/download/install.ps1 | iex
jotline
```

From PyPI, once the tagged release is on the index:

```sh
uv tool install jotline
# or: pipx install jotline
jotline
```

To update, re-run the installer with `--force` (or `uv tool install --force jotline`).
Run `jotline backup` first. Uninstall with `uv tool uninstall jotline` or
`pipx uninstall jotline`; your vault remains on disk. See the
[install, update and rollback guide](docs/install.md) for checksums, pip, and
the encryption extra, and [supported platforms](docs/platforms.md) for the OS
contract.

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
2. **Log.** `Ctrl+D` opens today's page. Mix observations with Markdown tasks: `- [ ] Follow up`. Previous/next daily log and **Open daily log by date** in the palette flip days; missing days use your daily template.
3. **Connect.** Keep durable ideas in their own notes. Select a passage and run **Extract selection to new note** to leave a `[[link]]` behind. Alt+K (or Show connections) lists who links here and where this note points. Follow a `[[link]]` or create the missing note.
4. **Review.** **Process next inbox note** opens the oldest capture (daily logs stay out of that queue). File it with Move to collection; the next capture opens. **Start weekly review** is a checklist when you want one.

These are optional practices, not a compulsory system. An inbox and search are enough to start.

The sidebar offers **Collections**, **Views**, **Filters**, **Actions**, **Import**,
and **Quick start**. The optional walkthrough opens without creating a note or
replacing your writing. On narrow terminals, Ctrl+F reveals the sidebar; Escape
returns to writing. Empty lists explain how to capture, star, or move a note,
and stay short on 80×24 terminals. Ctrl+P opens everyday commands first; type
to reach format, move, export, and encryption. See [navigation and saved
views](docs/navigation.md).

The design draws on [Drafts' quick capture](https://docs.getdrafts.com/gettingstarted/), [GTD's capture and reflection](https://gettingthingsdone.com/what-is-gtd/), [Bullet Journal's daily rapid logging](https://bulletjournal.com/pages/how-to-bullet-journal), [Zettelkasten's connected ideas](https://zettelkasten.de/overview/), and [PARA's organization by use](https://fortelabs.com/blog/para/). Jotline is independent of these products and authors.

## Keyboard

| Shortcut | Action |
| --- | --- |
| `Ctrl+,` | Open Settings (always available; F1 still works) |
| `Ctrl+N` | New thought |
| `Ctrl+T` | Browse workspace tags |
| `Ctrl+W` | Switch or create workspace |
| `Ctrl+P` | Searchable command palette |
| `Ctrl+O` | Open a note by title |
| `Ctrl+D` | Today's daily log |
| `Ctrl+F` | Search across notes |
| `Ctrl+B` | Toggle quiet focus mode |
| `Alt+K` | Show incoming and outgoing connections |
| `Ctrl+S` | Save immediately |
| `Ctrl+Q` | Save and quit |
| `Tab` / `Shift+Tab` | Move between controls |
| `Escape` | Close palette / return to writing |

The palette opens on everyday capture, find, and recover commands. Type to
reach format, move, export, encryption, daily-log navigation, extract, and
inbox processing. Arrows choose; Enter runs; Esc cancels. Clipboard copy is an
OSC 52 *request* and depends on your terminal. Type **Clipboard, IME, and
screen-reader notes** for Terminal.app, Windows Terminal, and Orca limits.
Previous daily, next daily, open-by-date, extract, and process-inbox start
without shortcuts; assign them in **Ctrl+, → Keyboard shortcuts**.

## Markdown editing

The editor colours Markdown as you type. Enter continues lists. A toolbar above
the editor formats the selection; it hides in focus mode. Type **format** in
Ctrl+P for the rest, including heading levels, tables, and preview. Details:
[Markdown editing](docs/markdown.md). Omarchy desktop follow:
[Omarchy](docs/omarchy.md).

## Move or delete with the mouse

Right-click a sidebar note, or focus it and press Shift+F10, to move or trash
it. [Note list menu](docs/note-menu.md) has the full sequence.

## Make it yours

Open **Ctrl+P → Settings**. Change preferences with Tab, arrows, and Space; choose
**Save** (or Ctrl+S) to apply them. Escape cancels. **Use defaults** fills the form
with the original settings; nothing changes until you save.

- **Themes:** twenty-two built-in palettes, plus optional Omarchy desktop follow
  on Linux. See [Omarchy](docs/omarchy.md).
- **Editor:** line numbers, wrapping, current-line highlighting, Markdown
  highlighting, and list continuation on Enter.
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

Inserted links use `[[stable-id|Readable title]]`. Renaming a heading does not break these links. Manually entered `[[Exact title]]` links also work, but ambiguous titles can match several notes. **Alt+K** (or **Show connections**) lists incoming and outgoing notes with the line that contains each link. **Follow a link** opens the `[[link]]` under the cursor; a missing target can create a note and rewrite the typed title to a stable ID. Click a link in preview, or Ctrl+click one in the editor. `[[links]]` inside fenced code or code spans are examples, not connections. `jotline backlinks NOTE` prints the same graph for scripts.

## Use it from your shell

```sh
jotline capture "A thought before I forget"
printf 'Meeting notes\n\nNext step: draft the outline\n' | jotline capture
jotline capture --daily "- [ ] Send the outline"
jotline capture --daily --date yesterday "A thought from last night"
jotline daily
jotline daily --date 2026-09-14
jotline desktop install
jotline desktop recipe hyprland
jotline list '#work'
jotline stats
jotline stats --json
jotline doctor
jotline doctor --json
jotline backups
jotline recoveries
jotline sync
jotline import ~/Downloads/meeting.md
jotline export NOTE_ID > note.md
jotline export last > note.md
jotline export last --output plan.docx
jotline tasks
jotline backlinks last
jotline path
jotline --vault ~/Notes/Jotline
```

Wherever a command takes a note, you can type less than the full 32-character
ID: a unique prefix of at least four characters (`jotline append 3f9a 'Next step'`),
the note's exact title in any letter case (`jotline export 'Weekly review'`), or
`last` for the most recently updated note in the workspace. A reference that
matches several notes is refused and lists their IDs, and titles never match
notes in the trash or in another workspace. A note whose full ID is literally
`last` still wins.

Captures, append/prepend and imports read UTF-8. For text in another encoding,
pass `--encoding NAME` (for example `latin-1` or `cp1252`), or `--replace-invalid`
to keep going and substitute the undecodable bytes.

`list`, `tags`, `workspaces`, `actions`, `tasks`, `stats`, `backlinks`, `doctor`,
`backups` and `recoveries` accept `--json` for
scripts. Warnings still go to stderr, so stdout stays valid JSON. `jotline stats`
prints workspace counts (notes, inbox captures, open tasks, tags) without note bodies.

### Tasks across notes

Every Markdown checkbox line (`- [ ] Call Sam`) in any note is a task. Give it a
due date with `due:2026-09-20`, or the `📅 2026-09-20` form some other apps use.

```sh
jotline tasks                      # open tasks in this workspace, dated ones first
jotline tasks '#coaching' --due today
jotline tasks --done --json
jotline done 3f9a8c21:4            # check off the task on line 4 of that note
jotline done 3f9a8c21:4 --undo
```

Each line shows `NOTE:LINE`, the checkbox, the due date (or `-`), the task and
the note's title. Line numbers move when a note is edited, so list tasks again
before `done`; it refuses a line that is no longer a task. Tasks in the trash and
inside fenced code blocks are ignored. In the app, **Ctrl+P → Open tasks across
notes** lists open tasks and jumps to the one you pick.

### Export to HTML, Word or PDF

```sh
jotline export last --output plan.html
jotline export 'Weekly plan' --output ~/Documents/plan.docx
jotline export 3f9a --format pdf --output plan.pdf --force
```

The format comes from `--format` or the output file's extension. Without
`--output`, `export` writes Markdown (or `--format html`) to stdout as before, and
it never replaces an existing file without `--force`. Jotline builds the HTML
itself. Word files use pandoc or LibreOffice, and PDFs use Chromium, Google
Chrome, Microsoft Edge, LibreOffice or pandoc with a PDF engine, whichever is
installed. Checkboxes print as ☐/☒ and `[[links]]` as their titles. Raw HTML in a
note is shown as text and images become links, so an export never reads other
files or contacts a server. In the app, use **Ctrl+P → Export note as…**.

### Quick capture from a hotkey

`jotline capture` with no text opens a small editor: Ctrl+S saves and Esc
cancels. On Linux, install a capture launcher and bind one command:

```sh
jotline desktop install
jotline desktop launch
```

`jotline desktop recipe omarchy`, `hyprland`, `gnome`, `kde`, or `pipe` prints a
filled-in snippet for that desktop. Pipe-in stays the integration when a
launcher cannot open a terminal. See [docs/quick-capture.md](docs/quick-capture.md).

### Encrypted notes

Note files are readable only by your user account. For sensitive notes, such as
client or athlete records, you can also encrypt a note's text on disk:

```sh
uv tool install 'jotline[encryption]'  # adds the cryptography library
jotline encryption setup               # choose a passphrase
jotline encrypt 'Athlete intake'
jotline export 'Athlete intake'        # asks for the passphrase
jotline --unlock tasks                 # include tasks from encrypted notes
jotline encryption passphrase          # change the passphrase
jotline decrypt 'Athlete intake'       # store it as plain text again
```

In the app, **Ctrl+P → Encrypt this note** sets encryption up the first time, and
**Lock encrypted notes** / **Unlock encrypted notes** hide and show them. A locked
note is listed as "Encrypted note (locked)"; it cannot be searched, edited or
exported until you unlock, but it can still be moved to another collection.
Encrypted notes stay unlocked until you lock them or quit.

- **There is no recovery.** Without the passphrase, encrypted notes cannot be
  opened. Keep it in a password manager.
- The note text, including its title and tags, is sealed with AES-256-GCM. The
  key lives in `.jotline-key.json`, wrapped with your passphrase through scrypt;
  backups include that file, and changing the passphrase rewraps only it. The
  collection, workspace, star and dates stay readable in the file header.
- Encrypting a note deletes its unencrypted saved versions from note history.
  Backup ZIPs made before then (including today's automatic one) still contain
  the old text; delete those you no longer need from `.jotline-backups`.
- Scripts can set `JOTLINE_PASSPHRASE`, but anything that can read your
  environment can read it too. Otherwise commands ask on the terminal, and never
  read the passphrase from piped input.
- Older Jotline versions show encrypted notes as unreadable text; do not edit
  them there.

### Shell completion

Completion covers commands, options, note IDs, tags, workspaces and action names,
and follows any `--vault` or `--workspace` already on the line.

```sh
# bash: add to ~/.bashrc
eval "$(jotline completion bash)"
# zsh: add to ~/.zshrc after compinit
eval "$(jotline completion zsh)"
# fish: add to ~/.config/fish/config.fish
jotline completion fish | source
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
use Ctrl+, to customize it in Settings.

`jotline doctor` checks the runtime, vault path, settings, lock, templates, history,
backups, limits, recovery copies, displaced conflict files, and readable note
counts. It prints diagnostics rather than note bodies, reports unsafe or broken
local state, and exits nonzero when it finds a problem. Use `jotline doctor --json`
for machine-readable output. `jotline backups` lists local ZIP archives and
verifies they open; `jotline recoveries` lists inbox copies saved after an
external change. Search stays an in-memory scan until a measured vault misses
the bar in [vault scale](docs/vault-scale.md). `jotline import FILE` copies a regular UTF-8 file into a new note in your
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

Open **Ctrl+, → Keyboard shortcuts**. Change shortcuts for new notes,
tags, workspaces, commands, opening notes, daily logs, search, save, focus, and quit.
Optional fields also support Markdown preview and formatting, previous/next daily
log, open daily by date, extract selection, and process inbox.
Use `ctrl+letter`, `alt+letter`, or `f2`–`f12` (for example `alt+n` or `f4`).
Duplicate assignments and reserved editing/navigation keys are rejected.

Choose **Save** (or Ctrl+S inside Settings) to apply immediately; the footer and
command hints update too. **Reset hotkeys** restores shortcut defaults without
changing your other preferences; save to apply or Escape to cancel. **Ctrl+,** always
opens Settings (F1 still works), and **Escape** remains fixed for closing dialogs. Editor shortcuts
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
- Jotline coordinates its own writers and detects external edits before saving. It will block navigation/exit on a save failure so the buffer remains available. **Save recovery copy** preserves your buffer as a new inbox note. The copy keeps the original text and records which note it came from; **Open a recovery copy** and `jotline recoveries` list them later.
- Trash is reversible. There is no permanent-delete command.
- Keep a backup of your vault. Sync with [Git or Syncthing](docs/sync.md) using
  the recovery dialog you already have; there is no Jotline cloud. Encryption
  keys must not go to a public remote. Simultaneous edits through an external
  editor or sync provider are not a collaborative editing protocol.
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

Open `Ctrl+,` → **Keyboard shortcuts** to assign keys for preview, bold, italic,
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
are not rendered as browser content. Preview links do not open files or browsers.
Click a `[[note link]]` in preview to open it; use **Follow a link** from the
editor, or **Alt+K** to see every connection.

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
- **Previous daily log**, **Next daily log**, and **Open daily log by date:**
  move by calendar day. Dates are `YYYY-MM-DD`, `today`, or `yesterday`. A day
  without a log is created from your daily template.
- **Extract selection to new note:** saves the selected text as an inbox note
  and leaves a `[[id|title]]` link. Undo reverses the replacement in the source.
- **Process next inbox note:** opens the oldest inbox capture (not a daily log).
  After **Move note to** a collection, the next capture opens. The status line
  shows how many remain.
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
[community recipes](examples/actions/README.md) (`starter-recipes.json` for
copy/export, `inbox-process.json` for filing). You can also define actions
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

Version 0.9.6 is an early release. It offers a one-liner install on Linux, macOS,
and Windows, Markdown source editing, rendered preview, configurable local
actions, and guided import/recovery workflows. See
[CHANGELOG.md](CHANGELOG.md) and [ROADMAP.md](ROADMAP.md). Full Vim emulation,
cloud sync, plugins and dictation remain future work.
Automated cross-platform checks and a POSIX terminal smoke test complement the
[native terminal and accessibility checklist](docs/terminal-testing.md).
Clipboard copy is an OSC 52 request (the terminal must allow it). IME composition
and screen readers need filled [native reports](docs/terminal-reports/) for 1.0;
headless tests only prove control names and Unicode round-trip.
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
