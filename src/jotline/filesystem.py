"""Storage OS interface: native descriptors on Unix, pinned handles on Windows.

The Unix implementation is the os module itself so its dir_fd guarantees remain
unchanged. Windows implements the small descriptor-relative subset used by the
store; it never silently downgrades a pinned operation to an unprotected path.
"""
import errno
import os

if os.name == "nt":
    import msvcrt

    from ._windows_fs import WindowsFS

    fs = WindowsFS()
else:
    import fcntl

    fs = os


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
