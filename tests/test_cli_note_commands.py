"""One note resolver, shell edit/trash/rename, and the shell output fixes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jotline import cli
from jotline.cli import replace_title
from jotline.store import Vault

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shells")


def run_cli(vault: Path, *args, input: bytes | None = None, env=None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, "-m", "jotline", "--vault", os.fsencode(vault), *args],
                          input=input, capture_output=True, check=False, timeout=30, env=env)


def saved(vault: Vault, body: str, note_id: str | None = None, **fields):
    note = vault.new(body, workspace=fields.pop("workspace", "default"))
    if note_id is not None:
        note.id = note_id
    for name, value in fields.items():
        setattr(note, name, value)
    vault.save(note)
    return note


def error(result) -> str:
    return result.stderr.decode()


def titles(result) -> list[str]:
    return [line.split("\t")[2] for line in result.stdout.decode().splitlines() if line]


# Shared note matching -----------------------------------------------------

def test_id_prefix_beats_an_exact_title(tmp_path):
    vault = Vault(tmp_path)
    by_prefix = saved(vault, "Grocery list", "milk0001")
    saved(vault, "milk")
    assert run_cli(tmp_path, "export", "milk").stdout == b"Grocery list\n"
    assert vault.read(by_prefix.id).body == "Grocery list"


def test_exact_title_beats_a_weaker_title_match(tmp_path):
    vault = Vault(tmp_path)
    exact = saved(vault, "milk")
    saved(vault, "Buy milk today")
    assert run_cli(tmp_path, "export", "milk").stdout == exact.body.encode() + b"\n"


def test_every_note_command_accepts_the_best_title_match(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk #home\n- [ ] call\n")
    saved(vault, "Unrelated errand")
    exported = run_cli(tmp_path, "export", "milk")
    assert exported.returncode == 0 and exported.stdout == note.body.encode()
    linked = run_cli(tmp_path, "backlinks", "milk", "--json")
    assert linked.returncode == 0 and json.loads(linked.stdout)["id"] == note.id
    done = run_cli(tmp_path, "done", "milk:2")
    assert done.returncode == 0, done.stderr
    assert "- [x] call" in vault.read(note.id).body
    assert run_cli(tmp_path, "tag", "milk", "later").returncode == 0
    assert "#later" in vault.read(note.id).body
    assert run_cli(tmp_path, "append", "milk", "next").returncode == 0
    assert run_cli(tmp_path, "prepend", "milk", "intro").returncode == 0
    body = vault.read(note.id).body
    assert body.startswith("intro\n") and body.rstrip().endswith("next")


def test_an_ambiguous_title_lists_id_and_title_and_changes_nothing(tmp_path):
    vault = Vault(tmp_path)
    buy = saved(vault, "Buy milk")
    prices = saved(vault, "Milk prices")
    for command in (("export", "milk"), ("append", "milk", "x"), ("tag", "milk", "home"),
                    ("backlinks", "milk"), ("trash", "milk"), ("rename", "milk", "Oat")):
        result = run_cli(tmp_path, *command)
        message = error(result)
        assert result.returncode == 1 and result.stdout == b""
        assert "milk matches 2 notes" in message and "use more of the ID" in message
        assert buy.id in message and prices.id in message
        assert "Buy milk" in message and "Milk prices" in message
    assert vault.read(buy.id).body == "Buy milk"
    assert vault.read(prices.id).body == "Milk prices"
    assert vault.read(buy.id).collection == "inbox"


def test_trash_and_other_workspaces_stay_out_of_a_title_match(tmp_path):
    vault = Vault(tmp_path)
    saved(vault, "Buy milk", collection="trash")
    assert "No note with ID or title milk" in error(run_cli(tmp_path, "export", "milk"))
    saved(vault, "Client plan", workspace="work")
    assert "No note with ID or title plan" in error(run_cli(tmp_path, "export", "plan"))
    assert "Note is in another workspace" in error(run_cli(tmp_path, "export", "Client plan"))


# edit, trash, rename ------------------------------------------------------

def editor_env(tool: str) -> dict[str, str]:
    return {**os.environ, "JOTLINE_EDITOR": tool, "VISUAL": "", "EDITOR": ""}


@posix_only
def test_edit_opens_the_configured_editor_and_reads_the_file_back(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    tool = tmp_path / "editor.sh"
    tool.write_text("#!/bin/sh\nprintf '\\nBrought back\\n' >> \"$1\"\n")
    tool.chmod(0o755)
    result = run_cli(tmp_path, "edit", "milk", env=editor_env(str(tool)))
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode().strip() == note.id
    assert vault.read(note.id).body == "Buy milk\nBrought back\n"
    payload = json.loads(run_cli(tmp_path, "edit", note.id, "--json", env=editor_env("/bin/true")).stdout)
    assert payload["id"] == note.id and payload["title"] == "Buy milk"


@posix_only
def test_edit_reports_a_missing_editor_and_a_failed_editor(tmp_path):
    note = saved(Vault(tmp_path), "Buy milk")
    env = {key: value for key, value in os.environ.items() if key not in ("EDITOR", "VISUAL", "JOTLINE_EDITOR")}
    missing = run_cli(tmp_path, "edit", note.id, env=env)
    assert missing.returncode == 1 and "No editor is configured" in error(missing)
    failing = tmp_path / "fail.sh"
    failing.write_text("#!/bin/sh\nexit 3\n")
    failing.chmod(0o755)
    failed = run_cli(tmp_path, "edit", "milk", env=editor_env(str(failing)))
    assert failed.returncode == 1 and "exited with status 3" in error(failed)
    assert Vault(tmp_path).read(note.id).body == "Buy milk"


@posix_only
def test_edit_refuses_an_encrypted_note(tmp_path):
    pytest.importorskip("cryptography")
    vault = Vault(tmp_path)
    vault.setup_encryption("correct horse", n=2 ** 10)
    note = vault.new("Secret")
    note.encrypted = True
    vault.save(note)
    refused = run_cli(tmp_path, "edit", note.id, env={**editor_env("/bin/true"), "JOTLINE_PASSPHRASE": "correct horse"})
    assert refused.returncode == 1 and "encrypted" in error(refused).casefold()
    assert "Secret" not in vault.file(note.id).read_text()


def test_trash_moves_the_note_and_leaves_the_file(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "Buy milk")
    path = vault.file(note.id)
    before = path.read_bytes()
    result = run_cli(tmp_path, "trash", "milk", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["id"] == note.id and payload["collection"] == "trash" and payload["title"] == "Buy milk"
    assert path.exists() and path.read_bytes() != before
    stored = vault.read(note.id)
    assert stored.collection == "trash" and stored.body == "Buy milk" and stored.id == note.id
    assert note.id.encode() not in run_cli(tmp_path, "list").stdout
    again = run_cli(tmp_path, "trash", note.id)
    assert again.returncode == 1 and "already in the trash" in error(again)


def test_rename_changes_the_title_and_keeps_the_id(tmp_path):
    vault = Vault(tmp_path)
    note = saved(vault, "# Buy milk\n\n- [ ] later")
    result = run_cli(tmp_path, "rename", "milk", "Oat", "milk", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["id"] == note.id and payload["title"] == "Oat milk"
    stored = vault.read(note.id)
    assert stored.body == "# Oat milk\n\n- [ ] later"
    assert vault.file(note.id).exists()
    again = run_cli(tmp_path, "export", "oat")
    assert again.returncode == 0 and b"Oat milk" in again.stdout


def test_rename_sentences_at_a_terminal(tmp_path, monkeypatch, capsys):
    saved(Vault(tmp_path), "Buy milk")
    monkeypatch.setattr(sys, "argv", ["jotline", "--vault", str(tmp_path), "rename", "milk", "Oat milk"])
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    cli.main()
    note = Vault(tmp_path).notes()[0]
    assert capsys.readouterr().out == f"Renamed to Oat milk ({note.id})\n"


def test_replace_title_keeps_a_heading_and_the_note_newline(tmp_path):
    assert replace_title("# Buy milk\n\n- [ ] later", "Oat milk") == "# Oat milk\n\n- [ ] later"
    assert replace_title("Buy milk", "Oat milk") == "Oat milk"
    assert replace_title("# Buy milk\r\n\r\nmore\r\n", "Oat milk") == "# Oat milk\r\n\r\nmore\r\n"
    assert replace_title("- [ ] buy milk", "buy bread") == "buy bread"
    assert replace_title("# Old", "# New heading") == "# New heading"
    assert replace_title("\n\n# Old\nrest\n", "New") == "\n\n# New\nrest\n"


# Terminal guard, export newline, list options -----------------------------

def test_open_and_daily_refuse_without_a_terminal(tmp_path, monkeypatch, capsys):
    note = saved(Vault(tmp_path), "Buy milk")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys, "argv", ["jotline", "--vault", str(tmp_path), "open", note.id])
    with pytest.raises(SystemExit) as opened:
        cli.main()
    assert opened.value.code == 1
    assert capsys.readouterr().err == "jotline: open needs a terminal\n"

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(sys, "argv", ["jotline", "--vault", str(tmp_path), "daily"])
    with pytest.raises(SystemExit) as daily:
        cli.main()
    assert daily.value.code == 1
    assert capsys.readouterr().err == "jotline: daily needs a terminal\n"
    assert list(tmp_path.glob("daily-*.md")) == []

    missing = run_cli(tmp_path, "open", "zzz")
    assert missing.returncode == 1 and "No note with ID or title zzz" in error(missing)


def test_open_and_daily_launch_when_both_streams_are_a_terminal(tmp_path, monkeypatch):
    note = saved(Vault(tmp_path), "Buy milk")
    launched = []

    class FakeApp:
        def __init__(self, vault, workspace, initial_note, first_run):
            launched.append(initial_note.id)

        def run(self):
            return None

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("jotline.app.Jotline", FakeApp)
    monkeypatch.setattr(sys, "argv", ["jotline", "--vault", str(tmp_path), "open", "milk"])
    cli.main()
    monkeypatch.setattr(sys, "argv", ["jotline", "--vault", str(tmp_path), "daily", "--date", "2026-10-02"])
    cli.main()
    assert launched == [note.id, "daily-2026-10-02"]


def test_export_to_stdout_ends_with_one_newline(tmp_path):
    vault = Vault(tmp_path)
    bare = saved(vault, "Buy milk")
    ended = saved(vault, "Already\n")
    assert run_cli(tmp_path, "export", bare.id).stdout == b"Buy milk\n"
    assert run_cli(tmp_path, "export", ended.id).stdout == b"Already\n"
    written = tmp_path / "out.md"
    assert run_cli(tmp_path, "export", bare.id, "--output", str(written)).returncode == 0
    assert written.read_bytes() == b"Buy milk"


def test_list_limit_and_sort(tmp_path):
    vault = Vault(tmp_path)
    alpha = vault.new("Alpha")
    alpha.created = "2026-01-02T00:00:00+00:00"
    vault.save(alpha)
    bravo = vault.new("Bravo")
    bravo.created = "2026-01-01T00:00:00+00:00"
    vault.save(bravo)
    star = vault.new("Zulu")
    star.starred = True
    star.created = "2020-01-01T00:00:00+00:00"
    vault.save(star)

    assert titles(run_cli(tmp_path, "list")) == titles(run_cli(tmp_path, "list", "--sort", "updated"))
    assert titles(run_cli(tmp_path, "list", "--sort", "title")) == ["Zulu", "Alpha", "Bravo"]
    assert titles(run_cli(tmp_path, "list", "--sort", "created"))[0] == "Zulu"
    created = titles(run_cli(tmp_path, "list", "--sort", "created", "--limit", "3"))
    assert created[1:] == ["Alpha", "Bravo"]
    assert titles(run_cli(tmp_path, "list", "--sort", "title", "--limit", "1")) == ["Zulu"]
    payload = json.loads(run_cli(tmp_path, "list", "--json", "--sort", "title", "--limit", "2").stdout)
    assert [item["title"] for item in payload] == ["Zulu", "Alpha"]
    assert run_cli(tmp_path, "search", "--limit", "1", "--sort", "title").stdout == run_cli(
        tmp_path, "list", "--limit", "1", "--sort", "title").stdout

    refused = run_cli(tmp_path, "list", "--limit", "0")
    assert refused.returncode == 2 and b"positive whole number" in refused.stderr
    assert run_cli(tmp_path, "list", "--sort", "nope").returncode == 2


def test_new_commands_are_in_help_and_do_not_create_a_missing_vault(tmp_path):
    help_text = subprocess.run([sys.executable, "-m", "jotline", "--help"], capture_output=True, text=True,
                               check=False, timeout=30).stdout
    for name in ("edit", "trash", "rename"):
        assert name in help_text
    missing = tmp_path / "absent"
    for command in (("edit", "milk"), ("trash", "milk"), ("rename", "milk", "Other")):
        result = run_cli(missing, *command)
        assert result.returncode == 1 and "there is no vault yet" in error(result)
    assert not missing.exists()
