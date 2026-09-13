"""Opt-in note encryption: storage, history, backups, the shell and the app."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

import pytest

pytest.importorskip("cryptography")

from textual.widgets import Input

from jotline.app import Jotline, TextPrompt
from jotline.crypto import EncryptionError, KeyFile
from jotline.importing import preview_import
from jotline.store import Vault

PASSPHRASE = "correct horse"
FAST = 2 ** 10  # A light work factor keeps tests quick; real setups use the default.


def encrypted_vault(path: Path) -> Vault:
    vault = Vault(path)
    vault.setup_encryption(PASSPHRASE, n=FAST)
    return vault


def encrypted_note(vault: Vault, body: str):
    note = vault.new(body)
    note.encrypted = True
    vault.save(note)
    return note


def test_encrypted_text_never_stays_on_disk_in_notes_history_or_new_backups(tmp_path):
    vault = encrypted_vault(tmp_path)
    note = vault.new("Client Sam\nbench 100 kg #athlete")
    vault.save(note)
    note.body += "\nupdated"
    vault.save(note)
    note.encrypted = True
    vault.save(note)

    raw = (tmp_path / f"{note.id}.md").read_text()
    assert "Client Sam" not in raw and "encrypted: true" in raw
    revisions = list((tmp_path / ".jotline-history" / note.id).iterdir())
    assert revisions and all("Client Sam" not in revision.read_text() for revision in revisions)
    with zipfile.ZipFile(vault.backup()) as archive:
        assert ".jotline-key.json" in archive.namelist()
        assert b"Client Sam" not in archive.read(f"{note.id}.md")

    vault.lock()
    locked = vault.read(note.id)
    assert locked.locked and locked.body == "" and locked.title == "Encrypted note (locked)"
    assert not locked.tags and not vault.search("Sam")
    vault.unlock(PASSPHRASE)
    assert vault.read(note.id).body == "Client Sam\nbench 100 kg #athlete\nupdated"
    assert [found.id for found in vault.search("#athlete")] == [note.id]


def test_decrypting_restores_the_plain_note_format(tmp_path):
    vault = encrypted_vault(tmp_path)
    note = encrypted_note(vault, "secret")
    note.encrypted = False
    vault.save(note)
    raw = (tmp_path / f"{note.id}.md").read_text()
    assert raw.endswith("\n---\nsecret") and "encrypted" not in raw


def test_locked_notes_can_be_moved_but_their_text_cannot_change(tmp_path):
    vault = encrypted_vault(tmp_path)
    note = encrypted_note(vault, "secret")
    vault.lock()
    locked = vault.read(note.id)
    locked.collection = "archive"
    vault.save(locked)
    assert vault.read(note.id).collection == "archive"

    changed = vault.read(note.id)
    changed.body = "overwritten"
    with pytest.raises(ValueError, match="unlock"):
        vault.save(changed)
    with pytest.raises(ValueError, match="unlock"):
        vault.recovery(vault.read(note.id))
    with pytest.raises(ValueError, match="unlock"):
        vault.append_note(note.id, "more", "default")
    vault.unlock(PASSPHRASE)
    assert vault.read(note.id).body == "secret"


def test_wrong_passphrases_tampering_and_swapped_files_are_refused(tmp_path):
    vault = encrypted_vault(tmp_path)
    with pytest.raises(EncryptionError, match="Wrong passphrase"):
        Vault(tmp_path).unlock("not the passphrase")
    one = encrypted_note(vault, "one")
    two = encrypted_note(vault, "two")
    (tmp_path / f"{two.id}.md").write_text((tmp_path / f"{one.id}.md").read_text())
    fresh = Vault(tmp_path)
    fresh.unlock(PASSPHRASE)
    with pytest.raises(EncryptionError, match="could not be decrypted"):
        fresh.read(two.id)

    raw = (tmp_path / f"{one.id}.md").read_text()
    start = raw.index("jotline-encrypted: 1\n") + len("jotline-encrypted: 1\n")
    (tmp_path / f"{one.id}.md").write_text(raw[:start] + ("B" if raw[start] == "A" else "A") + raw[start + 1:])
    with pytest.raises(EncryptionError, match="could not be decrypted"):
        fresh.read(one.id)
    fresh.notes()
    assert any("could not be decrypted" in warning for warning in fresh.warnings)


def test_passphrase_changes_rewrap_the_key_without_touching_notes(tmp_path):
    vault = encrypted_vault(tmp_path)
    note = encrypted_note(vault, "secret")
    before = (tmp_path / f"{note.id}.md").read_bytes()
    vault.change_passphrase(PASSPHRASE, "battery staple")
    assert (tmp_path / f"{note.id}.md").read_bytes() == before
    fresh = Vault(tmp_path)
    with pytest.raises(EncryptionError, match="Wrong passphrase"):
        fresh.unlock(PASSPHRASE)
    fresh.unlock("battery staple")
    assert fresh.read(note.id).body == "secret"
    with pytest.raises(EncryptionError, match="at least 8"):
        vault.change_passphrase("battery staple", "short")
    with pytest.raises(ValueError, match="already set up"):
        vault.setup_encryption("another passphrase", n=FAST)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_key_file_is_private(tmp_path):
    encrypted_vault(tmp_path)
    assert stat.S_IMODE((tmp_path / ".jotline-key.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("change", [{"n": 2 ** 30}, {"n": 1000}, {"r": 0}, {"salt": "!!"}, {"wrapped": ""},
                                    {"cipher": "none"}, {"jotline_key": 2}])
def test_damaged_or_hostile_key_files_are_refused(tmp_path, change):
    encrypted_vault(tmp_path)
    path = tmp_path / ".jotline-key.json"
    data = json.loads(path.read_text())
    data.update(change)
    path.write_text(json.dumps(data))
    with pytest.raises(EncryptionError):
        Vault(tmp_path).unlock(PASSPHRASE)


def test_missing_library_explains_how_to_install_it(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", None)
    with pytest.raises(EncryptionError, match=r"jotline\[encryption\]"):
        KeyFile.create(PASSPHRASE, os.urandom(32), n=FAST)


def test_imports_skip_encrypted_note_files(tmp_path):
    vault = encrypted_vault(tmp_path / "vault")
    note = encrypted_note(vault, "secret")
    source = tmp_path / "source"
    source.mkdir()
    (source / "copied.md").write_bytes((vault.path / f"{note.id}.md").read_bytes())
    plan = preview_import(Vault(tmp_path / "other"), source)
    assert plan.items == []
    assert any("Encrypted Jotline note skipped" in warning for warning in plan.warnings)


def run_cli(vault: Path, *args, passphrase: str | None = None) -> subprocess.CompletedProcess[bytes]:
    env = {name: value for name, value in os.environ.items() if name != "JOTLINE_PASSPHRASE"}
    if passphrase:
        env["JOTLINE_PASSPHRASE"] = passphrase
    # No controlling terminal, so a missing passphrase can never wait for typing.
    detached = {} if os.name == "nt" else {"start_new_session": True}
    return subprocess.run([sys.executable, "-m", "jotline", "--vault", os.fsencode(vault), *args],
                          stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=60, env=env,
                          **detached)


def test_cli_sets_up_encrypts_and_reads_with_a_passphrase(tmp_path):
    setup = run_cli(tmp_path, "encryption", "setup", passphrase=PASSPHRASE)
    assert setup.returncode == 0, setup.stderr
    assert "no way to recover" in setup.stderr.decode()
    note_id = run_cli(tmp_path, "capture", "Sam bench notes").stdout.decode().strip()
    encrypt = run_cli(tmp_path, "encrypt", note_id, passphrase=PASSPHRASE)
    assert encrypt.returncode == 0, encrypt.stderr
    assert "Sam" not in (tmp_path / f"{note_id}.md").read_text()

    assert run_cli(tmp_path, "export", note_id, passphrase=PASSPHRASE).stdout == b"Sam bench notes"
    listing = run_cli(tmp_path, "list").stdout.decode()
    assert "Encrypted note (locked)" in listing and "Sam" not in listing
    locked = run_cli(tmp_path, "export", note_id)
    assert locked.returncode == 1
    assert "set JOTLINE_PASSPHRASE" in locked.stderr.decode()
    wrong = run_cli(tmp_path, "export", note_id, passphrase="not the passphrase")
    assert wrong.returncode == 1
    assert "Wrong passphrase" in wrong.stderr.decode()

    assert run_cli(tmp_path, "append", note_id, "- [ ] call Sam", passphrase=PASSPHRASE).returncode == 0
    hidden = run_cli(tmp_path, "tasks")
    assert hidden.stdout == b"" and "pass --unlock" in hidden.stderr.decode()
    assert b"call Sam" in run_cli(tmp_path, "--unlock", "tasks", passphrase=PASSPHRASE).stdout
    assert run_cli(tmp_path, "encryption", "status").stdout == b"Encryption is set up; 1 encrypted note\n"

    assert run_cli(tmp_path, "decrypt", note_id, passphrase=PASSPHRASE).returncode == 0
    assert "Sam bench notes" in (tmp_path / f"{note_id}.md").read_text()


async def test_app_encrypts_locks_and_unlocks(tmp_path):
    vault = encrypted_vault(tmp_path)
    note = vault.new("Sam secret")
    vault.save(note)
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.load_id(note.id)
        app.command("encrypt")
        await pilot.pause()
        assert isinstance(app.screen, TextPrompt)
        app.screen.query_one(Input).value = PASSPHRASE
        await pilot.press("enter")
        await pilot.pause()
        assert app.current.encrypted
        assert "Sam" not in (tmp_path / f"{note.id}.md").read_text()

        app.command("lock")
        await pilot.pause()
        assert app.current.id != note.id
        assert "Encrypted note (locked)" in str(app.query_one("#notes").get_option_at_index(0).prompt)

        app.load_id(note.id)
        await pilot.pause()
        assert isinstance(app.screen, TextPrompt)
        app.screen.query_one(Input).value = PASSPHRASE
        await pilot.press("enter")
        await pilot.pause()
        assert app.current.id == note.id and app.current.body == "Sam secret"
