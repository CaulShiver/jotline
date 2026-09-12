"""Reusable local Markdown templates with literal placeholder substitution."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime
from pathlib import Path
import re
import stat

from .filesystem import fs as os
from .store import (MAX_NOTE_BYTES, create_private_temp, read_regular_at,
                    validate_workspace, vault_lock)

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
                    info = os.stat(filename, dir_fd=directory, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        raise OSError(f"Not a regular template file: {filename}")
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

    def render(self, name: str, workspace: str) -> str:
        validate_workspace(workspace)
        stamp = datetime.now().astimezone()
        values = {"date": stamp.date().isoformat(), "time": stamp.strftime("%H:%M"), "workspace": workspace}
        return re.sub(r"\{\{(date|time|workspace)\}\}", lambda match: values[match[1]], self.read(name))
