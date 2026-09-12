"""Cross-platform defaults, byte preservation, and Windows handle protection."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jotline import cli
from jotline.filesystem import fs
from jotline.store import Vault, read_regular_file


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    for name in ('JOTLINE_VAULT', 'XDG_DATA_HOME', 'LOCALAPPDATA'):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.mark.parametrize('platform,relative', [
    ('linux', '.local/share/jotline/notes'),
    ('darwin', 'Library/Application Support/jotline/notes'),
    ('win32', 'AppData/Local/jotline/notes'),
])
def test_platform_default(home, monkeypatch, platform, relative):
    monkeypatch.setattr(sys, 'platform', platform)
    assert cli.default_vault() == home / relative
    monkeypatch.setenv('JOTLINE_VAULT', str(home / 'custom'))
    assert cli.default_vault() == home / 'custom'


def test_windows_uses_local_appdata(home, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setenv('LOCALAPPDATA', str(home / 'local'))
    monkeypatch.setenv('XDG_DATA_HOME', str(home / 'xdg'))
    assert cli.default_vault() == home / 'local/jotline/notes'


def test_macos_preserves_existing_and_explicit_xdg_vault(home, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    legacy = home / '.local/share/jotline/notes'
    legacy.mkdir(parents=True)
    assert cli.default_vault() == legacy
    monkeypatch.setenv('XDG_DATA_HOME', str(home / 'xdg'))
    assert cli.default_vault() == home / 'xdg/jotline/notes'


def test_unicode_and_mixed_newlines_survive_repeated_saves(tmp_path):
    vault = Vault(tmp_path / 'My notes — 日本語')
    note = vault.new('é 📝\nline two\r\nline three\n')
    vault.save(note)
    assert vault.read(note.id).body == note.body
    assert vault.file(note.id).read_bytes().decode('utf-8') == note.original
    note.body += 'another line\n'
    vault.save(note)
    assert vault.read(note.id).body == note.body


def test_unicode_cli_pipeline_without_utf8_environment(tmp_path):
    env = dict(os.environ, PYTHONUTF8='0', PYTHONIOENCODING='ascii')
    command = [sys.executable, '-m', 'jotline', '--vault', str(tmp_path)]
    # Windows configures output itself. Unix honors the user's locale/encoding.
    if os.name != 'nt':
        env['PYTHONIOENCODING'] = 'utf-8'
    body = '日本語 📝\r\né\n'.encode('utf-8')
    captured = subprocess.run(command + ['capture'], input=body, capture_output=True, env=env, timeout=15)
    assert captured.returncode == 0, captured.stderr
    exported = subprocess.run(command + ['export', captured.stdout.decode().strip()],
                              capture_output=True, env=env, timeout=15)
    assert exported.returncode == 0, exported.stderr
    assert exported.stdout == body


def test_separate_process_cannot_write_until_lock_is_released(tmp_path):
    vault = Vault(tmp_path)
    command = [sys.executable, '-m', 'jotline', '--vault', str(tmp_path), 'capture', 'saved']
    with vault.locked():
        blocked = subprocess.run(command, capture_output=True, timeout=15)
        assert blocked.returncode == 1
        assert b'busy' in blocked.stderr
        assert not list(tmp_path.glob('*.md'))
    saved = subprocess.run(command, capture_output=True, timeout=15)
    assert saved.returncode == 0, saved.stderr
    assert vault.read(saved.stdout.decode().strip()).body == 'saved'


def test_lock_creation_race_reopens_winners_file(tmp_path, monkeypatch):
    real_open = fs.open
    raced = False

    def open_with_race(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal raced
        if path == '.jotline.lock' and flags & fs.O_EXCL and not raced:
            raced = True
            other = real_open(path, flags, mode, dir_fd=dir_fd)
            fs.close(other)
            raise FileExistsError('another writer created the lock')
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(fs, 'open', open_with_race)
    vault = Vault(tmp_path)
    note = vault.new('survives creation race')
    vault.save(note)
    assert raced
    assert vault.read(note.id).body == note.body


@pytest.mark.skipif(os.name != 'nt', reason='Native Windows handle protection')
def test_windows_pins_directory_and_ancestors_until_close(tmp_path):
    parent = tmp_path / 'parent'
    folder = parent / 'vault'
    folder.mkdir(parents=True)
    fd = fs.open(folder, fs.O_DIRECTORY | fs.O_NOFOLLOW)
    duplicate = fs.dup(fd)
    fs.close(fd)
    try:
        for source in (folder, parent):
            with pytest.raises(OSError):
                source.rename(source.with_name('moved'))
    finally:
        fs.close(duplicate)
    folder.rename(parent / 'moved')


@pytest.mark.skipif(os.name != 'nt', reason='Windows junctions')
def test_windows_rejects_junctions_in_storage_and_import(tmp_path):
    vault = Vault(tmp_path / 'vault')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.md').write_text('private')
    junction = vault.path / '.jotline-templates'
    import _winapi
    _winapi.CreateJunction(str(outside), str(junction))
    try:
        from jotline.templates import Templates
        warnings = []
        assert cli.check_managed_directory(junction, 'templates', warnings) is None
        assert warnings
        with pytest.raises(OSError):
            Templates(vault.path).save('test', 'must not escape')
        with pytest.raises(OSError):
            read_regular_file(junction / 'private.md', ancestor_safe=True)
        assert not (outside / 'test.md').exists()
    finally:
        junction.rmdir()


@pytest.mark.skipif(os.name != 'nt', reason='Windows handle cleanup')
def test_windows_failed_opens_close_ancestor_handles(tmp_path, resource_count):
    baseline = resource_count()
    for _ in range(32):
        with pytest.raises(FileNotFoundError):
            read_regular_file(tmp_path / 'missing.md')
    assert resource_count() == baseline
