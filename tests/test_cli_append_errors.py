"""CLI append/prepend line joining and plain-language error messages."""
from pathlib import Path
import subprocess
import sys

import pytest

from jotline.store import Vault


def run_cli(vault: Path, *args: str, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "jotline", "--vault", str(vault), *args],
        input=input,
        capture_output=True,
        check=False,
        timeout=30,
    )


def saved(vault: Vault, body: str):
    note = vault.new(body)
    vault.save(note)
    return note


def test_argument_text_goes_on_its_own_line(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "First thought #idea")
    assert run_cli(tmp_path, "append", note.id, "appended", "text").returncode == 0
    assert run_cli(tmp_path, "prepend", note.id, "prepended").returncode == 0
    reread = vault.read(note.id)
    assert reread.body == "prepended\nFirst thought #idea\nappended text"
    assert reread.tags == {"idea"}


@pytest.mark.parametrize("newline", ["\r\n", "\r"])
def test_added_line_break_matches_note_newline_style(tmp_path, newline):
    vault = Vault(tmp_path)
    note = saved(vault, f"one{newline}two")
    assert run_cli(tmp_path, "append", note.id, input=b"three").returncode == 0
    assert run_cli(tmp_path, "prepend", note.id, input=b"zero").returncode == 0
    assert vault.read(note.id).body == newline.join(["zero", "one", "two", "three"])


def test_existing_line_boundaries_are_not_doubled(tmp_path):
    vault = Vault(tmp_path)
    ends_with_newline = saved(vault, "body\n")
    assert run_cli(tmp_path, "append", ends_with_newline.id, "more").returncode == 0
    assert vault.read(ends_with_newline.id).body == "body\nmore"
    empty = saved(vault, "")
    assert run_cli(tmp_path, "append", empty.id, "only").returncode == 0
    assert vault.read(empty.id).body == "only"


def test_no_newline_joins_exactly(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "middle")
    assert run_cli(tmp_path, "append", "--no-newline", note.id, "end").returncode == 0
    assert run_cli(tmp_path, "prepend", "--no-newline", note.id, "start").returncode == 0
    assert vault.read(note.id).body == "startmiddleend"


def test_actions_keep_exact_append(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "target")
    vault.append_note(note.id, "tail", "default")
    assert vault.read(note.id).body == "targettail"


@pytest.mark.parametrize("command", [("append", "missing-note", "x"), ("export", "missing-note"),
                                     ("tag", "missing-note", "work")])
def test_missing_note_is_named_plainly(tmp_path, command):
    saved(Vault(tmp_path), "keep")
    result = run_cli(tmp_path, *command)
    assert result.returncode == 1
    assert result.stderr.decode() == "jotline: No note with ID or title missing-note; run jotline list to find IDs\n"


def test_missing_import_file_has_no_errno(tmp_path):
    missing = tmp_path / "nowhere.txt"
    result = run_cli(tmp_path / "vault", "import", str(missing))
    assert result.returncode == 1
    message = result.stderr.decode()
    assert "Errno" not in message and "nowhere.txt" in message


def test_invalid_utf8_input_is_explained(tmp_path):
    result = run_cli(tmp_path, "capture", input=b"\xff\xfe\x00bin")
    assert result.returncode == 1
    assert result.stderr.decode() == (
        "jotline: Piped input is not valid UTF-8 text (bad byte at position 0); pass --encoding NAME "
        "if it uses another encoding, or --replace-invalid to substitute bad bytes\n")
    assert not list(tmp_path.glob("*.md"))


def test_invalid_utf8_import_names_the_file(tmp_path):
    source = tmp_path / "latin1.txt"
    source.write_bytes(b"caf\xe9")
    result = run_cli(tmp_path / "vault", "import", str(source))
    assert result.returncode == 1
    message = result.stderr.decode()
    assert "latin1.txt is not valid UTF-8 text" in message and "codec" not in message
