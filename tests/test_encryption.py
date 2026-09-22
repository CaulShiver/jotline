"""Opt-in note encryption: storage, history, backups, the shell and the app."""
import base64
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

from jotline.actions import run_action
from jotline.app import Jotline, TextPrompt
from jotline.crypto import SCRYPT_N, EncryptionError, KeyFile
from jotline.importing import preview_import
from jotline.store import Vault, wiki_link

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


def test_an_undecryptable_note_stays_listed_and_is_reported(tmp_path):
    vault = encrypted_vault(tmp_path)
    one = encrypted_note(vault, "one")
    two = encrypted_note(vault, "two")
    # A sync conflict settled the wrong way: two's file holds text sealed under one's ID.
    (tmp_path / f"{two.id}.md").write_text((tmp_path / f"{one.id}.md").read_text())
    fresh = Vault(tmp_path)
    fresh.unlock(PASSPHRASE)
    listed = {note.id: note for note in fresh.notes()}
    assert listed[one.id].body == "one"
    assert listed[two.id].locked and listed[two.id].title == "Encrypted note (locked)"
    assert [warning for warning in fresh.warnings if "could not be decrypted" in warning] == [
        f"{two.id}.md: Encrypted note could not be decrypted; the file is damaged or was encrypted "
        "with another vault's key"]
    # It is not cached, so the next scan reports it again rather than forgetting it.
    assert {note.id for note in fresh.notes()} == {one.id, two.id}
    assert sum(two.id in warning for warning in fresh.warnings) == 1


def test_passphrase_changes_rewrap_the_key_without_touching_notes(tmp_path):
    vault = encrypted_vault(tmp_path)
    note = encrypted_note(vault, "secret")
    before = (tmp_path / f"{note.id}.md").read_bytes()
    vault.change_passphrase(PASSPHRASE, "battery staple", n=FAST)
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


def test_passphrase_changes_rewrap_at_the_current_work_factor(tmp_path):
    vault = encrypted_vault(tmp_path)
    path = tmp_path / ".jotline-key.json"
    assert json.loads(path.read_text())["n"] == FAST
    vault.change_passphrase(PASSPHRASE, "battery staple")
    assert json.loads(path.read_text())["n"] == SCRYPT_N
    Vault(tmp_path).unlock("battery staple")


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_key_file_is_private(tmp_path):
    encrypted_vault(tmp_path)
    assert stat.S_IMODE((tmp_path / ".jotline-key.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("change", [{"n": 2 ** 30}, {"n": 1000}, {"r": 0}, {"salt": "!!"}, {"wrapped": ""},
                                    {"cipher": "none"}, {"jotline_key": 2}, {"checksum": "not this wrapping"}])
def test_damaged_or_hostile_key_files_are_refused(tmp_path, change):
    encrypted_vault(tmp_path)
    path = tmp_path / ".jotline-key.json"
    data = json.loads(path.read_text())
    data.update(change)
    path.write_text(json.dumps(data))
    with pytest.raises(EncryptionError):
        Vault(tmp_path).unlock(PASSPHRASE)


def test_a_damaged_key_file_is_told_from_a_wrong_passphrase(tmp_path):
    encrypted_vault(tmp_path)
    path = tmp_path / ".jotline-key.json"
    data = json.loads(path.read_text())
    wrapped = bytearray(base64.b64decode(data["wrapped"]))
    wrapped[0] ^= 1  # One flipped bit, as a bad sector or a botched sync merge leaves behind
    data["wrapped"] = base64.b64encode(bytes(wrapped)).decode()
    path.write_text(json.dumps(data))
    with pytest.raises(EncryptionError, match="damaged"):
        Vault(tmp_path).unlock(PASSPHRASE)


def test_a_key_file_without_a_checksum_still_unwraps(tmp_path):
    # Written by 0.9.8: the same fields, minus the ID. It must keep working as it is.
    vault = encrypted_vault(tmp_path)
    note = encrypted_note(vault, "secret")
    path = tmp_path / ".jotline-key.json"
    data = json.loads(path.read_text())
    del data["checksum"]
    path.write_text(json.dumps(data))
    fresh = Vault(tmp_path)
    fresh.unlock(PASSPHRASE)
    assert fresh.read(note.id).body == "secret"
    assert "checksum" not in json.loads(path.read_text())
    fresh.change_passphrase(PASSPHRASE, "battery staple", n=FAST)
    assert json.loads(path.read_text())["checksum"]


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
    raw = (tmp_path / f"{note_id}.md").read_text()
    # Short words can occur by chance in valid base64 ciphertext.
    assert "Sam bench notes" not in raw and "encrypted: true" in raw

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
        raw = (tmp_path / f"{note.id}.md").read_text()
        assert "Sam secret" not in raw and "encrypted: true" in raw

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


def plaintext_in_vault(path: Path, secret: str) -> list[str]:
    """Every file under the vault, archives included, still holding the secret."""
    found = []
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        raw = item.read_bytes()
        if secret.encode() in raw:
            found.append(str(item.relative_to(path)))
        if item.suffix == ".zip":
            with zipfile.ZipFile(item) as archive:
                found += [f"{item.name}::{member}" for member in archive.namelist()
                          if secret.encode() in archive.read(member)]
    return found


async def test_extracting_a_selection_keeps_it_encrypted(tmp_path):
    # A new note inherits nothing, so the selection used to be written to disk
    # in the clear, snapshotted into history and archived in the next backup.
    vault = encrypted_vault(tmp_path)
    note = encrypted_note(vault, "Sam therapy\nSECRETLINE dosage 200mg\n")
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        app.vault.unlock(PASSPHRASE)
        app.load_id(note.id)
        await pilot.pause()
        editor = app.editor()
        editor.move_cursor((1, 0))
        editor.move_cursor((1, 10), select=True)
        assert editor.selected_text == "SECRETLINE"
        app.action_extract_note()
        await pilot.pause()
        assert plaintext_in_vault(tmp_path, "SECRETLINE") == []


async def test_an_encrypted_note_cannot_be_saved_as_a_template(tmp_path):
    # Templates are stored unencrypted and the daily backup archives them.
    vault = encrypted_vault(tmp_path)
    note = encrypted_note(vault, "Sam therapy\nSECRETLINE dosage 200mg\n")
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 32)) as pilot:
        app.vault.unlock(PASSPHRASE)
        app.load_id(note.id)
        await pilot.pause()
        app.save_template("my-template")
        await pilot.pause()
        assert plaintext_in_vault(tmp_path, "SECRETLINE") == []


def test_an_action_refuses_to_append_an_encrypted_note_to_another(tmp_path):
    vault = encrypted_vault(tmp_path)
    vault.unlock(PASSPHRASE)
    note = encrypted_note(vault, "Sam therapy\nSECRETLINE dosage 200mg\n")
    target = vault.new("Log\n")
    vault.save(target)
    with pytest.raises(ValueError, match="unencrypted"):
        run_action(vault, vault.read(note.id), [{"type": "append", "value": target.id}])
    assert plaintext_in_vault(tmp_path, "SECRETLINE") == []


def test_a_link_to_an_encrypted_note_carries_no_label(tmp_path):
    # The label is the first line of the decrypted body, and the note being
    # linked from is usually not encrypted.
    vault = encrypted_vault(tmp_path)
    vault.unlock(PASSPHRASE)
    note = encrypted_note(vault, "SECRETLINE Sam HIV status\n")
    assert wiki_link(vault.read(note.id)) == f"[[{note.id}]]"
    assert wiki_link(vault.new("Ordinary note")).endswith("|Ordinary note]]")
