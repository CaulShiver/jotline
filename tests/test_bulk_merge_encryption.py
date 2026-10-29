"""Bulk merge must not silently decrypt or omit an encrypted source note."""
import zipfile

import pytest

pytest.importorskip("cryptography")

from jotline.app import Jotline
from jotline.store import Vault


@pytest.mark.parametrize("encrypted", [(True, True), (True, False), (False, True), (False, False)])
async def test_bulk_merge_preserves_encryption_and_originals(tmp_path, encrypted):
    vault = Vault(tmp_path)
    vault.setup_encryption("merge test passphrase", n=2 ** 10)
    sources = []
    for index, protected in enumerate(encrypted):
        body = f"confidential merge source {index}" if protected else f"public source {index}"
        note = vault.new(body)
        note.encrypted = protected
        vault.save(note)
        sources.append(note)

    app = Jotline(vault)
    async with app.run_test():
        app.run_bulk([note.id for note in sources], "merge")
        merged = app.current
        assert merged.id not in {note.id for note in sources}
        assert merged.body == "\n\n---\n\n".join(note.body for note in sources)
        assert merged.encrypted == any(encrypted)
        assert vault.read(merged.id).encrypted == any(encrypted)
        assert all(vault.read(note.id).body == note.body for note in sources)

        # Protection applies before the first write, including retained copies.
        secret = b"confidential merge source"
        for path in tmp_path.rglob("*.md"):
            assert secret not in path.read_bytes()
        with zipfile.ZipFile(vault.backup()) as backup:
            assert all(secret not in backup.read(name) for name in backup.namelist())

    vault.lock()
    assert vault.read(merged.id).locked == any(encrypted)
    vault.unlock("merge test passphrase")
    assert vault.read(merged.id).body == merged.body


@pytest.mark.parametrize("locked_first", [True, False])
async def test_bulk_merge_refuses_locked_sources_without_partial_output(tmp_path, locked_first):
    vault = Vault(tmp_path)
    vault.setup_encryption("merge test passphrase", n=2 ** 10)
    secret = vault.new("confidential locked source")
    secret.encrypted = True
    vault.save(secret)
    public = vault.new("public source")
    vault.save(public)
    vault.lock()
    ids = [secret.id, public.id] if locked_first else [public.id, secret.id]

    app = Jotline(vault)
    async with app.run_test():
        before = {note.id for note in vault.search()}
        current = app.current.id
        app.run_bulk(ids, "merge")
        assert {note.id for note in vault.search()} == before
        assert app.current.id == current
        assert vault.read(secret.id).locked
        assert vault.read(public.id).body == public.body
