"""Windows storage primitives (imported only on Windows).

Directory handles omit FILE_SHARE_DELETE, preventing rename/removal while in
use. Every ancestor is pinned too. Files are opened with OPEN_REPARSE_POINT and
checked on the resulting handle, rejecting symlinks, junctions and other reparse
points without a check/open race. File descriptors always use binary mode.

See https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
Windows has no equivalent of POSIX directory fsync; file contents are flushed,
but directory metadata durability across power loss is filesystem dependent.
The mode argument of open() is accepted for interface parity but has no effect:
new files inherit the folder's ACL, so private temporary files are exactly as
private as the vault folder itself.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import itertools
import msvcrt
import ntpath
import os
import re
import threading


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
CreateFileW.restype = wintypes.HANDLE
CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL
GetFileType = kernel32.GetFileType
GetFileType.argtypes = [wintypes.HANDLE]
GetFileType.restype = wintypes.DWORD
GetFileInformationByHandleEx = kernel32.GetFileInformationByHandleEx
GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
GetFileInformationByHandleEx.restype = wintypes.BOOL


class BasicInfo(ctypes.Structure):
    _fields_ = [("created", ctypes.c_longlong), ("accessed", ctypes.c_longlong),
                ("modified", ctypes.c_longlong), ("changed", ctypes.c_longlong),
                ("attributes", wintypes.DWORD)]


def _file_info(handle):
    info = BasicInfo()
    if not GetFileInformationByHandleEx(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info


@dataclass
class Directory:
    path: str
    handle: int
    parent: int | None


class WindowsFS:
    # Private flags outside the CRT flag range; not passed to open_osfhandle.
    O_DIRECTORY = 1 << 28
    O_NOFOLLOW = 1 << 29
    O_NONBLOCK = 0

    def __init__(self):
        self._directories = {}
        self._ids = itertools.count(-1, -1)
        self._mutex = threading.RLock()

    def __getattr__(self, name):
        return getattr(os, name)

    def _directory(self, fd):
        try:
            return self._directories[fd]
        except KeyError:
            raise OSError(9, "Invalid directory descriptor") from None

    def _path(self, path, directory=None):
        path = os.fspath(path)
        if directory is not None:
            # All descriptor-relative callers use a single validated basename.
            if not path or path in (".", "..") or any(c in path for c in "/\\:"):
                raise ValueError("Expected a single storage filename")
            path = ntpath.join(self._directory(directory).path, path)
        path = ntpath.abspath(path)
        if path.startswith(("\\\\.\\", "\\\\?\\")):
            raise ValueError("Device paths are not supported")
        for component in path[len(ntpath.splitdrive(path)[0]):].split("\\"):
            if component and (component[-1] in " ." or any(c in component for c in ':*?"<>|')
                              or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])", component.split('.')[0])
                              or any(ord(c) < 32 for c in component)):
                raise ValueError("Unsafe Windows filename")
        return path

    @staticmethod
    def _handle(path, *, directory=False, flags=0):
        # Extended paths support long vault names without relying on machine policy.
        native = "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path
        # Metadata-only access (zero) does not enforce sharing restrictions.
        # FILE_LIST_DIRECTORY participates in sharing checks and pins the name.
        access = 1 if directory else (0xC0000000 if flags & os.O_RDWR else
                                      0x40000000 if flags & os.O_WRONLY else 0x80000000)
        disposition = 1 if flags & os.O_CREAT and flags & os.O_EXCL else 4 if flags & os.O_CREAT else 3
        handle = CreateFileW(native, access, 3 if directory else 7, None,
                             disposition, 0x02000000 | 0x00200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = _file_info(handle)
            if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory or GetFileType(handle) != 1:
                label = "Not a safe directory" if directory else "Not a regular file"
                raise OSError(f"{label}: {path}")
            return handle
        except BaseException:
            CloseHandle(handle)
            raise

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        path = self._path(path, dir_fd)
        if flags & self.O_DIRECTORY:
            parent_path = ntpath.dirname(path)
            parent = None
            try:
                if parent_path != path:
                    parent = self.open(parent_path, self.O_DIRECTORY)
                handle = self._handle(path, directory=True)
            except BaseException:
                if parent is not None:
                    self.close(parent)
                raise
            with self._mutex:
                fd = next(self._ids)
                self._directories[fd] = Directory(path, handle, parent)
            return fd
        with self._parent(path, dir_fd):
            handle = self._handle(path, flags=flags)
            try:
                fd = msvcrt.open_osfhandle(handle, (flags & (os.O_RDWR | os.O_WRONLY)) | os.O_BINARY)
            except BaseException:
                CloseHandle(handle)
                raise
            return fd

    @contextmanager
    def _parent(self, path, existing):
        own = existing is None
        fd = self.open(ntpath.dirname(path), self.O_DIRECTORY) if own else existing
        try:
            yield fd
        finally:
            if own:
                self.close(fd)

    def close(self, fd):
        if fd >= 0:
            return os.close(fd)
        with self._mutex:
            entry = self._directory(fd)
            del self._directories[fd]
            CloseHandle(entry.handle)
            if entry.parent is not None:
                self.close(entry.parent)

    def dup(self, fd):
        if fd >= 0:
            return os.dup(fd)
        return self.open(self._directory(fd).path, self.O_DIRECTORY)

    def fsync(self, fd):
        if fd >= 0:
            os.fsync(fd)
        else:
            self._directory(fd)  # Validate even though directory flushing is unavailable.

    def file_signature(self, path):
        fd = self.open(path, os.O_RDONLY | self.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            basic = _file_info(msvcrt.get_osfhandle(fd))
            # Python's Windows st_ctime is creation time in 3.11–3.13. Use the
            # native change time to help detect edits with a restored mtime.
            return info.st_dev, info.st_ino, info.st_size, basic.modified * 100, basic.changed * 100
        finally:
            self.close(fd)

    def _as_path(self, path):
        return self._directory(path).path if isinstance(path, int) else path

    def scandir(self, path):
        return os.scandir(self._as_path(path))

    def listdir(self, path):
        return os.listdir(self._as_path(path))

    def stat(self, path, *, dir_fd=None, follow_symlinks=True):
        return os.stat(self._path(path, dir_fd), follow_symlinks=follow_symlinks)

    def mkdir(self, path, mode=0o777, *, dir_fd=None):
        return os.mkdir(self._path(path, dir_fd), mode)

    def unlink(self, path, *, dir_fd=None):
        return os.unlink(self._path(path, dir_fd))

    def replace(self, source, target, *, src_dir_fd=None, dst_dir_fd=None):
        return os.replace(self._path(source, src_dir_fd), self._path(target, dst_dir_fd))

    def link(self, source, target, *, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=True):
        return os.link(self._path(source, src_dir_fd), self._path(target, dst_dir_fd),
                       follow_symlinks=follow_symlinks)
