# Sync this vault (Git or Syncthing)

Jotline does not host a cloud. There is no Jotline cloud. Notes are ordinary files in the vault folder
(`jotline path`). Use **your** Git remote or Syncthing folder. Jotline's job is
the recovery UI you already have: conflict comparison, recovery copies, history,
ZIP backups, and `jotline doctor`.

Print the recipe with the vault path filled in:

```sh
jotline sync
jotline sync git
jotline sync syncthing
```

In the app: **Ctrl+P → How to sync this vault with Git or Syncthing**.

## Before you sync

1. `jotline backup` (or **Back up vault now**).
2. Prefer one writer at a time. Quit with `Ctrl+Q` so the last autosave is on
   disk before a large inbound sync.
3. Do not put `.jotline-key.json` on a public Git host or an untrusted Syncthing
   peer. Encrypted notes are sealed without it.

Suggested ignore rules (lock files and displaced leftovers from a crash):

```
.jotline.lock
.jotline-displaced-*
```

`.jotline-settings.json`, `.jotline-templates/`, and your `.md` notes should
sync. `.jotline-history/` is optional (revisions on every machine vs smaller
clones). `.jotline-backups/` ZIP archives are optional; they are already
local snapshots.

## Git

```sh
cd "$(jotline path)"
# add the ignore rules above
git init
git add -A
git commit -m "Vault"
# add a remote you already trust
git pull --rebase   # before a writing session
# quit Jotline, then:
git add -A && git commit && git push
```

Linux and macOS run Git natively. Windows is out of scope.

## Syncthing

Share the folder `jotline path` prints. Ignore `.jotline.lock`. Linux and macOS
peers can share the same vault. After Syncthing
replaces a file while Jotline still has unsaved text, use the comparison dialog
below — not a second copy of the whole vault.

## When sync changes a note you still have open

Jotline treats the inbound file as an external edit. The comparison dialog
shows your unsaved on-screen draft and the version on disk.

| Choice | Result |
| --- | --- |
| **Save copy, then review external version** | Inbox recovery copy of your full draft, then the synced file is loaded |
| **Save and open recovery copy** | Inbox recovery copy, then that copy is opened |
| **Keep editing** (Esc) | Unsaved buffer stays; the file on disk is unchanged by Jotline |

If the dialog was dismissed, **Review external change and recover draft**
reopens it. Saving a recovery copy never overwrites the synced file. If
recovery fails, the editor keeps your unsaved text.

Then run `jotline doctor`. See [importing and recovering](import-recovery.md)
for the same dialog after a local external editor.

