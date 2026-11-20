"""Preview a Jotline ZIP and publish a private, separate vault without replacing anything."""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import stat
from uuid import uuid4
import zipfile
import zlib

from .filesystem import FileSignature, fs as os, pin_ancestors, rename_noreplace
from .history import MAX_BACKUP_BYTES, MAX_BACKUP_ENTRIES, MAX_MANIFEST_BYTES
from .limits import MAX_NOTE_BYTES, MAX_SETTINGS_BYTES
from .terminal import terminal_text

MANIFEST = "jotline-backup-manifest.json"
SETTINGS = ".jotline-settings.json"
KEY = ".jotline-key.json"
TEMPLATES = ".jotline-templates"
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@dataclass(frozen=True)
class BackupPreview:
    source: Path
    signature: FileSignature
    created: str
    notes: int
    templates: int
    settings: bool
    key: bool
    skipped: int
    examples: tuple[str, ...]

    def describe(self) -> str:
        lines = [
            f"Backup: {terminal_text(self.source)}",
            f"Created: {terminal_text(self.created)}",
            f"Markdown notes: {self.notes} · Templates: {self.templates}",
            f"Settings: {'included' if self.settings else 'not included'}",
            f"Encryption key: {'included (passphrase still required)' if self.key else 'not included'}",
            f"Skipped when backed up: {self.skipped}",
        ]
        lines.extend(f"  {terminal_text(example)}" for example in self.examples)
        if self.skipped > len(self.examples):
            lines.append(f"  … and {self.skipped - len(self.examples)} more; see the ZIP manifest")
        lines.append("Note history and other backups are not restored.")
        return "\n".join(lines)


def _signature(fd: int) -> FileSignature:
    info = os.fstat(fd)
    return FileSignature(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def _archive(source: Path):
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Backup must be a regular ZIP file")
        # Allow room for the manifest and ZIP headers in addition to the payload budget.
        if info.st_size > MAX_BACKUP_BYTES + 2 * MAX_MANIFEST_BYTES:
            raise ValueError("Backup ZIP exceeds the size limit")
        before = _signature(fd)
        try:
            with zipfile.ZipFile(stream) as archive:
                yield archive, fd, before
        except (zipfile.BadZipFile, zlib.error, EOFError) as error:
            raise ValueError(f"Invalid backup ZIP: {error}") from error


def _entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_BACKUP_ENTRIES:
        raise ValueError("Backup ZIP has an invalid entry count")
    entries = {}
    for info in infos:
        name = info.filename
        parts = name.split("/")
        if (info.orig_filename != name or any(part in {"", ".", ".."} for part in parts)
                or "\\" in name or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)):
            raise ValueError(f"Unsafe backup entry: {name!r}")
        if name in entries:
            raise ValueError(f"Duplicate backup entry: {name!r}")
        if name == MANIFEST:
            limit = MAX_MANIFEST_BYTES
        elif name in (SETTINGS, KEY):
            limit = MAX_SETTINGS_BYTES
        elif name.endswith(".md") and (len(parts) == 1 or (len(parts) == 2 and parts[0] == TEMPLATES)):
            limit = MAX_NOTE_BYTES
        else:
            raise ValueError(f"Unsupported backup entry: {name!r}")
        if info.file_size > limit:
            raise ValueError(f"Backup entry exceeds the size limit: {name!r}")
        if info.flag_bits & (1 | 32 | 64) or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError(f"Unsupported ZIP encoding for {name!r}")
        entries[name] = info
    if MANIFEST not in entries:
        raise ValueError("Jotline backup manifest is missing")
    if len(entries) == 1:
        raise ValueError("Backup contains no vault files to restore")
    if sum(info.file_size for name, info in entries.items() if name != MANIFEST) > MAX_BACKUP_BYTES:
        raise ValueError("Backup contents exceed the size limit")
    return entries


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    data = archive.read(info)
    if len(data) != info.file_size:
        raise ValueError(f"Incomplete backup entry: {info.filename!r}")
    return data


def preview_backup(path: Path) -> BackupPreview:
    source = path.expanduser().absolute()
    with _archive(source) as (archive, fd, signature):
        entries = _entries(archive)
        try:
            manifest = json.loads(_read_member(archive, entries[MANIFEST]).decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError) as error:
            raise ValueError("Jotline backup manifest could not be read") from error
        if (not isinstance(manifest, dict) or not isinstance(manifest.get("created"), str)
                or not isinstance(manifest.get("scope"), str) or not isinstance(manifest.get("skipped"), list)):
            raise ValueError("Jotline backup manifest is incomplete")
        notes = templates = 0
        for name, info in entries.items():
            if name == MANIFEST:
                continue
            _read_member(archive, info).decode("utf-8")
            if name.endswith(".md"):
                if "/" in name:
                    templates += 1
                else:
                    notes += 1
        if _signature(fd) != signature:
            raise ValueError("Backup changed while it was being read; preview it again")
    skipped = manifest["skipped"]
    examples = tuple(
        f"{entry['path'][:160]}: {entry['reason'][:160]}"
        if isinstance(entry, dict) and isinstance(entry.get("path"), str) and isinstance(entry.get("reason"), str)
        else "See the ZIP manifest for details"
        for entry in skipped[:5]
    )
    return BackupPreview(source, signature, manifest["created"][:80], notes, templates,
                         SETTINGS in entries, KEY in entries, len(skipped), examples)


@contextmanager
def _destination(path: Path, active_vault: Path):
    target = Path(os.path.abspath(path.expanduser()))
    active = active_vault.expanduser().resolve()
    if target.is_relative_to(active):
        raise ValueError("Choose a new folder outside the current vault")
    if not target.name:
        raise ValueError("Choose a new folder for the restored vault")
    try:
        parent = pin_ancestors(target)
    except FileNotFoundError as error:
        raise ValueError("The restore destination's parent folder must already exist") from error
    try:
        # Compare directory identities as well as path strings (e.g. case aliases on macOS).
        try:
            active_info = os.stat(active)
        except FileNotFoundError:
            pass
        else:
            ancestor = os.dup(parent)
            try:
                while True:
                    info = os.fstat(ancestor)
                    if os.path.samestat(info, active_info):
                        raise ValueError("Choose a new folder outside the current vault")
                    above = os.open("..", DIR_FLAGS, dir_fd=ancestor)
                    os.close(ancestor)
                    ancestor = above
                    if os.path.samestat(info, os.fstat(ancestor)):
                        break
            finally:
                os.close(ancestor)
        try:
            os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            yield target, parent
        else:
            raise ValueError("Restore destination already exists; choose a new folder")
    finally:
        os.close(parent)


def check_destination(path: Path, active_vault: Path) -> Path:
    with _destination(path, active_vault) as (target, _):
        return target


def restore_backup(preview: BackupPreview, path: Path, active_vault: Path) -> Path:
    with _destination(path, active_vault) as (target, parent), _archive(preview.source) as (archive, fd, signature):
        if signature != preview.signature:
            raise ValueError("Backup changed since the preview; preview it again")
        entries = _entries(archive)
        temporary = f".jotline-restore-{uuid4().hex}"
        os.mkdir(temporary, 0o700, dir_fd=parent)
        with ExitStack() as handles, ExitStack() as undo:
            undo.callback(os.rmdir, temporary, dir_fd=parent)
            root = os.open(temporary, DIR_FLAGS, dir_fd=parent)
            handles.callback(os.close, root)
            template_dir = None
            for name, info in entries.items():
                if name == MANIFEST:
                    continue
                data = _read_member(archive, info)
                folder, filename = root, name
                if "/" in name:
                    if template_dir is None:
                        os.mkdir(TEMPLATES, 0o700, dir_fd=root)
                        undo.callback(os.rmdir, TEMPLATES, dir_fd=root)
                        template_dir = os.open(TEMPLATES, DIR_FLAGS, dir_fd=root)
                        handles.callback(os.close, template_dir)
                    folder, filename = template_dir, name.split("/")[1]
                file = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600, dir_fd=folder)
                undo.callback(os.unlink, filename, dir_fd=folder)
                with os.fdopen(file, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            if template_dir is not None:
                os.fsync(template_dir)
            os.fsync(root)
            if _signature(fd) != signature:
                raise ValueError("Backup changed during restore; preview it again")
            try:
                rename_noreplace(temporary, target.name, src_dir_fd=parent, dst_dir_fd=parent)
            except FileExistsError as error:
                raise ValueError("Restore destination already exists; choose a new folder") from error
            undo.pop_all()
            try:
                os.fsync(parent)
            except OSError as error:
                raise OSError(f"Files were restored to {target}, but the folder could not be synced: {error}") from error
    return target
