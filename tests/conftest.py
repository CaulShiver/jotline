"""Platform capabilities used by filesystem regression tests."""
import os
from pathlib import Path

import pytest


def pytest_collection_modifyitems(items):
    if hasattr(os, "mkfifo"):
        return
    for item in items:
        parameters = getattr(item, "callspec", None)
        if parameters and "fifo" in parameters.params.values():
            item.add_marker(pytest.mark.skip(reason="POSIX named pipes are unavailable on Windows"))


@pytest.fixture(autouse=True)
def symlink_capability(monkeypatch):
    if os.name != "nt":
        return
    original = Path.symlink_to

    def symlink(path, target, target_is_directory=False):
        try:
            return original(path, target, target_is_directory=target_is_directory)
        except OSError as error:
            if error.winerror == 1314:
                pytest.skip("Windows symlink tests need Developer Mode or symlink privilege")
            raise

    monkeypatch.setattr(Path, "symlink_to", symlink)


@pytest.fixture
def resource_count():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

        def count():
            value = wintypes.DWORD()
            if not kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), ctypes.byref(value)):
                raise ctypes.WinError(ctypes.get_last_error())
            return value.value

        return count
    return lambda: len(os.listdir("/dev/fd"))


@pytest.fixture
def fault_entry_stat(monkeypatch):
    """Inject a stat failure for one directory entry, keeping real directory I/O."""
    from contextlib import contextmanager

    def install(filesystem, name, fault):
        scandir = filesystem.scandir

        class Entry:
            def __init__(self, entry):
                self.entry = entry

            def __getattr__(self, key):
                return getattr(self.entry, key)

            def stat(self, **kwargs):
                fault()
                return self.entry.stat(**kwargs)

        @contextmanager
        def scan(folder):
            with scandir(folder) as entries:
                yield (Entry(entry) if entry.name == name else entry for entry in entries)

        monkeypatch.setattr(filesystem, 'scandir', scan)

    return install
