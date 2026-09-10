"""CLI regressions for bounded local vault inputs and terminal-safe output."""
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
import subprocess
import sys

import pytest

from jotline import cli as cli_module
from jotline.settings import Settings
from jotline.store import Vault


def run_cli(vault: Path, *args: str, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "jotline", "--vault", str(vault), *args],
        input=input,
        capture_output=True,
        check=False,
    )


def test_daily_captures_are_atomic_across_processes(tmp_path):
    def capture(text: str):
        return run_cli(tmp_path, "capture", "--daily", text)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(capture, ("one", "two")))

    assert first.returncode == second.returncode == 0, (first.stderr, second.stderr)
    note_id = first.stdout.decode().strip()
    assert note_id == second.stdout.decode().strip()
    body = Vault(tmp_path).read(note_id).body
    assert "one" in body and "two" in body


def test_capture_and_export_keep_crlf_when_piped(tmp_path):
    captured = run_cli(tmp_path, "capture", input=b"first\r\nsecond\r\n")
    assert captured.returncode == 0, captured.stderr.decode()
    exported = run_cli(tmp_path, "export", captured.stdout.decode().strip())
    assert exported.stdout == b"first\r\nsecond\r\n"


def test_list_and_doctor_escape_controls_in_malformed_filenames(tmp_path):
    bad = tmp_path / "bad\x1b[31m.md"
    bad.write_text("---\njotline: 1\nstarred: no-json\n---\n")

    listing = run_cli(tmp_path, "list")
    assert listing.returncode == 0
    assert b"\x1b" not in listing.stderr
    assert b"\\x1b" in listing.stderr

    doctor = run_cli(tmp_path, "doctor")
    assert doctor.returncode == 1
    assert b"Warnings: 1" in doctor.stdout
    assert b"\x1b" not in doctor.stderr
    assert b"\\x1b" in doctor.stderr


def test_import_copies_regular_utf8_file_without_changing_source(tmp_path):
    vault_path = tmp_path / "vault"
    source = tmp_path / "outside.md"
    source.write_bytes(b"# Imported\r\n\r\nOriginal source\r\n")
    Vault(vault_path)
    Settings(default_collection="projects").save(vault_path / ".jotline-settings.json")

    imported = run_cli(vault_path, "import", str(source))
    assert imported.returncode == 0, imported.stderr.decode()
    assert source.read_bytes() == b"# Imported\r\n\r\nOriginal source\r\n"
    note = Vault(vault_path).read(imported.stdout.decode().strip())
    assert note.body == source.read_bytes().decode("utf-8")
    assert note.collection == "projects"


def test_import_rejects_symlinked_source(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("private source")
    linked = tmp_path / "linked.md"
    linked.symlink_to(source)

    imported = run_cli(tmp_path / "vault", "import", str(linked))

    assert imported.returncode == 1
    assert b"Too many levels of symbolic links" in imported.stderr


def test_doctor_succeeds_when_clean_and_fails_for_invalid_settings(tmp_path):
    healthy = run_cli(tmp_path, "doctor")
    assert healthy.returncode == 0
    assert b"Readable notes: 0" in healthy.stdout
    assert b"Warnings: 0" in healthy.stdout

    (tmp_path / ".jotline-settings.json").write_text("[]")
    unhealthy = run_cli(tmp_path, "doctor")
    assert unhealthy.returncode == 1
    assert b"Warnings: 1" in unhealthy.stdout
    assert b"settings: Could not load settings" in unhealthy.stderr


class InteractiveOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_export_refuses_terminal_controls_to_tty_without_raw(tmp_path, monkeypatch, capsys):
    vault = Vault(tmp_path)
    note = vault.new("safe\x1b]52;c;payload\a")
    vault.save(note)
    output = InteractiveOutput()
    monkeypatch.setattr(cli_module.sys, "stdout", output)
    monkeypatch.setattr(cli_module.sys, "argv", ["jotline", "--vault", str(tmp_path), "export", note.id])

    with pytest.raises(SystemExit) as exit_code:
        cli_module.main()

    assert exit_code.value.code == 1
    assert output.getvalue() == ""
    assert "Refusing to print terminal controls" in capsys.readouterr().err

    monkeypatch.setattr(cli_module.sys, "argv", ["jotline", "--vault", str(tmp_path), "export", note.id, "--raw"])
    cli_module.main()
    assert output.getvalue() == note.body

    redirected = run_cli(tmp_path, "export", note.id)
    assert redirected.returncode == 0
    assert redirected.stdout == note.body.encode()
