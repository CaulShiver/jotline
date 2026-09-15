"""Blessed Git and Syncthing recipes. Jotline never hosts a sync service."""
from __future__ import annotations

from pathlib import Path

from .cli_io import terminal_text
from .crypto import KEY_FILE

GITIGNORE = f"""\
.jotline.lock
.jotline-displaced-*
"""

RECOVERY_KEEP_BOTH = "Save copy, then review external version"
RECOVERY_OPEN_COPY = "Save and open recovery copy"
RECOVERY_KEEP_EDITING = "Keep editing"


def vault_display(path: Path) -> str:
    return terminal_text(Path(path).expanduser().resolve())


def git_recipe(vault: Path) -> str:
    shown = vault_display(vault)
    return f"""\
## Git

Use Git when you want history you can clone. Jotline does not run Git for you.

1. `jotline backup` (or Ctrl+P → Back up vault now).
2. `cd {shown}`
3. Create a `.gitignore` with:

{GITIGNORE.rstrip()}
   Ignore `{KEY_FILE}` on any remote you do not fully control. Encrypted notes
   are unreadable without that file; a public Git host is not a safe place for it.
4. `git init && git add -A && git commit -m "Vault"`
5. Add a remote you already trust. Pull before you start a writing session
   (`git pull --rebase` or `git pull`), then write in Jotline.
6. After you quit Jotline (`Ctrl+Q`), `git add -A && git commit` and push.

If a pull rewrites a note you still have open, Jotline treats that as an
external edit. The comparison dialog keeps both copies:

- **{RECOVERY_KEEP_BOTH}** saves your full draft as an inbox recovery note,
  then loads the synced file.
- **{RECOVERY_OPEN_COPY}** opens the recovery note instead.
- **{RECOVERY_KEEP_EDITING}** (Esc) leaves the on-screen draft unsaved.

Then run `jotline doctor`. History lives in `.jotline-history/`; include it if
you want revisions on every machine, or omit it to keep clones smaller.
"""


def syncthing_recipe(vault: Path) -> str:
    shown = vault_display(vault)
    return f"""\
## Syncthing

Use Syncthing when you want folder sync without Git. Jotline does not talk to
Syncthing.

1. `jotline backup`.
2. Share `{shown}` as a Syncthing folder on each machine. Native Windows,
   macOS, and Linux are all supported; WSL is optional.
3. Ignore `.jotline.lock` (and `.jotline-displaced-*` if your version of
   Syncthing can ignore globs). Never share `{KEY_FILE}` to a peer you do not
   trust with every encrypted note.
4. Quit Jotline on a machine (`Ctrl+Q`) before you expect a large inbound
   sync. Two open editors plus a sync tool is not collaborative editing.
5. After Syncthing replaces a file while Jotline still has unsaved text, the
   same comparison dialog as Git keeps both versions ({RECOVERY_KEEP_BOTH},
   {RECOVERY_OPEN_COPY}, or {RECOVERY_KEEP_EDITING}).
6. `jotline doctor` after a messy sync. `jotline backup` before you delete a
   peer's copy.
"""


def sync_guide(vault: Path, tool: str | None = None) -> str:
    shown = vault_display(vault)
    header = f"""\
Sync this vault with Git or Syncthing — not a Jotline cloud.

Vault: {shown}
Print this path any time with `jotline path`. There is no Jotline account,
hosted backend, or vendor sync. Your folder tools move files; Jotline's job
is not eating notes: atomic saves, conflict copies, history, daily backups,
and `jotline doctor`.

When another machine (or `git pull`, or Syncthing) changes a note you are
still editing, use **Review external change and recover draft** if the dialog
is not already open.
"""
    if tool == "git":
        return header + "\n" + git_recipe(vault)
    if tool == "syncthing":
        return header + "\n" + syncthing_recipe(vault)
    return header + "\n" + git_recipe(vault) + "\n" + syncthing_recipe(vault)
