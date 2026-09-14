"""Cross-platform defaults and byte preservation for Linux and macOS."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from jotline import cli
from jotline.filesystem import fs
from jotline.importing import preview_import
from jotline.store import Vault, follow_root_prefix_symlinks, read_regular_file


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    for name in ('JOTLINE_VAULT', 'XDG_DATA_HOME'):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.mark.parametrize('platform,relative', [
    ('linux', '.local/share/jotline/notes'),
    ('darwin', 'Library/Application Support/jotline/notes'),
])
def test_platform_default(home, monkeypatch, platform, relative):
    monkeypatch.setattr(sys, 'platform', platform)
    assert cli.default_vault() == home / relative
    monkeypatch.setenv('JOTLINE_VAULT', str(home / 'custom'))
    assert cli.default_vault() == home / 'custom'


def test_macos_preserves_existing_and_explicit_xdg_vault(home, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    legacy = home / '.local/share/jotline/notes'
    legacy.mkdir(parents=True)
    assert cli.default_vault() == legacy
    monkeypatch.setenv('XDG_DATA_HOME', str(home / 'xdg'))
    assert cli.default_vault() == home / 'xdg/jotline/notes'


def test_os_tempdir_prefix_symlink_is_readable_and_importable(tmp_path):
    """pytest resolves TMPDIR; a raw TemporaryDirectory on macOS still goes through /var."""
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / 'from-temp.md'
        source.write_text('from os temp', encoding='utf-8')
        assert read_regular_file(source, ancestor_safe=True) == 'from os temp'
        plan = preview_import(Vault(tmp_path / 'vault'), source)
        assert plan.ready == 1, plan.warnings
        imported = subprocess.run(
            [sys.executable, '-m', 'jotline', '--vault', str(tmp_path / 'cli-vault'),
             'import', str(source)],
            capture_output=True, text=True, timeout=15)
        assert imported.returncode == 0, imported.stderr


@pytest.mark.skipif(not Path('/tmp').is_symlink(), reason='no root /tmp compatibility symlink')
def test_macos_tmp_prefix_symlink_is_followed_only_at_the_root():
    followed = follow_root_prefix_symlinks(Path('/tmp/jotline-probe.md'))
    assert followed == Path('/private/tmp/jotline-probe.md')
    kept = follow_root_prefix_symlinks(Path('/private/tmp/jotline-probe.md'))
    assert kept == Path('/private/tmp/jotline-probe.md')


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
