"""A retained plaintext conflict must be visible in the shell and the app."""
import sys

import pytest

pytest.importorskip("cryptography")

from jotline import cli, store
from jotline.app import Jotline
from jotline.history import DISPLACED_PREFIX


def _encryption_race(tmp_path, monkeypatch):
    vault = store.Vault(tmp_path)
    vault.setup_encryption("correct horse", n=2**10)
    note = vault.new("Original note")
    vault.save(note)
    external = note.original.replace("Original note", "External private edit")
    publish = store.publish_new

    def publish_then_edit(directory, source, target):
        publish(directory, source, target)
        next(tmp_path.glob(f"{DISPLACED_PREFIX}*")).write_text(external)

    monkeypatch.setattr(store, "publish_new", publish_then_edit)
    return vault, note


def test_cli_encrypt_reports_retained_plaintext_filename(tmp_path, monkeypatch, capsys):
    _vault, note = _encryption_race(tmp_path, monkeypatch)
    monkeypatch.setenv("JOTLINE_PASSPHRASE", "correct horse")
    monkeypatch.setattr(sys, "argv", ["jotline", "--vault", str(tmp_path), "encrypt", note.id])
    cli.main()

    captured = capsys.readouterr()
    displaced = next(tmp_path.glob(f"{DISPLACED_PREFIX}*"))
    assert captured.out == note.id + "\n"
    assert "retained unencrypted" in captured.err and displaced.name in captured.err
    assert "External private edit" not in captured.err and "correct horse" not in captured.err


async def test_app_encrypt_notifies_about_retained_plaintext(tmp_path, monkeypatch):
    vault, note = _encryption_race(tmp_path, monkeypatch)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause()
        app.set_current_encryption(True)
        await pilot.pause()
        displaced = next(tmp_path.glob(f"{DISPLACED_PREFIX}*"))
        messages = [item.message for item in app._notifications]
        assert any("retained unencrypted" in message and displaced.name in message for message in messages)
        assert all("External private edit" not in message and "correct horse" not in message for message in messages)
