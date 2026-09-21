# Changelog

## Unreleased

- **A search no longer hangs the app on a note that grows when it is folded.**
  ß folds to ss, so the folded body is longer than the body, and the matched-line
  code walked the folded text with body offsets. On such a note the skip position
  stopped advancing and the search spun until Jotline was killed, taking any
  unsaved editing with it. The same drift quoted the wrong line under a search
  result and put the highlights on the wrong characters. Skipping repeated
  headings is also linear now rather than quadratic: 64,000 of them took 10.7s
  and now take 0.15s.
- **A note interrupted mid-save comes back instead of disappearing.** A save
  moves the note aside and then publishes the new text under its name. Killed in
  between -- or on a filesystem that refuses both hard links and exclusive
  renames, such as sshfs or a VM shared folder -- the only copy was left under a
  hidden name that nothing listed, so the note was gone from the app with no
  warning. Opening the vault now puts it back, and `doctor` names the note a
  displaced file belongs to.
- **The outliner no longer overwrites a block you were not editing.** A
  structural edit the size guard refused stayed in the live tree, so every later
  block edit was written at a row belonging to a different block. Re-deriving the
  outline after an external change also commits the open block first, rather than
  dropping what was typed into it.
- **Encrypted notes stay encrypted.** Extract selection to new note keeps the new
  note encrypted instead of writing the selection out in the clear; Save this
  note as a template and an action's append step refuse an encrypted note and say
  why; a link to an encrypted note carries no label, because the label was its
  decrypted first line.
- **Note text can no longer drive your terminal.** The shell commands escaped
  control sequences; the app did not, so a note's title or a matched line could
  retitle the window, clear the screen, or write your clipboard through OSC 52.
  Applied to the note list, the note heading, the quoted search line and the
  import review dialog.
- **`jotline capture` is fast again for everyone who has saved a preference.**
  Reading a settings file imported the whole terminal UI to check outline
  shortcut names, which put back most of the deferred-import win: 0.10s without a
  settings file, 0.29s with one, and 0.11s now.
- A partly invalid settings file keeps the same fields every time. Which of two
  colliding fields survived depended on the hash seed, and the next ordinary save
  wrote the loser back as empty -- losing a hotkey map for good in three runs out
  of eight.
- A malformed Omarchy `colors.toml` falls back to the built-in theme instead of
  stopping Jotline with a traceback.
- Exports are created private (0600), like notes and the key file. An export of
  an encrypted note carries the same text in the clear.
- `jotline run` checks the whole output before an action commits, not the first
  20,000 characters, so a control character further into a note no longer lets an
  append apply and then repeat on every retry.
- `jotline sync git` quotes the vault path, which was wrong out of the box on the
  default macOS vault and a paste hazard on any path with shell metacharacters.
- History keeps the newest revisions when the clock steps backwards (DST, an NTP
  correction, a resumed VM snapshot); it was deleting them and keeping stale ones.
  A revision left half-written by a crash is also collected now, and removed when
  a note is encrypted -- it held the note in the clear and nothing swept it.
- Block operations no longer rewrite a tab as spaces, so a Makefile recipe line
  kept in a note survives toggling a task or editing a neighbouring block.

- Say why a note matched. A search with words in it now orders the note list by
  match quality and gives each row a third line quoting the matched text with
  the words in bold; a title hit, matching more of the query and a word near the
  top of a note all count for more. A query of only tags or dates leaves the
  order and the two-line rows alone. Still an in-memory scan with no index: at
  2,000 notes the ranking pass costs 0.02s against the published 1.00s bar.
- Match the letters you type in order in every picker, so `mtgnts` finds
  *Meeting notes*. Results are ordered best first with the matched letters
  underlined, and anything the old substring filter found is still found. The
  matcher is linear in the length of a label rather than exhaustive, because a
  label is a note title: `textual.fuzzy` takes 1.3 seconds on a five-letter
  query against a 239-character line of repeated vowels and does not finish a
  six-letter one, which in a picker is a freeze on every keystroke.
- Add **Edit this note in $EDITOR**: save, hand the note's file to the editor
  named in `$JOTLINE_EDITOR`, `$VISUAL` or `$EDITOR`, then read back whatever
  comes home. An encrypted note is never handed out; a missing file, a broken
  header or a terminal that cannot suspend is reported and leaves the draft on
  screen. Bind a key for it in Settings.
- Start `jotline capture` in about a tenth of a second instead of four tenths by
  importing Textual only where a screen is drawn. `list`, `tasks`, `backlinks`,
  `stats` and `done` never draw one and were paying for it too; capture is bound
  to a desktop hotkey, so that was the gap between the key and the thought.
- Answer the agenda question in the app. **Open tasks due today or overdue**
  narrows the task list the way `jotline tasks --due today` already did from the
  shell, **Tick off a task** checks one off without leaving the list, and a task
  due today now says so rather than reading as any other dated line.
- Fix outlining losing text typed or pasted into a block in the moment after a
  structural edit. That edit leaves the tree waiting to be re-derived from the
  note, and re-deriving it reloads the block from the note; it now commits what
  is in the block editor first, the way every other path that reads the note
  already does.
- Lint with ruff on Linux and Python 3.13 in CI, configured for defects rather
  than style. It found eight unused imports, six unused variables, an f-string
  with no placeholder, a re-raise that hid its cause and an unused loop
  variable; the two closures it flagged over a loop variable are called inside
  their own iteration and are marked as such.
- Make outlining keep up with a large note. Pressing Enter, Tab, Shift+Tab or a
  move key writes Markdown immediately and repaints from the tree it just built,
  re-deriving that tree from CommonMark once editing pauses rather than once per
  key; on a 10,000-block note those keys drop from about a second to under a
  tenth. Cache each block's derived prefix and content against its raw lines,
  key wrapped rows by text and column so re-deriving the tree no longer re-wraps
  the note, build a row's bullet gutter only when it is painted, and work out a
  new scrollbar before wrapping instead of after.
- Keep the note list out of the way of typing. The search box rebuilds the list
  once typing pauses instead of on every key, and a refresh redraws the list
  only when its rows actually changed, so an autosave that leaves every row
  reading the same no longer measures and wraps them all. Typing a query at
  500 notes drops from about 918 ms of work to 92 ms; results appear up to a
  fifth of a second after the last key rather than after every key.
- Keep typing cheap in a long note: the status line reuses its last whole-note
  word and tag scan for up to a quarter second and catches up when typing stops,
  and the Markdown editor carries its character count across edits instead of
  re-adding every line's length on each keystroke.
- Integrate the earlier publication-race hardening: when hard links are
  unavailable, use exclusive rename on Linux/macOS so saves, key setup and
  exports cannot overwrite a competing creator. Failed-save recovery keeps
  the displaced original when restoration cannot succeed safely.
- Preserve all original fences when formatting selections spanning multiple
  code blocks, compute Unicode highlight offsets in one pass, and limit the
  total number of preview table separators across the note.
- Apply CLI tags under one write lock, retain each storage warning once,
  reject duplicate capability names, and poll the desktop theme only while
  Omarchy is selected. Recipe helpers no longer look like Textual actions.
- Speed up large-outline opening and editing by reusing unchanged row identities,
  painting Rich text only for visible rows, and skipping idle serialization.
  Plain flat lists use a narrow parser shortcut; other Markdown keeps CommonMark.
  Resolve note-link aliases once per workspace snapshot and accelerate tag scans.
- Fix outline duplication, mixed line endings, folded search navigation, and
  pending edits when switching notes or leaving a focused branch. Whole-note
  actions update the complete note when run from the outliner.
- Keep encrypted-note outline preferences in memory and remove stale saved
  state when encryption is enabled. Bound malformed Markdown parsing and
  encryption key resource costs; tolerate malformed outline preferences.
- Add an inline outliner with wrapped rows, folding, branch focus, clickable
  breadcrumbs, search through folded content, bulk selection, grouping,
  duplication, move-to, and explicit outline/text paste commands.
- Parse outline structure with CommonMark source ranges. Preserve parent text
  after children; respect code fences, numbered marker widths, and tab stops.
- Share source undo and autosave, preserve block identity through transactions,
  remember per-note view positions, and offer a default outliner preference.
  Note navigation, formatting, link/snippet completion, and command shortcuts
  work inside the outliner. Every outline action has a menu alternative.
- Add optional permanent block references and read-only branch previews.
  Ordinary edits patch one block and refresh its rows with one reusable editor.
- Hide mouse-hover tooltips throughout the app and quick capture.
- Tab indents in the note editor, Shift+Tab outdents, and Enter keeps leading
  indentation. Selected lines and list items indent together. Ctrl+Tab and
  Ctrl+Shift+Tab move focus between controls.

- **Nothing Jotline starts can read your passphrase any more.** `$EDITOR`, the
  clipboard tool, the export converters and the terminal that quick capture
  opens all inherited `JOTLINE_PASSPHRASE`, where on Linux any process of yours
  could read it back out of `/proc`. `encryption change` leaked the replacement
  passphrase the same way.
- **A note still saves when its history cannot be written.** A stray file or a
  symlink where `.jotline-history` belongs used to make every save of that note
  fail, so the text went nowhere. The save goes through and Jotline says history
  is not being kept. Nothing is written through a symlink, as before.
- **A key file damaged on disk says so** instead of reporting a wrong
  passphrase. A key file from another vault still reports a wrong passphrase;
  telling those apart needs a note format change.
- **Changing your passphrase now strengthens the key file.** It was rewrapped at
  whatever work factor the file already carried, so a vault set up weak stayed
  weak.
- **An encrypted note that will not open stays in the list**, sealed, instead of
  disappearing as though deleted.
- **Encrypting a note no longer puts its plaintext in the day's backup.** The
  daily ZIP runs before the sealed file is published and archived the note as it
  was on disk. Backups made earlier in the day still hold the old text, as the
  README says.
- **An imported file cannot pass its first lines off as metadata.** A file
  starting with something that looked like a Jotline header could file itself
  into a collection, star and backdate itself, and hide those lines from the
  preview. A header counts only where Jotline would read that file as a note,
  and the preview says when an item's collection came from one.
- **Importing a folder that is itself a vault no longer pulls in its history**,
  which brought every old draft in as its own note.
- **Indent and outdent keep a tab that is content.** A Makefile recipe inside a
  fenced code block survives moving the item, and indent followed by outdent
  gives back the line you started with.
- **Quarantined backups are pruned and listed.** `.invalid-*.zip` files built up
  without limit and appeared nowhere; `doctor` names them.
- **A malformed backup cannot exhaust memory during validation**: a 199 KB
  archive could cost 400 MiB, now 18 MiB.
- **Smaller shell fixes**: an unknown `--encoding` value is escaped before it
  reaches the terminal, `import --apply` exits 0 on warnings that need nothing
  from you, and a vault path containing `%` produces a working desktop entry.

## 0.9.8 — 2026-09-18

- Copy uses `pbcopy` on macOS and `wl-copy` / `xclip` / `xsel` on Linux when
  those tools exist, then confirms. OSC 52 remains a fallback request for
  terminals that honor it. Terminal.app blocks OSC 52; macOS copy no longer
  depends on it.
- `scripts/install.py` asks GitHub's release JSON API for
  `application/vnd.github+json`. Sending `application/octet-stream` for that
  metadata returned HTTP 415, so the documented one-liner could not install
  from a tagged GitHub Release. Wheel and `SHA256SUMS` downloads still use
  `application/octet-stream`.
- README install leads with `uv tool install jotline`. A filled macOS 27
  Terminal.app report is in `docs/terminal-reports/macos-27-terminal.md`.
  VoiceOver was not on; issue #3 stays open.

## 0.9.7 — 2026-09-17

- Windows is out of scope. The product, CI matrix, PyPI classifiers, and
  install path are Linux and macOS. `jotline` and `scripts/install.py` exit
  with a short message on Windows. The PowerShell installer is gone. Native
  Windows Terminal reports are no longer a 1.0 requirement.
- Synthetic vault benchmarks (`scripts/vault_bench.py`, `docs/vault-scale.md`)
  time search and backlinks. They stay under the published bar, so search is
  still an in-memory scan — no index. `jotline doctor` now reports recovery
  copies, displaced conflict files, backup freshness, and scan budget, and
  warns when notes exist without a recent valid ZIP. `jotline backups` lists
  and verifies archives; `jotline recoveries` lists inbox copies saved after
  an external change. Those copies keep the original draft and store
  `recovery_of` in the note header. Commands → Check vault health and Open a
  recovery copy expose the same recovery tools in the app.
- The command palette opens on everyday capture, find, and recover commands.
  Type to reach format, move, export, and encryption. Empty inbox, trash,
  starred, and PARA lists say what to do next, and stay short on 80×24
  terminals. Markdown, Omarchy, and the note-list menu moved out of the README
  into `docs/markdown.md`, `docs/omarchy.md`, and `docs/note-menu.md`. There is
  still no second Vim editor.
- Accessibility is a ship criterion, not a help-wanted afterthought. Interactive
  controls on the writing screen, Settings, views, find, recovery, capture, the
  action builder, history, arrange, and bulk select now carry labels or tooltips.
  Copy wording is an OSC 52 *request*, never a success claim. `Ctrl+P → Clipboard,
  IME, and screen-reader notes` explains the limits. Native VoiceOver and
  Orca reports remain required for 1.0; fill the templates in
  `docs/terminal-reports/`. Headless Linux coverage is recorded there and does
  not close issues #2 or #3.
- Documented Git and Syncthing recipes for the vault folder. `jotline sync`
  and **How to sync this vault with Git or Syncthing** print the path, ignore
  rules, and the existing recovery dialog. There is no Jotline cloud.
- Grew `examples/actions` from real capture and inbox workflows: copy/export
  recipes that keep the source, plus filing recipes that append and archive.
  Still no plugin SDK, shell steps, or network actions.

## 0.9.6 — 2026-09-15

- The `v0.9.5` tag never uploaded GitHub Release assets or PyPI files.
  Hatchling now emits Metadata-Version 2.5; the release job still ran
  `twine==6.1.0`, which rejects that version. The check now uses Twine 7.
  The rest of 0.9.5 is unchanged.

## 0.9.5 — 2026-09-15

- Daily logs can move through days: Previous daily log, Next daily log, and Open
  daily log by date (`YYYY-MM-DD`, `today`, or `yesterday`) in the command
  palette. Missing days use the daily template, as today already did. Optional
  shortcuts start unassigned. `jotline daily` opens today's log in the app;
  `jotline daily --date yesterday` opens another day. `jotline capture --daily --date`
  appends to that log.
- **Extract selection to new note** saves the selection as an inbox note and
  replaces it with a `[[id|title]]` link, as one undo step.
- **Process next inbox note** opens the oldest inbox capture (daily logs are
  skipped). Filing that note with Move to collection opens the next. The status
  line shows how many captures remain. `jotline stats` (and `--json`) prints
  workspace counts without note bodies.
- Connections are a first-class loop: Alt+K (or Ctrl+P → Show connections)
  lists incoming and outgoing notes with the line that contains each link.
  Follow opens the `[[link]]` under the cursor; a missing target can create a
  note and rewrite the typed `[[title]]` to a stable `[[id|title]]`. Click a
  link in preview, or Ctrl+click one in the editor. Compact terminals keep
  `←N →N` on the status line when the connections bar is hidden.
  `jotline backlinks NOTE [--json]` prints the same graph. Wiki links inside
  fenced code or inline code spans no longer count as connections. Typing `[[`
  to complete a note link no longer offers the note you are already in.
- Linux desktop capture is a shipped feature: `jotline desktop install` writes
  an XDG `jotline capture` desktop entry, `jotline desktop launch` opens the
  capture editor in a terminal, and `jotline desktop recipe` prints Omarchy,
  Hyprland, GNOME, KDE, and clipboard-pipe snippets with this install's
  `jotline` path. No dictation, share sheet, or cloud. Windows and macOS keep
  `jotline capture` and pipe-in.
- Install no longer requires hunting a wheel filename. A tagged GitHub Release
  attaches the wheel, source archive, `SHA256SUMS`, `install.py`, and
  `install.ps1`. Linux and macOS use
  `curl …/install.py | python3`; Windows PowerShell uses
  `irm …/install.ps1 | iex`. The installer verifies SHA-256 before installing
  with uv, pipx, or pip.
- `uv tool install jotline` / `pipx install jotline` are the PyPI commands. The
  tag workflow publishes to PyPI with Trusted Publishing after the GitHub
  assets exist. Linux, macOS, and Windows remain the supported-OS contract;
  Windows is not dropped to make a tag publishable.
- CI installs the built wheel through `scripts/install.py` on Linux, macOS, and
  Windows before a tag can publish.

## 0.9.4 — 2026-09-15

- GitHub Release assets for the `v0.9.3` tag were never uploaded: Windows
  Python 3.11 failed `test_builder_keyboard_only_preview_close_save` on a 60×20
  terminal because Preview sat one row below the screen. The action builder now
  pins Preview, Save, and Cancel below the form, matching Settings.
- The test job allows eight minutes for pytest. A slow PDF converter on
  Ubuntu/Python 3.12 previously finished the suite in 299s and still failed the
  five-minute step timeout.
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
- Tagged as `v0.9.3`; the release workflow did not publish wheels. Install 0.9.4.

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
