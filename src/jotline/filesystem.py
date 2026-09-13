"""Storage OS interface: native descriptors on Unix, pinned handles on Windows.

The Unix implementation is the os module itself so its dir_fd guarantees remain
unchanged. Windows implements the small descriptor-relative subset used by the
store; it never silently downgrades a pinned operation to an unprotected path.
"""
import errno
import os
import sys
from functools import lru_cache

if os.name == "nt":
    import msvcrt

    from ._windows_fs import WindowsFS

    fs = WindowsFS()
else:
    import fcntl

    fs = os


@lru_cache(maxsize=1)
def _exclusive_rename():
    """Resolve the native no-replace operation without weakening dir_fd semantics."""
    import ctypes

    if sys.platform.startswith("linux"):
        name, flag, cwd = "renameat2", 1, -100  # RENAME_NOREPLACE, AT_FDCWD
    elif sys.platform == "darwin":
        name, flag, cwd = "renameatx_np", 4, -2  # RENAME_EXCL, AT_FDCWD
    else:
        raise OSError(errno.ENOTSUP, "This platform cannot safely publish without hard links")
    try:
        operation = getattr(ctypes.CDLL(None, use_errno=True), name)
    except AttributeError:
        raise OSError(errno.ENOTSUP, "This platform cannot safely publish without hard links") from None
    operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    operation.restype = ctypes.c_int
    return operation, flag, cwd


def rename_noreplace(source, target, *, src_dir_fd=None, dst_dir_fd=None) -> None:
    """Atomically move a complete file only if the destination name is free.

    Never emulate this with stat followed by replace: that loses a concurrent
    creator's file. Unsupported filesystems fail with the source still intact.
    """
    if os.name == "nt":
        # Windows rename always refuses an existing destination; the facade
        # keeps the source and destination ancestors pinned during the call.
        fs.rename(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        return
    import ctypes

    operation, flag, cwd = _exclusive_rename()
    source_bytes, target_bytes = os.fsencode(source), os.fsencode(target)
    if b"\0" in source_bytes or b"\0" in target_bytes:
        raise ValueError("embedded null byte")
    if operation(cwd if src_dir_fd is None else src_dir_fd, source_bytes,
                 cwd if dst_dir_fd is None else dst_dir_fd, target_bytes, flag):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(target))


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
