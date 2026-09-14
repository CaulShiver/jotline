# Importing and recovering notes

## Import a library

In Commands, choose **Import notes from file, folder or Drafts export** and enter a Markdown/text file, a folder,
or a `.draftsExport` path. Folder imports include subfolders. Review the list and
warnings, then choose **Import**. Cancel leaves the vault unchanged. Import creates
new notes; it never modifies source files or overwrites existing notes.

The command line provides the same preview:

```sh
jotline import ~/Documents/notes --recursive
jotline import ~/Documents/notes --recursive --apply
jotline --workspace work import ~/Downloads/backup.draftsExport
jotline --workspace work import ~/Downloads/backup.draftsExport --apply
```

Folder and Drafts imports default to preview. A single Markdown/text file retains
its previous immediate-import behavior; add `--preview` to review it first.
`--duplicates skip` is the default for batch import: matching text in the destination
workspace or matching Drafts UUIDs are skipped. `--duplicates copy` creates new,
independent IDs instead. There is no overwrite mode. The apply step checks again
for duplicates introduced since preview. The app applies the exact previewed
content even if the source changes while the dialog is open; CLI invocations read
the source afresh each time.

Drafts mapping:

| Export field | Jotline result |
| --- | --- |
| `content` | Note body |
| `uuid` | Stable `drafts-…` note ID for duplicate detection |
| `folder` | Inbox (0), archive (1), trash (2) |
| `flagged` | Starred |
| `created_at`, `modified_at` | Original creation and modification timestamps |
| `tags` | Inline hashtags; tags outside Jotline's grammar remain in a visible “Drafts tags” line |
| Workspace | Destination selected in Jotline or `--workspace` |

The importer accepts Drafts' JSON list of draft objects. Location, syntax, action
history, and version history do not map to Jotline. Preserve your original export.
The format follows [Drafts backup documentation](https://docs.getdrafts.com/docs/settings/backups)
and the [export example supplied by Drafts' developer](https://forums.getdrafts.com/t/how-to-preserve-create-time-and-modification-time-while-importing/6782).

Imports are bounded to 1,000 scanned directory entries, 1,000 records, and 32 MiB
of source content per preview. Individual notes must fit the normal note limit
including mapped metadata. Folder imports recognize `.md`, `.txt`, and
`.draftsExport`. Symlinks are not followed. Invalid
records are reported separately so valid notes can still be imported. The final
summary reports imported, skipped, and failed counts; failures do not undo earlier
successful imports. CLI `--apply` exits nonzero when warnings or failures require
review. Retry with the default skip policy to avoid duplicating successful notes.

## Recover after an external edit

The conflict dialog displays your unsaved on-screen text and the external version.
The comparison shows up to 100,000 characters per version; saving preserves the
complete on-screen draft.

- **Save copy, then review external version** saves your full draft as a separate
  inbox note before loading the latest external version.
- **Save and open recovery copy** saves a separate inbox note and opens that copy.
- **Keep editing** (Escape) retains the unsaved buffer without changing either file.

If saving the recovery copy fails, the editor keeps your unsaved text. If the
external file disappears or moves to another workspace, Jotline opens the saved
recovery copy and explains what happened. The success notification identifies the
recovery note. **Review external change and recover draft** reopens the comparison after dismissal.
