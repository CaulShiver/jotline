"""What the shell says: empty results, a missing vault, usage errors and readable output at a terminal."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jotline import cli
from jotline.export import ExportError, export_bytes
from jotline.store import Vault

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shells")


def run_cli(vault: Path, *args, input: bytes | None = None, env=None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "jotline", "--vault", os.fsencode(vault), *args],
                          input=input, capture_output=True, check=False, timeout=30, env=env,
                          start_new_session=True)


def text(result) -> tuple[str, str]:
    return result.stdout.decode(), result.stderr.decode()


def saved(vault: Vault, body: str, **fields):
    note = vault.new(body, workspace=fields.pop("workspace", "default"))
    for name, value in fields.items():
        setattr(note, name, value)
    vault.save(note)
    return note


def main(monkeypatch, *argv, tty=False) -> int:
    """Run the CLI in-process; with tty, stdout claims to be a terminal."""
    monkeypatch.setattr(sys, "argv", ["jotline", *map(str, argv)])
    if tty:
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    try:
        cli.main()
    except SystemExit as stop:
        return stop.code or 0
    return 0


# A vault that does not exist yet ------------------------------------------

def test_read_commands_on_a_missing_vault_are_empty_and_create_nothing(tmp_path):
    missing = tmp_path / "notes"
    for command in ("list", "tasks", "tags", "recoveries", "backups"):
        result = run_cli(missing, command, "--json")
        assert result.returncode == 0, result.stderr
        assert result.stdout == b"[]\n"
    assert run_cli(missing, "list").stdout == b""
    stats = json.loads(run_cli(missing, "stats", "--json").stdout)
    assert stats == {"workspace": "default", "notes": 0, "inbox": 0, "inbox_captures": 0, "daily_logs": 0,
                     "open_tasks": 0, "tagged": 0, "starred": 0}
    assert run_cli(missing, "workspaces").stdout == b"default *\n"
    doctor = run_cli(missing, "doctor")
    assert doctor.returncode == 0
    assert text(doctor)[0] == f"No vault yet at {missing}; it is created on first capture or launch\n"
    report = json.loads(run_cli(missing, "doctor", "--json").stdout)
    assert report["vault"] == {"path": str(missing), "exists": False} and report["warnings"] == []
    linked = run_cli(missing, "backlinks", "abcd")
    assert linked.returncode == 1 and "there is no vault yet" in text(linked)[1]
    assert not missing.exists()
    assert run_cli(missing, "capture", "first").returncode == 0 and missing.is_dir()


def test_a_missing_vault_hint_goes_to_stderr_at_a_terminal(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "notes"
    assert main(monkeypatch, "--vault", missing, "list", tty=True) == 0
    out, err = capsys.readouterr()
    assert out == "" and err == f"No vault yet at {missing}; it is created on first capture or launch\n"


# Capture output -----------------------------------------------------------

def test_capture_confirms_at_a_terminal_and_prints_the_id_when_piped(tmp_path, monkeypatch, capsys):
    assert main(monkeypatch, "--vault", tmp_path, "capture", "Buy", "milk", tty=True) == 0
    note = Vault(tmp_path).notes()[0]
    assert capsys.readouterr().out == f"Saved to inbox: Buy milk ({note.id[:8]})\n"
    assert main(monkeypatch, "--vault", tmp_path, "capture", "--daily", "--date", "2026-10-01", "ran",
                tty=True) == 0
    assert capsys.readouterr().out == "Added to daily log 2026-10-01\n"
    piped = run_cli(tmp_path, "capture", "plain")
    assert len(piped.stdout.strip()) == 32 and piped.stdout.strip().isalnum()


# open, search -------------------------------------------------------------

def test_open_falls_back_to_one_clear_fuzzy_match(tmp_path, monkeypatch, capsys):
    vault = Vault(tmp_path)
    venue = saved(vault, "Venue for the party")
    saved(vault, "Buy milk")
    saved(vault, "Milk prices")
    saved(vault, "Venue elsewhere", workspace="work")
    opened = []
    monkeypatch.setitem(cli.COMMANDS, "open", lambda run: opened.append(run.args.id))
    assert main(monkeypatch, "--vault", tmp_path, "open", "venue party") == 0
    assert opened == [venue.id]

    assert main(monkeypatch, "--vault", tmp_path, "open", "milk") == 1
    err = capsys.readouterr().err
    assert "Buy milk" in err and "Milk prices" in err
    assert "milk matches several titles; run jotline open with one of these IDs" in err
    assert main(monkeypatch, "--vault", tmp_path, "open", "zzz") == 1
    assert "No note with ID or title zzz" in capsys.readouterr().err
    assert opened == [venue.id]


def test_fuzzy_matching_is_only_for_open(tmp_path):
    saved(Vault(tmp_path), "Venue for the party")
    result = run_cli(tmp_path, "export", "venue party")
    assert result.returncode == 1 and "No note with ID or title" in text(result)[1]


def test_search_is_list(tmp_path):
    note = saved(Vault(tmp_path), "Venue for the party")
    assert run_cli(tmp_path, "search", "venue").stdout == run_cli(tmp_path, "list", "venue").stdout
    assert note.id in text(run_cli(tmp_path, "search", "venue", "--json"))[0]


# Empty results ------------------------------------------------------------

def test_empty_results_say_so_only_at_a_terminal(tmp_path, monkeypatch, capsys):
    saved(Vault(tmp_path), "plain")
    expected = {("list", "nothing"): "No notes match nothing\n",
                ("tasks",): "No open tasks\n",
                ("tags",): "No tags in workspace default yet\n",
                ("actions",): "No local actions yet; see docs/actions.md\n"}
    for command, message in expected.items():
        assert main(monkeypatch, "--vault", tmp_path, *command, tty=True) == 0
        assert capsys.readouterr() == ("", message)
    for command in expected:
        result = run_cli(tmp_path, *command)
        assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""


def test_run_without_actions_points_at_the_docs(tmp_path):
    note = saved(Vault(tmp_path), "plain")
    result = run_cli(tmp_path, "run", "nope", note.id)
    assert result.returncode == 1
    assert text(result)[1] == "jotline: No local actions yet; see docs/actions.md to add one\n"
    (tmp_path / ".jotline-settings.json").write_text(json.dumps({"actions": {"send": [{"type": "export"}]}}))
    assert "use jotline actions" in text(run_cli(tmp_path, "run", "nope", note.id))[1]


# Global options -----------------------------------------------------------

def test_global_options_work_after_the_command(tmp_path):
    vault = Vault(tmp_path / "real")
    note = saved(vault, "Work plan", workspace="work")
    result = subprocess.run([sys.executable, "-m", "jotline", "list", "--vault", str(vault.path),
                             "--workspace", "work"], capture_output=True, check=False, timeout=30)
    assert result.returncode == 0 and note.id.encode() in result.stdout
    # A value given after the command wins over one before it.
    later = run_cli(tmp_path / "elsewhere", "list", "--vault", str(vault.path), "--workspace", "work")
    assert note.id.encode() in later.stdout


def test_a_mistyped_workspace_is_refused(tmp_path):
    vault = Vault(tmp_path)
    saved(vault, "Work plan", workspace="work")
    listed = run_cli(tmp_path, "--workspace", "wrok", "list")
    assert listed.returncode == 1
    assert text(listed)[1] == "jotline: No workspace named wrok; run jotline workspaces\n"
    captured = run_cli(tmp_path, "capture", "x", "--workspace", "wrok")
    assert captured.returncode == 1 and "pass --new-workspace" in text(captured)[1]
    assert vault.workspaces() == {"default", "work"}
    assert run_cli(tmp_path, "--workspace", "work", "list").returncode == 0
    assert run_cli(tmp_path, "--workspace", "default", "list").returncode == 0
    assert run_cli(tmp_path, "--workspace", "side", "--new-workspace", "capture", "x").returncode == 0
    assert vault.workspaces() == {"default", "side", "work"}
    # A workspace created in the app exists before it has notes.
    (tmp_path / ".jotline-settings.json").write_text(json.dumps({"workspace_names": ["default", "empty"]}))
    assert run_cli(tmp_path, "--workspace", "empty", "capture", "x").returncode == 0
    # The default workspace is always there, even before the vault is.
    assert run_cli(tmp_path / "new", "--workspace", "default", "list").returncode == 0


def test_a_vault_that_is_a_file_says_so(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("not a vault")
    for command in ("capture", "list"):
        result = run_cli(path, command, "x")
        assert result.returncode == 1
        assert text(result)[1] == f"jotline: {path} is a file, not a vault folder\n"


def test_help_groups_commands_and_gives_examples():
    result = subprocess.run([sys.executable, "-m", "jotline", "--help"], capture_output=True, text=True,
                            check=False, timeout=30)
    for heading in ("Capture", "Find", "Tasks", "Notes", "Export & import", "Vault care", "Setup", "examples:"):
        assert heading in result.stdout
    capture = subprocess.run([sys.executable, "-m", "jotline", "capture", "--help"], capture_output=True,
                             text=True, check=False, timeout=30)
    assert "Save text as a new note" in capture.stdout and "Text to save" in capture.stdout


def test_usage_errors_show_the_commands_own_usage(tmp_path):
    for args, usage in ((("capture", "--date", "today", "x"), "usage: jotline capture"),
                        (("list", "--bogus\x1b[31m"), "usage: jotline list")):
        result = run_cli(tmp_path, *args)
        err = text(result)[1]
        assert result.returncode == 2 and err.startswith(usage)
        assert "export" not in err.split("error:")[0]
        assert "\x1b" not in err


# Import -------------------------------------------------------------------

def test_import_preview_prints_real_columns_and_warnings_alone_exit_zero(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "good.txt").write_text("Good\tnote")
    (source / "bad.txt").write_bytes(b"\xff\xfe broken")
    vault = tmp_path / "vault"
    preview = run_cli(vault, "import", str(source), "--preview")
    rows = [line.split("\t") for line in text(preview)[0].splitlines() if line.startswith("import")]
    assert rows == [["import", "good.txt", "inbox", "Good\\tnote"]]
    applied = run_cli(vault, "import", str(source), "--apply")
    assert applied.returncode == 0, applied.stderr
    assert "bad.txt" in text(applied)[1] and "Imported 1" in text(applied)[0]

    (source / "good.txt").unlink()
    failed = run_cli(tmp_path / "other", "import", str(source), "--apply")
    assert failed.returncode == 1 and "Imported 0" in text(failed)[0]


# Encryption, export and settings ------------------------------------------

def test_a_wrong_passphrase_only_fails_commands_that_need_it(tmp_path):
    pytest.importorskip("cryptography")
    vault = Vault(tmp_path)
    vault.setup_encryption("correct horse", n=2 ** 10)
    plain = saved(vault, "Plain note")
    locked = saved(vault, "Secret", encrypted=True)
    env = {**os.environ, "JOTLINE_PASSPHRASE": "not it"}
    listed = run_cli(tmp_path, "list", env=env)
    assert listed.returncode == 0 and plain.id in text(listed)[0]
    assert "JOTLINE_PASSPHRASE did not unlock the vault" in text(listed)[1]
    assert run_cli(tmp_path, "export", plain.id, env=env).stdout == b"Plain note"
    secret = run_cli(tmp_path, "export", locked.id, env=env)
    assert secret.returncode == 1 and "Wrong passphrase" in text(secret)[1]


def test_a_wrong_passphrase_is_a_warning_until_the_key_is_needed(tmp_path, monkeypatch, capsys):
    # The same path as above without the cryptography package: unlocking fails the way a wrong passphrase does.
    plain = saved(Vault(tmp_path), "Plain note")

    def wrong(self, passphrase):
        raise ValueError("Wrong passphrase for encrypted notes")

    monkeypatch.setattr(Vault, "has_key", lambda self: True)
    monkeypatch.setattr(Vault, "unlock", wrong)
    monkeypatch.setenv("JOTLINE_PASSPHRASE", "not it")
    assert main(monkeypatch, "--vault", tmp_path, "list") == 0
    out, err = capsys.readouterr()
    assert plain.id in out and "did not unlock the vault (Wrong passphrase" in err
    assert main(monkeypatch, "--vault", tmp_path, "--unlock", "list") == 1
    assert capsys.readouterr().err == "jotline: Wrong passphrase for encrypted notes\n"


@posix_only
def test_a_broken_converter_keeps_its_error_and_the_html_advice(tmp_path, monkeypatch):
    from jotline import export

    office = tmp_path / "soffice"
    office.write_text("#!/bin/sh\necho 'Error: source file could not be loaded' >&2\nexit 1\n")
    office.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(export, "_existing", lambda *candidates: None)
    with pytest.raises(ExportError) as caught:
        export_bytes("Plan", "body", "docx")
    assert "LibreOffice: Error: source file could not be loaded" in str(caught.value)
    assert str(caught.value).endswith("or export HTML and open it in Word")


def test_a_settings_warning_names_the_file(tmp_path):
    (tmp_path / ".jotline-settings.json").write_text("{broken")
    result = run_cli(tmp_path, "list")
    assert result.returncode == 0
    assert f"Could not load settings from {tmp_path / '.jotline-settings.json'}" in text(result)[1]
