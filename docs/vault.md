# Your vault

A vault is one folder of plain Markdown files. Jotline has no account,
telemetry, hosted backend or database, and needs no network at runtime. Only
the source code is published to GitHub; your notes stay on your computer.

## Where notes live

| Platform | Default vault |
| --- | --- |
| Linux | `$XDG_DATA_HOME/jotline/notes`, normally `~/.local/share/jotline/notes` |
| macOS | `~/Library/Application Support/jotline/notes` |

On macOS, an explicitly set `XDG_DATA_HOME` or an existing vault at the old
`~/.local/share/jotline/notes` location continues to be used.

`jotline path` prints the active location. To use another folder, set
`JOTLINE_VAULT` (for example `export JOTLINE_VAULT="$HOME/Notes"`) or pass
`--vault "path/to/notes"` to any command. The folder is created on the first
capture or launch; read commands never create it.

## What is in the folder

| Path | Contents |
| --- | --- |
| `<id>.md` | One note each: small Jotline front matter, then your Markdown |
| `.jotline-settings.json` | Preferences, hotkeys, saved views, action recipes, known workspaces |
| `.jotline-templates/` | Your saved templates |
| `.jotline-history/` | Saved revisions of each note |
| `.jotline-backups/` | Daily and on-demand ZIP backups |
| `.jotline-key.json` | The encryption key, wrapped with your passphrase (only after setup) |
| `.jotline-outline.json` | Outliner folds and positions for unencrypted notes |
| `.jotline-action-history.json` | The last 100 action runs, without note bodies |
| `.jotline.lock` | Held while Jotline writes |
| `.jotline-displaced-*` | Leftovers from a failed save; `jotline doctor` reports them |

The front matter holds JSON-valued fields for collection, workspace, timestamps
and starred state. Note files are readable only by your user account.

Workspaces are organization, not access control: all notes stay directly in the
vault folder, with workspace membership recorded in their front matter. Moving a
note between workspaces keeps its filename and contents. Versions of Jotline
from before workspaces do not preserve that field, so do not edit workspace
notes with them.

## Your data

- Saves are atomic and fsynced. A normal exit saves pending edits; abrupt
  termination can lose the last autosave interval (0.7 seconds by default,
  configurable).
- Jotline coordinates its own writers and detects external edits before saving.
  A save failure blocks navigation and exit so the buffer stays available, and
  **Save recovery copy** keeps your buffer as a new inbox note that records which
  note it came from. **Open a recovery copy** and `jotline recoveries` list them.
- Trash is reversible. There is no permanent-delete command.
- Keep a backup of your vault. Sync it with [Git or Syncthing](sync.md); there
  is no Jotline cloud. Encryption keys must not go to a public remote.
  Simultaneous edits through an external editor or a sync provider are not a
  collaborative editing protocol.

## Save conflicts

When a note changed on disk while you had unsaved text, a comparison dialog
offers **Save copy, then review external version**, **Save and open recovery
copy**, or **Keep editing**. Both save options keep your full local draft before
changing what is open. If recovery fails, the unsaved editor text stays. Use
**Review external change and recover draft** in the palette to reopen the
dialog. Large comparisons show excerpts but keep the complete draft. Details:
[importing and recovering](import-recovery.md#recover-after-an-external-edit).

## Filesystem requirements

Use a local filesystem with hard-link support, such as APFS or ext4. When hard
links are unavailable, Jotline tries an atomic exclusive rename. If neither is
supported, it refuses to publish the save and reports where any displaced
original was kept, rather than replace another writer's file. File contents are
flushed before publication. Unix permission warnings apply on Linux and macOS.

## Limits

Notes are limited to 10 MiB including metadata, and settings to 256 KiB. A paste
that takes a note over the limit is warned about at once, with the note's size
and how far over it is. Symbolic links and special files are skipped and
reported. A busy vault lock returns an error after about one second so the app
can recover instead of hanging. `jotline doctor` warns when the vault folder is
not writable, since capture and saves need write permission even when reading
still works.

## Files from elsewhere

You can place Markdown files directly in the vault when their filenames use
letters, numbers, underscores or hyphens. Front matter that is not Jotline's
stays part of the body. Subfolders and attachment management are not supported.

An in-memory cache avoids reparsing unchanged notes. Each scan still checks file
metadata, cached content expires after one second, and **Refresh vault** clears
the cache at once and picks up shell captures and external changes while keeping
the current editor buffer. Search stays an in-memory scan with no index until a
measured vault misses the bar in [vault scale](vault-scale.md).

## History and backups

Jotline saves note revisions in `.jotline-history/`. It keeps the first saved
version from each of the latest 30 minutes with edits, plus the two latest saves
(up to 32 versions per note); autosaves within a minute are consolidated. It
cannot recover edits made before history was enabled.

**Ctrl+P → History of this note** lists versions; inspect one and choose
**Restore as new note**, which creates a separate inbox note and keeps your
current writing. **Browse saved note history** also finds history for notes
deleted outside Jotline, within the active workspace.

A ZIP backup is made before the first changed note save each day. It holds the
vault's current Markdown notes, settings and custom templates, plus a manifest of
any unreadable or unsafe files that were skipped; it leaves out history and other
backups. **Ctrl+P → Back up vault now** or `jotline backup` makes one
immediately. The latest seven archives stay in `.jotline-backups/`, including
today's automatic one. `jotline backups` lists them and checks they open.

For whole-vault recovery, extract a ZIP into a separate folder and run
`jotline --vault /path/to/recovered-folder`. Backups stay on this computer; copy
an archive elsewhere to protect against disk loss.

## Encrypted notes

For sensitive notes, such as client or athlete records, you can also encrypt a
note's text on disk:

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
  environment can read it too. A wrong value only fails commands that need the
  key; others warn and leave encrypted notes locked. Otherwise commands ask on
  the terminal, and never read the passphrase from piped input.
- Encrypted notes stay in Jotline: **Edit this note in $EDITOR** does not hand
  them out, undo history is not kept for them across note switches, and the
  outliner keeps their view state only while they are open.
- Older Jotline versions show encrypted notes as unreadable text; do not edit
  them there.

## Import and export safety

Imports copy into new notes and never modify source files or overwrite existing
notes. They refuse symlinked files and symlinked source folders, and are bounded
in size and count. See [importing and recovering](import-recovery.md).

Exports build HTML themselves, print raw HTML as text and turn images into
links, so an export never reads other files or contacts a server. Output to an
interactive terminal refuses control characters unless you pass `--raw`, and
diagnostics escape them. See [export](shell.md#export).
