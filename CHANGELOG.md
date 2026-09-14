# Changelog

## Unreleased

- Settings opens with Ctrl+, so it works on Mac keyboards that do not send
  F-keys without Fn. F1 still opens Settings where function keys work.
- On macOS, import and recipe files under `/tmp` or `$TMPDIR` (`/var/folders`)
  work. Those prefixes are OS compatibility links to `/private`; user-created
  aliases later in the path are still refused.
- Optional Omarchy desktop theme synchronization, including live palette,
  cursor and selection updates in the editor and quick-capture window.

- Markdown has an editor toolbar for bold, italic, headings, lists, tasks, links,
  inline code, all other formats, and preview. Mouse selections retain their
  Markdown colours on a theme-tinted background, and the cursor uses the theme
  accent. Theme changes update both immediately.
- PDF export no longer hangs or crashes on common setups. Every installed
  Chromium-based browser is tried in turn, each with its own profile. On Ubuntu
  23.10 and later, where Chromium's sandbox cannot start, a browser is retried
  without it (the page loads nothing and its CSP blocks scripts). Chrome on
  macOS no longer waits on the keychain or on helper processes after printing,
  Windows' `chrome.exe` launcher no longer counts as finished before the PDF is
  written, and a stuck browser gives up after 30 seconds instead of 180.
- On Windows, a command run with input from `NUL` (a scheduled task or script)
  is no longer mistaken for a terminal: a missing passphrase fails with the
  `JOTLINE_PASSPHRASE` hint instead of waiting forever, and `capture` reads the
  empty input instead of opening the editor.
- Markdown editing fixes from a code review. Format link keeps a multi-line
  selection on one line in CRLF notes and accepts a selected `<autolink>`.
  Insert or tidy table no longer pulls a paragraph above the table containing
  a pipe into the table, and dash-only body rows no longer truncate the table. Toggling a code block off works when the selection ends at the start
  of the closing fence. Numbered lists keep task checkboxes. Jump to heading
  keeps a `#` that is part of a title (such as `C#`), lists setext headings,
  and is one command again. Enter after a `- - -` rule no longer starts a
  list. A horizontal rule gets exactly one blank line on each side. The
  side-by-side preview follows the cursor as well as edits, waits for its
  content before scrolling, and stops rendering while the terminal is too
  small to show it. It can be switched off while compact, responds to terminal
  resizes immediately, and picks up externally renamed link titles on refresh. Highlighting rescans only the edited rows, so typing in
  large notes no longer lags. Exports, tasks and highlighting share one rule
  for fenced code, and `[[links]]` inside code spans are left alone.
- Storage fixes from the same review. A revision removed by another process
  between listing and stat no longer makes a note's history read as empty;
  permission and I/O errors still surface. Concurrent backup pruning no longer
  reports a failed daily backup when an archive disappears before stat.
  Exporting a note snapshots its text first, so typing during a slow PDF
  export cannot change what is written. A folder import skips an unreadable
  entry instead of abandoning the rest of that folder.
- Tags are highlighted with the rule the vault uses to index them, so `#123`
  now counts. Tags inside URL destinations and fragments are not highlighted.
- Moving a note now reports `Moved to X`, prefixes failures with `Note was not
  moved:`, refreshes connections, and shows any backup warning.
- Workspace mismatch errors now consistently name the `--workspace NAME` option.
  CLI export uses the same terminal-control refusal message as other commands.
- Applying an empty note selection now shows `Select at least one note first`.
- Internal cleanup with no behaviour change: the CLI dispatches commands
  through one handler per command, repeated messages and limits are named
  constants, temporary-file removal and modal cancel share one helper each,
  and dead code was removed.
- Full Markdown editing in the app. The editor highlights Markdown syntax in the
  current theme's colours, with no new dependency. Enter continues bullet,
  numbered, task and quote lines, and Enter on an empty item ends the list.
  Formatting commands now toggle off. New commands: strikethrough, heading
  levels 1–6, numbered and task lists, code blocks, links, images, horizontal
  rules, indent and outdent, and insert or tidy table. Ctrl+P → Toggle
  side-by-side Markdown preview renders while you type, and Jump to heading
  lists a note's headings. Previews show checkboxes and note-link titles as
  exports do. Every new command can take an optional shortcut, and F1 → Editor
  turns highlighting or list continuation off.
- Commands that take a note (`append`, `prepend`, `open`, `run`, `export`,
  `tag`) accept a unique ID prefix of four or more characters, an exact title
  (any letter case), or `last`. Ambiguous references are refused with the
  matching IDs. The missing-note error now reads "No note with ID or title …".
- `capture`, `append`, `prepend` and `import` accept `--encoding NAME` and
  `--replace-invalid`. Decoding errors suggest both, and folder imports report
  a bad file in plain language instead of a codec error. Undecodable bytes in
  command-line text are reported the same way.
- `tags`, `workspaces` and `actions` accept `--json`, joining `list` and `doctor`.
- `jotline completion bash|zsh|fish` prints a completion script for commands,
  options, note IDs, tags, workspaces and actions.
- `jotline tasks` lists open `- [ ]` tasks across the workspace, with optional
  due dates (`due:2026-09-20` or `📅 2026-09-20`), a search filter, `--due`,
  `--done` and `--json`. `jotline done NOTE:LINE` checks one off (`--undo`
  reopens it). In the app, Ctrl+P → Open tasks across notes jumps to a task.
- `jotline capture` with no text in a terminal opens a small capture editor
  (Ctrl+S saves, Esc cancels). [docs/quick-capture.md](docs/quick-capture.md)
  binds it to a global key on Omarchy/Hyprland, GNOME and KDE.
- `jotline export` saves HTML, Word (`.docx`) and PDF with `--format` or an
  `--output` file extension; `--force` replaces an existing file. HTML is built
  in; Word uses pandoc or LibreOffice and PDF a Chromium-based browser,
  LibreOffice or pandoc. Ctrl+P → Export note as… does the same in the app.
- Opt-in encryption for sensitive notes: `jotline encryption setup`, then
  `jotline encrypt NOTE` or Ctrl+P → Encrypt this note. Note text is sealed with
  AES-256-GCM under a passphrase-wrapped key; unencrypted saved versions of the
  note are removed, and locked notes show as "Encrypted note (locked)". Needs
  the `cryptography` package (`jotline[encryption]`). There is no passphrase
  recovery. Versions before this release show encrypted notes as unreadable text.

## 0.9.3 — 2026-09-12

- `jotline append` and `prepend` put the text on its own line. They add one
  line break in the note's newline style when the text would otherwise run into
  the note, which merged words and created false tags such as `#ideaappended`.
  Pass `--no-newline` for the previous exact join. Actions are unchanged.
- CLI errors are plain language: a missing note reads "No note with ID …", a
  missing file no longer shows `[Errno 2]`, and non-UTF-8 input names its source
  instead of printing a Python codec error.

## 0.9.2 — 2026-09-12

Fixes from the 2026-09-12 multi-agent red team (storage, CLI, parsing, UI).
See [docs/redteam-2026-09-12.md](docs/redteam-2026-09-12.md).

- Saves fall back to rename on filesystems that refuse hard links (FAT/exFAT
  media, SMB shares, shared folders). A failed publish now puts the original
  note straight back under its own name, and any warning that names a retained
  file survives sidebar refreshes.
- A daily backup that cannot be written (full disk, unsafe backup folder) no
  longer blocks note saves or recovery copies; it becomes a warning. The daily
  archive is validated once per session instead of on every save, and stale
  temporary files from interrupted writes are removed after an hour and listed
  by `jotline doctor`.
- One invalid settings value no longer resets every other preference: valid
  fields are kept, the bad field is named, and the next save preserves actions,
  views, hotkeys and unknown keys. Unreadable settings files are set aside as
  `.jotline-settings.json.invalid-*.json` rather than overwritten.
- Opening a note never rewrites it: notes with Unicode line separators, form
  feeds, lone CR or mixed newlines stay clean until you actually edit them, and
  no longer trigger false external-change dialogs.
- Task toggle, heading/list/quote formatting, find context and arrange now use
  the editor's own line model, fixing a crash on lone-CR notes and inserted
  blank lines on CRLF notes.
- Modal dialogs ignore a second dismissal (key repeat, Enter then Escape, or a
  mouse double-click), which previously ended the app or silently closed the
  action builder.
- Ctrl+Q, Ctrl+N, Ctrl+S, opening a note and switching workspace re-show the
  external-change dialog after it was dismissed; re-selecting the open note
  keeps its undo history.
- A byte-order mark added by an external editor no longer strips a note's
  collection, star, workspace and created date; folder imports of Jotline's own
  note files keep that metadata too.
- Markdown preview refuses notes with more than 600 content lines or very wide
  tables, which stalled the interface for ten seconds or more.
- Jump to heading used a quadratic regular expression; a 20 KB heading line
  took seconds and a long one minutes.
- Text search no longer matches one or two characters against random digits of
  every note ID; ID matching needs an 8-character prefix. Links and `title:`
  filters match the full first line, not only its first 100 characters.
- Terminal-safety checks accept ordinary text such as CRLF, joined emoji,
  soft hyphens and byte-order marks; `jotline run` checks exported output
  before any step applies and accepts `--raw`. Closed stdin and a closed pipe
  reader are handled quietly; `--vault ""` is rejected and a relative
  `XDG_DATA_HOME` is ignored. Shell commands wait up to ten seconds for the
  vault lock instead of one.
- Revision history orders versions by write time, so a clock step backwards
  cannot offer stale content or prune the newest version.
- A corrupt action-history file is set aside and logging resumes. One stray
  entry in the templates folder no longer hides every template. Symlinked
  ancestors are reported as such instead of "Not a directory".
- Read-only commands fail with "Vault does not exist" instead of creating an
  empty vault at a mistyped path; the preview labels unrendered HTML blocks.

## 0.9.1 — 2026-09-12

- Bound cached search results to one second before the next scan rereads them.
  External edits that preserve all tracked timestamps no longer remain cached
  indefinitely. Refresh vault still forces an immediate reread.
- Add deterministic coverage for timestamp collisions and cache expiry.

## 0.9.0 — 2026-09-12

- Added an action builder, starter recipes, result previews, action editing and
  duplication, recipe sharing, and bounded action run history.
- Added visible navigation controls, contextual empty states, and an optional
  quick-start guide that preserves the current note.
- Added saved-view editing, renaming, duplication and updates, filter controls,
  and an active-view indicator.
- Added recovery comparison with explicit preservation of the full local draft
  before reviewing an external version.
- Added folder and Drafts JSON export import with preview, metadata mapping,
  duplicate handling and partial-result summaries.
- Added versioned release packages with checksums and a cross-platform test gate,
  installation/update/uninstall instructions, and contributor templates.
- Added private vulnerability reporting, a security policy, a public roadmap,
  and a terminal/accessibility testing checklist.
- Corrected replacement failure feedback, backward selection search navigation,
  and canonical date-filter validation.
- Restored Tab/Shift+Tab navigation inside modals and removed a redundant
  Markdown preview render.

Existing notes and settings remain readable. Imports create new notes and do not
overwrite existing notes. Compact date filters must use `YYYY-MM-DD`. Local
action history is stored separately from note revision history.
Older releases do not recognize the new `quote` and `restore` recipe steps;
back up settings before downgrading, or remove those recipes using 0.9.0 first.

## 0.8.1 and earlier

The pre-release source history introduced Markdown capture, collections,
workspaces, tags, templates, history/backups, saved views, local JSON actions,
native Windows/macOS support and sidebar context menus. See the Git history and
[earlier review](docs/redteam-review.md) for the historical fixes. Version 0.9.0
is the first packaged GitHub release.
