import hashlib
import json

import pytest

from jotline.outline_state import read_state, write_state
from jotline.store import Vault

pytest.importorskip('cryptography')


def test_encrypt_removes_plaintext_outline_fingerprint(tmp_path):
    vault = Vault(tmp_path)
    vault.setup_encryption('synthetic passphrase', n=1024)
    note = vault.new('- yes')
    vault.save(note)
    path = tmp_path / '.jotline-outline.json'
    data = {'revision': hashlib.sha256(note.body.encode()).hexdigest(), 'folded': [0]}
    write_state(path, note.id, data)
    assert note.id in json.loads(path.read_text())
    vault.set_encrypted(note.id, 'default', True)
    assert note.id not in json.loads(path.read_text())


def test_stale_plaintext_window_cannot_recreate_encrypted_fingerprint(tmp_path):
    vault = Vault(tmp_path)
    vault.setup_encryption('synthetic passphrase', n=1024)
    note = vault.new('- yes')
    note.encrypted = True
    vault.save(note)
    path = tmp_path / '.jotline-outline.json'
    write_state(path, note.id, {'revision': hashlib.sha256(note.body.encode()).hexdigest()})
    assert not path.exists() or note.id not in json.loads(path.read_text())


def test_deeply_nested_view_state_is_ignored_and_repaired(tmp_path):
    path = tmp_path / '.jotline-outline.json'
    path.write_text('[' * 20000 + ']' * 20000)
    assert read_state(path, 'note', '- text') == {}
    write_state(path, 'note', {'revision': 'fresh'})
    assert json.loads(path.read_text()) == {'note': {'revision': 'fresh'}}


def test_reencrypting_legacy_note_clears_state_without_rewriting_note(tmp_path):
    vault = Vault(tmp_path)
    vault.setup_encryption('synthetic passphrase', n=1024)
    note = vault.new('- yes')
    note.encrypted = True
    vault.save(note)
    path = tmp_path / '.jotline-outline.json'
    path.write_text(json.dumps({note.id: {'revision': hashlib.sha256(note.body.encode()).hexdigest()},
                               'other': {'revision': 'retained'}}))
    before = vault.file(note.id).read_bytes()
    _, changed = vault.set_encrypted(note.id, 'default', True)
    assert not changed
    assert json.loads(path.read_text()) == {'other': {'revision': 'retained'}}
    assert vault.file(note.id).read_bytes() == before


async def test_encrypted_outliner_never_persists_plaintext_view_state(tmp_path):
    from jotline.app import Jotline
    vault = Vault(tmp_path)
    vault.setup_encryption('synthetic passphrase', n=1024)
    note = vault.new('- yes\n  - private child')
    note.encrypted = True
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 32)) as pilot:
        app.action_outliner()
        await pilot.pause()
        app.screen.action_fold()
        app.screen.action_save()
        path = tmp_path / '.jotline-outline.json'
        assert not path.exists() or note.id not in json.loads(path.read_text())
        assert vault.read(note.id).body == note.body


def test_outline_state_budget_matches_the_written_json(tmp_path):
    from jotline.limits import MAX_SETTINGS_BYTES
    path = tmp_path / '.jotline-outline.json'
    write_state(path, 'note', {'revision': 'synthetic', 'folded': list(range(30000))})
    assert path.stat().st_size <= MAX_SETTINGS_BYTES
    assert json.loads(path.read_text()) == {}


@pytest.mark.parametrize('corruption', ['invalid', 'nested', 'oversized'])
def test_encrypt_clears_fingerprints_from_corrupt_regular_state(tmp_path, corruption):
    vault = Vault(tmp_path)
    vault.setup_encryption('synthetic passphrase', n=1024)
    note = vault.new('- yes')
    vault.save(note)
    path = tmp_path / '.jotline-outline.json'
    fingerprint = hashlib.sha256(note.body.encode()).hexdigest()
    state = json.dumps({note.id: {'revision': fingerprint}})
    if corruption == 'invalid':
        state += 'broken'
    elif corruption == 'nested':
        state = state[:-1] + ', "other": ' + '[' * 20000 + ']' * 20000 + '}'
    else:
        state += ' ' * (300 * 1024)
    path.write_text(state)
    vault.set_encrypted(note.id, 'default', True)
    assert fingerprint not in path.read_text()
    assert json.loads(path.read_text()) == {}
