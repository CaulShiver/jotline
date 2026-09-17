"""Platform capabilities used by filesystem regression tests."""
import os

import pytest


@pytest.fixture
def resource_count():
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
