"""Storage OS interface using native POSIX descriptors.

The implementation is the os module itself so dir_fd guarantees remain unchanged.
Windows is out of scope; the process entry refuses that platform before this
module is imported.
"""
import fcntl
import os

fs = os


def lock_file(fd: int, *, unlock: bool = False) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)
