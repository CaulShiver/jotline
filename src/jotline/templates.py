"""Reusable local Markdown templates with literal placeholder substitution."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime
from pathlib import Path
import re
import stat

from .filesystem import create_private_temp, fs as os, read_regular_at, vault_lock
from .limits import MAX_NOTE_BYTES
from .store import validate_workspace

BUILTIN_TEMPLATES = {
    "meeting": "# Meeting — {{date}}\n\n## Attendees\n\n## Agenda\n\n- \n\n## Notes\n\n## Actions\n\n- [ ] \n",
    "project": "# Project\n\nWorkspace: {{workspace}}\nStarted: {{date}}\n\n## Outcome\n\n## Next actions\n\n- [ ] \n\n## References\n",
    "journal": "# {{date}}\n\n## What's on my mind\n\n## Today’s priorities\n\n- [ ] \n\n## Reflection\n",
}
MAX_TEMPLATE_ENTRIES = 2048


def _name(name: str) -> str:
    try:
        return validate_workspace(name)
    except ValueError:
        raise ValueError("Template names need 1–48 lowercase letters, numbers, hyphens or underscores") from None


class Templates:
    def __init__(self, vault_path: Path):
        self.vault_path = Path(vault_path).expanduser().resolve()
        self.path = self.vault_path / ".jotline-templates"

    @contextmanager
    def _directory(self, create: bool = False, vault_directory: int | None = None):
        """Pin the directory so replacement cannot redirect file operations."""
        with ExitStack() as handles:
            if vault_directory is None:
                vault_directory = os.open(self.vault_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                handles.callback(os.close, vault_directory)
            if create:
                try:
                    os.mkdir(self.path.name, mode=0o700, dir_fd=vault_directory)
                except FileExistsError:
                    pass
            try:
                fd = os.open(self.path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=vault_directory)
            except FileNotFoundError:
                if create:
                    raise
                fd = None
            if fd is not None:
                handles.callback(os.close, fd)
            yield fd

    def names(self) -> list[str]:
        names = set(BUILTIN_TEMPLATES)
        with self._directory() as directory:
            if directory is not None:
                for index, filename in enumerate(os.listdir(directory)):
                    if index >= MAX_TEMPLATE_ENTRIES:
                        raise OSError(f"Too many templates; limit is {MAX_TEMPLATE_ENTRIES}")
                    if not filename.endswith(".md"):
                        continue
                    name = filename[:-3]
                    try:
                        _name(name)
                    except ValueError:
                        continue
                    try:
                        info = os.stat(filename, dir_fd=directory, follow_symlinks=False)
                    except OSError:
                        continue
                    if not stat.S_ISREG(info.st_mode):
                        continue  # One stray link or folder must not hide every template.
                    names.add(name)
        return sorted(names)

    def read(self, name: str) -> str:
        _name(name)
        if name in BUILTIN_TEMPLATES:
            return BUILTIN_TEMPLATES[name]
        with self._directory() as directory:
            if directory is None:
                raise FileNotFoundError(f"Template does not exist: {name}")
            return read_regular_at(directory, name + ".md", MAX_NOTE_BYTES)

    def save(self, name: str, body: str) -> None:
        _name(name)
        if name in BUILTIN_TEMPLATES:
            raise FileExistsError("Built-in template name; choose a different name")
        if not isinstance(body, str):
            raise ValueError("Template body must be text")
        raw = body.encode("utf-8")
        if len(raw) > MAX_NOTE_BYTES:
            raise ValueError("Template exceeds the note size limit")
        with vault_lock(self.vault_path) as vault_directory, self._directory(
                create=True, vault_directory=vault_directory) as directory:
            fd, temporary = create_private_temp(directory, ".tmp-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                # An atomic hard link publishes the complete file without replacing
                # an existing name, even when an external writer ignores our lock.
                try:
                    os.link(temporary, name + ".md", src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                except FileExistsError:
                    raise FileExistsError("Template already exists; choose a different name") from None
                os.fsync(directory)
            finally:
                os.unlink(temporary, dir_fd=directory)

    def render(self, name: str, workspace: str, **context: str) -> str:
        return self.render_text(self.read(name), workspace, **context)

    def render_text(self, source: str, workspace: str, **context: str) -> str:
        validate_workspace(workspace)
        stamp = datetime.now().astimezone()
        values = {"date": stamp.date().isoformat(), "time": stamp.strftime("%H:%M"),
                  "workspace": workspace, "title": "", "body": "", "selection": "", **context}
        remaining = 64

        def expand(text, stack):
            def substitute(match):
                nonlocal remaining
                key = match[1]
                if key.startswith('template:'):
                    name = key[9:]
                    remaining -= 1
                    if name in stack or len(stack) >= 8 or remaining < 0:
                        raise ValueError("Template includes are recursive or exceed the expansion limit")
                    return expand(self.read(name), (*stack, name))
                if key.startswith('date:'):
                    return stamp.strftime(key[5:])
                return values.get(key, match[0])
            # Append bounded pieces instead of allocating an unbounded expanded string.
            pieces, end, size = [], 0, 0
            for match in re.finditer(r"\{\{([^{}]+)\}\}", text):
                for piece in (text[end:match.start()], substitute(match)):
                    size += len(piece.encode('utf-8'))
                    if size > MAX_NOTE_BYTES:
                        raise ValueError("Expanded template exceeds the note size limit")
                    pieces.append(piece)
                end = match.end()
            tail = text[end:]
            if size + len(tail.encode('utf-8')) > MAX_NOTE_BYTES:
                raise ValueError("Expanded template exceeds the note size limit")
            return ''.join(pieces) + tail
        return expand(source, ())


GUIDE = """# A little room to think

Capture first. Press Ctrl+N and write without choosing a folder or title.
The first line becomes the title. Your words save automatically.

## A simple rhythm
- Capture loose thoughts in the inbox.
- Ctrl+D opens today's log: observations, decisions, and next steps.
- Ctrl+P → Previous/next daily log, or Open daily log by date, moves through other days.
- Keep a useful idea in its own note. Select it and Ctrl+P → Extract selection to new note.
- Review the inbox with Ctrl+P → Process next inbox note. Move useful notes to projects, areas, or resources.
- Archive what is finished. Trash is reversible; move a note back to restore it.

## Make it yours
Ctrl+, opens Settings for themes, editor, layout, keyboard shortcuts, and daily templates.
Hotkey changes apply on Save. Ctrl+, and Esc stay fixed; Reset hotkeys restores defaults.
Preferences are saved for this vault.

## Writing
Use Markdown: # headings, **bold**, *italic*, ~~strikethrough~~, `code`, - lists,
1. numbered lists, - [ ] tasks, > quotes, tables, and fenced code. The editor
colours Markdown as you type.
Enter continues a bullet, numbered, task, or quote line. Enter on an empty item ends it.
Select text, then Ctrl+P → Format bold, italic, strikethrough, inline code, or link.
Without a selection, a selected placeholder is inserted. Run a format again to remove it.
Headings (levels 1–6), bullet, numbered and task lists, blockquotes, code blocks,
and indent or outdent apply to the current line or selected lines. Undo works normally.
Ctrl+P → Format table inserts a table, or lines up the columns of the table under the cursor.
Ctrl+P → Preview rendered Markdown displays your current text; Esc returns to editing.
Ctrl+P → Toggle side-by-side Markdown preview keeps a live preview next to the editor.
Ctrl+P → Jump to heading moves through a long note.
Add #tags anywhere; search #tag to find exact tag matches.
Ctrl+T browses workspace tags and counts. Ctrl+P → Add tags appends tags.
Edit or remove inline tags directly in the note; no separate tag database is needed.

## Workspaces
Ctrl+W switches workspaces or creates one, such as work or personal.
Ctrl+P → Move note to workspace moves a regular note without changing its file ID.
Each workspace has its own daily logs, collections, search results, and links.
Existing notes are in default. Workspace names use lowercase letters, numbers, - or _.
All Markdown stays in the same vault folder; workspace is saved in note metadata.
Appearance and editor settings are shared across this vault.

## Navigation
Ctrl+P → Toggle task checks or unchecks the current line.
Ctrl+B hides the sidebar. Ctrl+O finds a note by title.
Ctrl+F searches this workspace (except trash). Multiple words narrow results.
Alt+K shows incoming and outgoing connections, with the line that contains each link.
Ctrl+P → Follow a link opens the [[link]] under the cursor. Broken links can create a note.
Click a link in preview, or Ctrl+click one in the editor.
Links inserted by Jotline use stable IDs, so changing titles is safe.

## Templates and history
Ctrl+P → New note from template starts a meeting, project, journal, or saved template.
Save this note as a template keeps a reusable copy; use {{date}}, {{time}}, {{workspace}}.
Copy template source to new note preserves placeholders for customization.
Ctrl+, → Keyboard shortcuts includes optional Markdown formatting, preview,
previous/next daily log, extract selection, and process-inbox keys.
Ctrl+P → History of this note lets you inspect and restore a saved version as a new note.
Browse saved note history includes externally deleted notes in this workspace.
Back up vault now saves a local ZIP of notes, settings, and templates.
Check vault health and Open a recovery copy surface doctor warnings and copies saved after an external change.

## Your files
Everything stays in your local vault as readable Markdown.
Use `jotline capture` to send text from the shell, and `jotline export` to
write a note without metadata. No account, telemetry, or cloud service.
`jotline sync` prints a Git or Syncthing recipe that uses the same recovery
dialog as an external editor. Ctrl+Q flushes edits before quitting. Use it
before closing the terminal.

## Clipboard and accessibility
Ctrl+P → Copy note sends an OSC 52 *request*. The terminal decides whether the
system clipboard changes; Jotline will not claim that it did. Ctrl+P →
Clipboard, IME, and screen-reader notes explains Terminal.app, Windows Terminal,
and Orca limits. Native reports in docs/terminal-reports/ are a 1.0 ship
criterion.
"""

REVIEW = """# Weekly review

## Clear the inbox
- [ ] Read unprocessed captures (Ctrl+P → Process next inbox note).
- [ ] Turn actionable thoughts into a concrete next step.
- [ ] Move active work to projects and ongoing responsibilities to areas.
- [ ] Keep reference material in resources; archive what is finished.

## Connect and reflect
- [ ] Revisit this week's daily logs.
- [ ] Extract useful ideas into their own notes and link them.
- [ ] Review active projects: what is the next small action?
- [ ] Choose what deserves attention next week.

## What I learned

## Next week

"""
