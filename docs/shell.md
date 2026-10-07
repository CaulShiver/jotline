# Jotline from the shell

`jotline` with no command opens the app. Every other command works on the same
vault from your shell and scripts. `jotline --help` groups the commands by task
with examples, and `jotline COMMAND --help` shows one command's options.

## Commands

| Task | Commands |
| --- | --- |
| Capture | `capture`, `append`, `prepend`, `daily` |
| Find | `list` (or `search`), `open`, `backlinks`, `tags`, `workspaces` |
| Tasks | `tasks`, `done` |
| Notes | `tag`, `actions`, `run`, and `encrypt` / `decrypt` when encryption is available |
| Export and import | `export`, `import` |
| Vault care | `backup`, `backups`, `recoveries`, `doctor`, `stats`, and `encryption` when a key or the extra is present |
| Setup | `path`, `completion`, `desktop` |

`encrypt`, `decrypt` and `encryption` stay off this list until the
`jotline[encryption]` extra is installed or the default vault has a key file.
The commands still run when you type them. Jotline does not sync; `jotline doctor`
points at [Git or Syncthing](sync.md).

```sh
jotline capture "A thought before I forget"
printf 'Meeting notes\n\nNext step: draft the outline\n' | jotline capture
jotline capture --daily "- [ ] Send the outline"
jotline capture --daily --date yesterday "A thought from last night"
jotline daily
jotline daily --date 2026-09-14
jotline append NOTE_ID 'Next step'
printf 'Introduction' | jotline prepend NOTE_ID
jotline list '#work'
jotline search 'tag:work -blocked' --json
jotline open milk
jotline backlinks last
jotline tag NOTE_ID ideas project/topic
jotline tasks
jotline done 3f9a8c21:4
jotline export last --output plan.html
jotline import ~/Downloads/meeting.md
jotline actions
jotline run ACTION_NAME NOTE_ID > output.md
jotline stats
jotline doctor
jotline backup
jotline backups
jotline recoveries
jotline path
jotline desktop install
```

## Global options

| Option | Effect |
| --- | --- |
| `--vault PATH` | Use this vault folder instead of the default |
| `--workspace NAME` | Use this workspace instead of the last one selected in the app |
| `--new-workspace` | Let `--workspace` name a workspace that does not exist yet |
| `--unlock` | Ask for the encryption passphrase first so encrypted notes are included |
| `--version` | Print the version |

Global options work before or after the command, so `jotline --vault X list`
and `jotline list --vault X` are the same. When both are given, the value after
the command wins.

A `--workspace` that names no existing workspace is refused rather than quietly
starting a new one. Read commands report `No workspace named X`; captures,
imports and other writes ask you to add `--new-workspace` to create it.
Workspaces created in the app, and `default`, always count. `actions`, `backup`,
`backups`, `doctor` and `encryption` cover the whole vault and do not check the
name. A desktop capture launcher bound to a workspace adds `--new-workspace` for
you, so its first capture can create it.

```sh
jotline workspaces
jotline --workspace work                       # open the app in that workspace
jotline --workspace work capture 'Meeting #team'
jotline capture --workspace work --daily 'Today’s progress'
jotline --workspace research --new-workspace capture 'First note here'
jotline list '#team' --workspace work
```

## Naming a note

Wherever a command takes a note, you can type less than the full 32-character
ID:

- a unique prefix of at least four characters (`jotline append 3f9a 'Next step'`),
- the note's exact title in any letter case (`jotline export 'Weekly review'`),
  including a title written with Markdown markers, such as `- [ ] buy milk`,
- or `last` for the most recently updated note in the workspace.

A reference that matches several notes is refused and lists their IDs. Titles
never match notes in the trash or in another workspace. A note whose full ID is
literally `last` still wins.

`open` goes one step further. When no exact title or ID matches, `jotline open
milk` opens the one note whose title clearly matches best, or lists the top
five with short IDs on stderr so you can pick one.

## Capture

`jotline capture TEXT` saves a new note in your default collection;
`--daily` appends to today's log instead, and `--date` picks another day
(`YYYY-MM-DD`, `today` or `yesterday`). With no text, piped stdin is read. At a
terminal with nothing piped, a small editor opens: see
[quick capture](quick-capture.md).

At a terminal, capture confirms in words: `Saved to inbox: <title> (<short id>)`
or `Added to daily log <date>`. Piped or redirected, it prints only the note ID,
for scripts.

`append` and `prepend` put the text on its own line: when it would otherwise run
into the note, they add one line break in the note's newline style. Pass
`--no-newline` to join the text exactly as supplied.

Captures, `append`/`prepend` and imports read UTF-8. For text in another
encoding, pass `--encoding NAME` (for example `latin-1` or `cp1252`), or
`--replace-invalid` to keep going and substitute the undecodable bytes.

`daily` and `open` open the app on that note; `open` takes precedence over the
startup-page preference. Every update uses the normal locking, history and
conflict detection.

## Find

`jotline list QUERY` (or `jotline search QUERY`) prints ID, collection and title
for each matching note. The query uses the same syntax as the app's search:
words, `#tags`, `"exact phrases"`, `-excluded`, `tag:work`, `title:"..."` and
date operators. See [search syntax](navigation.md#search-syntax).

`backlinks NOTE` prints the notes that link to a note and the notes it links to.
`tags` lists tags and counts in the workspace, `workspaces` lists workspaces.

## Tasks

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
inside fenced code blocks are ignored. Tasks in locked encrypted notes are left
out with a warning; pass `--unlock` to include them.

## Export

```sh
jotline export NOTE_ID > note.md
jotline export last --output plan.html
jotline export 'Weekly plan' --output ~/Documents/plan.docx
jotline export 3f9a --format pdf --output plan.pdf --force
```

The format comes from `--format` or the output file's extension. Without
`--output`, `export` writes Markdown (or `--format html`) to stdout, and it
never replaces an existing file without `--force`. Jotline builds the HTML
itself. Word files use pandoc or LibreOffice, and PDFs use Chromium, Google
Chrome, Microsoft Edge, LibreOffice or pandoc with a PDF engine, whichever is
installed. If no converter is installed, or LibreOffice is installed but cannot
convert, the error says so and suggests exporting HTML instead. Checkboxes print
as ☐/☒ and `[[links]]` as their titles. Raw HTML in a note is shown as text and
images become links, so an export never reads other files or contacts a server.

Redirected export preserves the note body, including line endings. Export and
`run` to an interactive terminal refuse control characters (escape sequences,
bidirectional overrides) unless you pass `--raw`; ordinary text such as CRLF
endings, joined emoji and soft hyphens prints normally.

## Import

`jotline import FILE` copies a regular UTF-8 file into a new note in your
default collection; the original is left untouched. Folders and Drafts
`.draftsExport` libraries preview first:

```sh
jotline import ~/Downloads/notes --recursive          # preview
jotline import ~/Downloads/notes --recursive --apply  # import
jotline import ~/Downloads/library.draftsExport       # preview
jotline import ~/Downloads/library.draftsExport --apply
```

Preview prints one tab-separated row per source. `--preview` reviews a single
file first, and `--duplicates copy` creates separate copies instead of skipping
matches. To move notes between Jotline vaults, add `--jotline-notes` so each note
keeps its collection, star and dates; without it a Jotline header stays in the
note as text. A single file with that flag is imported at once. A folder still
needs `--apply`. See [import and recovery](import-recovery.md) for limits, exit
status and the Drafts field mapping.

## Actions

`jotline actions` lists saved local actions and `jotline run ACTION NOTE` runs
one on a note, writing any export step to stdout. Recipes run only built-in
steps; there is no shell evaluation. See [local actions](actions.md).

## Vault care

`doctor` checks the runtime, vault path, settings, lock, templates, history,
backups, limits, recovery copies, displaced conflict files and readable note
counts. It prints diagnostics rather than note bodies and exits nonzero when it
finds a problem. It warns when the vault folder is not writable. `backup`
writes a ZIP now, `backups` lists the archives and checks they open (quarantined
daily archives print as `quarantined`), and `recoveries` lists inbox copies
saved after an external change. `stats` prints workspace counts (notes, inbox
captures, open tasks, tags) without note bodies. See
[your vault](vault.md#history-and-backups).

## Scripts and empty results

`list`, `tags`, `workspaces`, `actions`, `tasks`, `stats`, `backlinks`,
`doctor`, `backups` and `recoveries` accept `--json`. Warnings go to stderr, so
stdout stays valid JSON. `list --json` returns metadata and tags, not note
bodies.

When there is nothing to print, `list`, `tasks`, `tags` and `actions` explain
why on stderr, and only at a terminal; scripts see the same empty output as
before. `jotline run` with no actions set up points at
[docs/actions.md](actions.md).

On a new install, before the first capture, the read commands `list`, `tasks`,
`stats`, `tags`, `workspaces`, `recoveries` and `backups` print an empty result
and exit 0, and create nothing. `doctor` says where the vault will be created.
A `--vault` that points at a file is refused with a message saying so.

## Environment variables

| Variable | Effect |
| --- | --- |
| `JOTLINE_VAULT` | Default vault folder; `--vault` still overrides it ([vault location](vault.md#where-notes-live)) |
| `XDG_DATA_HOME` | Base for the default vault on Linux, and on macOS when set explicitly |
| `JOTLINE_PASSPHRASE` | Encryption passphrase for scripts; a wrong one only fails commands that need it, others warn and leave encrypted notes locked |
| `JOTLINE_EDITOR`, `VISUAL`, `EDITOR` | Editor for **Edit this note in $EDITOR**, checked in that order |
| `JOTLINE_TERMINAL` | Terminal that `jotline desktop launch` opens capture in ([quick capture](quick-capture.md#choosing-the-terminal)) |

## Shell completion

Completion covers commands, options, note IDs, tags, workspaces and action
names, and follows any `--vault` or `--workspace` already on the line.

```sh
# bash: add to ~/.bashrc
eval "$(jotline completion bash)"
# zsh: add to ~/.zshrc after compinit
eval "$(jotline completion zsh)"
# fish: add to ~/.config/fish/config.fish
jotline completion fish | source
```
