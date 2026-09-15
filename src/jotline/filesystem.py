"""Storage OS interface: native descriptors on Unix, pinned handles on Windows.

The Unix implementation is the os module itself so its dir_fd guarantees remain
unchanged. Windows implements the small descriptor-relative subset used by the
store; it never silently downgrades a pinned operation to an unprotected path.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import stat
from time import monotonic, sleep
from typing import NamedTuple
from uuid import uuid4

from .limits import LOCK_TIMEOUT_SECONDS, MAX_NOTE_BYTES

if os.name == "nt":
    import msvcrt

    from ._windows_fs import WindowsFS

    fs = WindowsFS()
else:
    import fcntl

    fs = os


class FileSignature(NamedTuple):
    """What must match for a cached parse of a note file to be reused."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


def lock_file(fd: int, *, unlock: bool = False) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            # Windows permits locking a byte beyond EOF, including an empty file.
            msvcrt.locking(fd, msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if not unlock and error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError(errno.EAGAIN, "Vault lock is held") from error
            raise
    else:
        fcntl.flock(fd, fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)


def read_regular_fd(fd: int, name: str, max_bytes: int, encoding: str = "utf-8", errors: str = "strict") -> str:
    info = fs.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"Not a regular file: {name}")
    if info.st_size > max_bytes:
        raise ValueError(f"{name} exceeds the {max_bytes}-byte file limit")
    raw = bytearray()
    while len(raw) <= max_bytes:
        chunk = fs.read(fd, min(64 * 1024, max_bytes + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    if len(raw) > max_bytes:
        raise ValueError(f"{name} exceeds the {max_bytes}-byte file limit")
    return bytes(raw).decode(encoding, errors)


def read_regular_at(directory: int, name: str, max_bytes: int = MAX_NOTE_BYTES) -> str:
    fd = fs.open(name, fs.O_RDONLY | fs.O_NOFOLLOW | fs.O_NONBLOCK, dir_fd=directory)
    try:
        return read_regular_fd(fd, name, max_bytes)
    finally:
        fs.close(fd)


def create_private_temp(directory: int, prefix: str) -> tuple[int, str]:
    """Create a private file inside an already-pinned directory."""
    for _ in range(100):
        name = prefix + uuid4().hex
        try:
            fd = fs.open(name, fs.O_RDWR | fs.O_CREAT | fs.O_EXCL | fs.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            return fd, name
        except FileExistsError:
            continue
    raise FileExistsError("Could not allocate private storage")


def replace_at(directory: int, source: str, target: str) -> None:
    """Replace within a pinned directory, failing closed if dir_fd is unsupported."""
    fs.replace(source, target, src_dir_fd=directory, dst_dir_fd=directory)


def unlink_quietly(directory: int, name: str) -> None:
    """Remove a temporary file from a pinned directory; it may already be gone."""
    try:
        fs.unlink(name, dir_fd=directory)
    except FileNotFoundError:
        pass


# Hard links are refused on FAT/exFAT media, most SMB shares and shared folders.
LINK_UNSUPPORTED = {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.EXDEV,
                    getattr(errno, "ENOSYS", errno.EPERM), errno.EACCES}


def link_unsupported(error: OSError) -> bool:
    return error.errno in LINK_UNSUPPORTED


def publish_new(directory: int, source: str, target: str) -> None:
    """Publish a complete file under a name that must not already exist.

    A hard link is atomic and exclusive. Where the filesystem refuses links,
    fall back to an existence check plus rename so the note is never lost.
    """
    try:
        fs.link(source, target, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    except OSError as error:
        if isinstance(error, FileExistsError) or not link_unsupported(error):
            raise
        try:
            fs.stat(target, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            fs.replace(source, target, src_dir_fd=directory, dst_dir_fd=directory)
        else:
            raise FileExistsError(errno.EEXIST, "File exists", target) from None


def follow_root_prefix_symlinks(path: Path) -> Path:
    """Follow only a root-level directory symlink such as macOS /tmp or /var.

    Those prefixes are OS compatibility links to /private/*. User-created
    aliases later in the path stay in place so pin_ancestors can refuse them.
    """
    path = Path(path)
    if not path.is_absolute():
        path = path.absolute()
    parts = path.parts
    if len(parts) < 2:
        return path
    prefix = Path(parts[0]) / parts[1]
    try:
        if not stat.S_ISLNK(prefix.lstat().st_mode):
            return path
        target = prefix.resolve()
    except OSError:
        return path
    if not target.is_dir():
        return path
    return target.joinpath(*parts[2:])


def pin_ancestors(absolute: Path) -> int:
    """Open every ancestor of an absolute path without following links.

    Returns a descriptor for the parent directory; the caller closes it.
    macOS /tmp and /var are followed first; other aliases still fail.
    """
    absolute = follow_root_prefix_symlinks(Path(absolute).absolute())
    directory = fs.open(absolute.anchor, fs.O_RDONLY | fs.O_DIRECTORY)
    try:
        for component in absolute.parts[1:-1]:
            try:
                next_directory = fs.open(component, fs.O_RDONLY | fs.O_DIRECTORY | fs.O_NOFOLLOW,
                                         dir_fd=directory)
            except OSError as error:
                if isinstance(error, NotADirectoryError) or error.errno == errno.ELOOP:
                    raise OSError(
                        f"Path passes through a link at {component}; use the real path") from None
                raise
            fs.close(directory)
            directory = next_directory
    except BaseException:
        fs.close(directory)
        raise
    return directory


def read_regular_file(path: Path, max_bytes: int = MAX_NOTE_BYTES, *, ancestor_safe: bool = False,
                      encoding: str = "utf-8", errors: str = "strict") -> str:
    """Read bounded text (UTF-8 by default) without following links or blocking on a pipe."""
    if ancestor_safe:
        absolute = follow_root_prefix_symlinks(Path(path).absolute())
        directory = pin_ancestors(absolute)
        try:
            fd = fs.open(absolute.name, fs.O_RDONLY | fs.O_NOFOLLOW | fs.O_NONBLOCK, dir_fd=directory)
        finally:
            fs.close(directory)
    else:
        fd = fs.open(path, fs.O_RDONLY | fs.O_NOFOLLOW | fs.O_NONBLOCK)
    try:
        return read_regular_fd(fd, path.name, max_bytes, encoding, errors)
    finally:
        fs.close(fd)


@contextmanager
def vault_lock(path: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
    """Coordinate local writers without hanging the UI indefinitely."""
    directory = fs.open(path, fs.O_RDONLY | fs.O_DIRECTORY | fs.O_NOFOLLOW)
    try:
        # APFS can report ENOENT for concurrent O_CREAT | O_NOFOLLOW opens.
        # Separate existing-file opens from exclusive creation and retry only
        # when another writer wins creation. Links still fail without following.
        flags = fs.O_RDWR | fs.O_NOFOLLOW | fs.O_NONBLOCK
        for _ in range(100):
            try:
                fd = fs.open(".jotline.lock", flags, dir_fd=directory)
                break
            except FileNotFoundError:
                try:
                    fd = fs.open(".jotline.lock", flags | fs.O_CREAT | fs.O_EXCL,
                                 0o600, dir_fd=directory)
                    break
                except FileExistsError:
                    continue
        else:
            raise OSError("Vault lock changed repeatedly; try saving again")
    except BaseException:
        fs.close(directory)
        raise
    try:
        if not stat.S_ISREG(fs.fstat(fd).st_mode):
            raise OSError("Jotline lock is not a regular file")
        deadline = monotonic() + timeout
        while True:
            try:
                lock_file(fd)
                break
            except BlockingIOError:
                if monotonic() >= deadline:
                    raise OSError("Vault is busy in another process; try saving again") from None
                sleep(0.025)
        try:
            yield directory
        finally:
            lock_file(fd, unlock=True)
    finally:
        fs.close(fd)
        fs.close(directory)


def file_signature(path: Path) -> FileSignature:
    if os.name == "nt":
        return FileSignature(*fs.file_signature(path))
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"Not a regular file: {path.name}")
    return FileSignature(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
