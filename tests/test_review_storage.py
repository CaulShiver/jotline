"""Regression coverage for malformed backup and encryption metadata."""
import zipfile
from datetime import date

import pytest

from jotline import crypto, history
from jotline.crypto import EncryptionError, KeyFile
from jotline.store import Vault


def test_save_replaces_daily_backup_with_deeply_nested_manifest(tmp_path):
    vault = Vault(tmp_path)
    folder = tmp_path / '.jotline-backups'
    folder.mkdir()
    daily = folder / f'daily-{date.today().isoformat()}.zip'
    with zipfile.ZipFile(daily, 'w') as archive:
        archive.writestr('old.md', 'preserved old backup note')
        archive.writestr('jotline-backup-manifest.json', '[' * 2000 + '0' + ']' * 2000)
    original = daily.read_bytes()

    note = vault.new('new note survives malformed backup')
    vault.save(note)

    assert vault.read(note.id).body == note.body
    quarantined = list(folder.glob('.invalid-*.zip'))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == original
    assert history.validate_backup(daily) == (True, '')
    with zipfile.ZipFile(daily) as archive:
        assert note.body.encode() in archive.read(f'{note.id}.md')
    assert 'Invalid daily backup retained' in vault.backup_warning


@pytest.mark.parametrize('n,r,p', [
    (2 ** 20, 16, 4),  # Former maxima overflow the backend maxmem argument.
    (2 ** 20, 8, 1),   # Individual parameters pass but memory is excessive.
    (2 ** 19, 8, 1),   # Memory exceeds the joint bound without integer overflow.
    (2 ** 18, 8, 4),   # Memory is bounded but combined CPU work is excessive.
])
def test_unlock_rejects_excessive_joint_scrypt_cost_before_deriving(tmp_path, monkeypatch, n, r, p):
    key = KeyFile(bytes(16), n, r, p, bytes(12), bytes(48))
    (tmp_path / crypto.KEY_FILE).write_text(key.dumps())

    def unexpected_scrypt(*args, **kwargs):
        pytest.fail('Unsafe key parameters reached scrypt')

    monkeypatch.setattr(crypto.hashlib, 'scrypt', unexpected_scrypt)
    with pytest.raises(EncryptionError, match='unsupported settings'):
        Vault(tmp_path).unlock('a valid passphrase')


def test_default_key_settings_round_trip_with_bounded_backend_memory(monkeypatch):
    pytest.importorskip('cryptography')
    calls = []

    def fake_scrypt(password, **kwargs):
        calls.append(kwargs)
        return bytes(32)

    monkeypatch.setattr(crypto.hashlib, 'scrypt', fake_scrypt)
    key = KeyFile.create('a valid passphrase', b'k' * 32)
    assert KeyFile.loads(key.dumps()).unwrap('a valid passphrase') == b'k' * 32
    assert len(calls) == 2
    for call in calls:
        assert (call['n'], call['r'], call['p']) == (2 ** 17, 8, 1)
        assert 128 * call['n'] * call['r'] < call['maxmem'] < 2 ** 31


def test_direct_key_derivation_also_rejects_excessive_cost(monkeypatch):
    def unexpected_scrypt(*args, **kwargs):
        pytest.fail('Unsafe explicit work factor reached scrypt')

    monkeypatch.setattr(crypto.hashlib, 'scrypt', unexpected_scrypt)
    with pytest.raises(EncryptionError, match='unsupported settings'):
        KeyFile.create('a valid passphrase', bytes(32), n=2 ** 20)
