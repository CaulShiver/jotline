"""Short note references, input encodings, JSON listings and shell completion."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from jotline.store import Vault

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shells and argument bytes")


def run_cli(vault: Path, *args, input: bytes | None = None, env=None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, "-m", "jotline", "--vault", os.fsencode(vault), *args],
                          input=input, capture_output=True, check=False, timeout=30, env=env)


def saved(vault: Vault, body: str, note_id: str | None = None, **fields):
    note = vault.new(body, workspace=fields.pop("workspace", "default"))
    note.id = note_id or note.id
    for name, value in fields.items():
        setattr(note, name, value)
    vault.save(note)
    return note


def error(result) -> str:
    return result.stderr.decode()


# Note references ----------------------------------------------------------

def test_unique_id_prefix_resolves(tmp_path):
    vault = Vault(tmp_path)
    target = saved(vault, "target", "abcd1234ef")
    saved(vault, "other", "abce9999")
    assert run_cli(tmp_path, "append", "abcd", "more").returncode == 0
    assert vault.read(target.id).body == "target\nmore"
    assert run_cli(tmp_path, "export", "abcd12").stdout == b"target\nmore"


def test_short_prefix_is_not_guessed(tmp_path):
    saved(Vault(tmp_path), "target", "abcd1234")
    result = run_cli(tmp_path, "export", "abc")
    assert result.returncode == 1
    assert error(result) == "jotline: No note with ID or title abc; run jotline list to find IDs\n"


def test_ambiguous_prefix_names_the_candidates(tmp_path):
    vault = Vault(tmp_path)
    saved(vault, "one", "abcd0001")
    saved(vault, "two", "abcd0002")
    result = run_cli(tmp_path, "tag", "abcd", "work")
    assert result.returncode == 1
    message = error(result)
    assert "abcd matches 2 notes" in message and "abcd0001" in message and "abcd0002" in message
    assert "#work" not in vault.read("abcd0001").body + vault.read("abcd0002").body


def test_exact_title_ignores_case_and_must_be_unique(tmp_path):
    vault = Vault(tmp_path)
    review = saved(vault, "# Weekly Review\n\n- [ ] plan")
    assert run_cli(tmp_path, "export", "weekly review").stdout == review.body.encode()
    saved(vault, "Weekly review")
    result = run_cli(tmp_path, "export", "Weekly Review")
    assert result.returncode == 1 and "matches 2 notes" in error(result)


def test_last_is_the_most_recently_updated_note(tmp_path):
    vault = Vault(tmp_path)
    first = saved(vault, "first")
    saved(vault, "second")
    assert run_cli(tmp_path, "append", first.id, "again").returncode == 0
    assert run_cli(tmp_path, "export", "last").stdout == b"first\nagain"


def test_a_note_whose_id_is_a_keyword_wins(tmp_path):
    vault = Vault(tmp_path)
    saved(vault, "literal", "last")
    saved(vault, "newer")
    assert run_cli(tmp_path, "export", "last").stdout == b"literal"


def test_trash_and_other_workspaces_are_not_matched_silently(tmp_path):
    vault = Vault(tmp_path)
    saved(vault, "Discarded", collection="trash")
    assert "No note with ID or title Discarded" in error(run_cli(tmp_path, "export", "Discarded"))
    saved(vault, "Client plan", workspace="work")
    assert "Note is in another workspace" in error(run_cli(tmp_path, "export", "Client plan"))
    assert run_cli(tmp_path, "--workspace", "work", "export", "client plan").stdout == b"Client plan"


def test_title_references_never_become_paths(tmp_path):
    vault_path = tmp_path / "vault"
    saved(Vault(vault_path), "inside")
    (tmp_path / "outside.md").write_text("secret")
    result = run_cli(vault_path, "export", "../outside")
    assert result.returncode == 1 and result.stdout == b""
    assert "No note with ID or title ../outside" in error(result)


def test_run_and_open_accept_references(tmp_path):
    vault = Vault(tmp_path)
    saved(vault, "quiet", "feed0001")
    (tmp_path / ".jotline-settings.json").write_text(json.dumps(
        {"actions": {"shout": [{"type": "uppercase"}, {"type": "export"}]}}))
    result = run_cli(tmp_path, "run", "shout", "feed")
    assert result.returncode == 0 and result.stdout == b"QUIET"


# Input encodings ----------------------------------------------------------

def test_piped_input_can_name_its_encoding(tmp_path):
    result = run_cli(tmp_path, "capture", "--encoding", "latin-1", input=b"caf\xe9")
    assert result.returncode == 0
    assert Vault(tmp_path).read(result.stdout.decode().strip()).body == "café"


def test_bad_bytes_can_be_replaced(tmp_path):
    result = run_cli(tmp_path, "capture", "--replace-invalid", input=b"caf\xe9")
    assert result.returncode == 0
    assert Vault(tmp_path).read(result.stdout.decode().strip()).body == "caf�"


def test_decode_error_suggests_the_options(tmp_path):
    result = run_cli(tmp_path, "capture", input=b"\xffbin")
    assert result.returncode == 1
    assert error(result) == (
        "jotline: Piped input is not valid UTF-8 text (bad byte at position 0); pass --encoding NAME "
        "if it uses another encoding, or --replace-invalid to substitute bad bytes\n")
    cp1252 = run_cli(tmp_path, "capture", "--encoding", "utf-16", input=b"\x00\xd8")
    assert "not valid utf-16 text" in error(cp1252)


def test_single_file_import_uses_the_encoding(tmp_path):
    source = tmp_path / "quote.txt"
    source.write_bytes(b"\x93quoted\x94")
    vault_path = tmp_path / "vault"
    assert "quote.txt is not valid UTF-8" in error(run_cli(vault_path, "import", str(source)))
    result = run_cli(vault_path, "import", str(source), "--encoding", "cp1252")
    assert result.returncode == 0
    assert Vault(vault_path).read(result.stdout.decode().strip()).body == "“quoted”"


def test_folder_import_warning_is_plain_and_encoding_applies(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "bad.txt").write_bytes(b"caf\xe9")
    vault_path = tmp_path / "vault"
    preview = run_cli(vault_path, "import", str(folder))
    assert "warning: bad.txt: not valid UTF-8 text (bad byte at position 3)" in error(preview)
    assert "codec" not in error(preview)
    latin = run_cli(vault_path, "import", str(folder), "--encoding", "latin-1")
    assert latin.stderr == b"" and b"1 to import" in latin.stdout


@posix_only
def test_command_line_bytes_are_decoded_as_asked(tmp_path):
    result = run_cli(tmp_path, "capture", b"caf\xe9")
    assert result.returncode == 1
    assert "Command-line text is not valid UTF-8 text (bad byte at position 3)" in error(result)
    decoded = run_cli(tmp_path, "capture", "--encoding", "latin-1", b"caf\xe9")
    assert Vault(tmp_path).read(decoded.stdout.decode().strip()).body == "café"


@pytest.mark.parametrize("name", ["klingon", "base64"])
def test_unknown_or_binary_encodings_are_rejected(tmp_path, name):
    result = run_cli(tmp_path, "capture", "--encoding", name, "text")
    assert result.returncode == 2
    assert f"unknown text encoding: {name}" in error(result)


# JSON listings ------------------------------------------------------------

def test_tags_workspaces_and_actions_print_json(tmp_path):
    vault = Vault(tmp_path)
    saved(vault, "one #work #idea")
    saved(vault, "two #work")
    saved(vault, "elsewhere", workspace="clients")
    steps = [{"type": "uppercase"}]
    (tmp_path / ".jotline-settings.json").write_text(json.dumps({"actions": {"shout": steps}}))
    assert json.loads(run_cli(tmp_path, "tags", "--json").stdout) == [
        {"tag": "idea", "count": 1}, {"tag": "work", "count": 2}]
    assert json.loads(run_cli(tmp_path, "workspaces", "--json").stdout) == [
        {"name": "clients", "active": False}, {"name": "default", "active": True}]
    assert json.loads(run_cli(tmp_path, "actions", "--json").stdout) == [{"name": "shout", "steps": steps}]


def test_stats_counts_without_note_bodies(tmp_path):
    vault = Vault(tmp_path)
    saved(vault, "# Plan\n\n- [ ] Next #work")
    saved(vault, "Loose thought")
    daily = vault.daily()
    vault.save(daily)
    starred = saved(vault, "Starred", starred=True)
    data = json.loads(run_cli(tmp_path, "stats", "--json").stdout)
    assert data["workspace"] == "default"
    assert data["notes"] == 4
    assert data["inbox"] == 4
    assert data["inbox_captures"] == 3
    assert data["daily_logs"] == 1
    assert data["open_tasks"] == 1
    assert data["tagged"] == 1
    assert data["starred"] == 1
    text = run_cli(tmp_path, "stats").stdout.decode()
    assert "inbox_captures\t3\n" in text
    assert starred.body not in text and "Loose thought" not in text


def test_capture_date_requires_daily_and_rejects_compact_dates(tmp_path):
    missing = run_cli(tmp_path, "capture", "--date", "yesterday", "hi")
    assert missing.returncode == 2
    assert "--date is only used with --daily" in error(missing)
    compact = run_cli(tmp_path, "capture", "--daily", "--date", "20260901", "hi")
    assert compact.returncode == 2
    assert "today, or yesterday" in error(compact)


def test_daily_command_resolves_a_dated_log_without_launching(tmp_path):
    from jotline.cli import build_parser, prepare
    parser = build_parser()
    args = parser.parse_args(["--vault", str(tmp_path), "daily", "--date", "2026-09-01"])
    run = prepare(parser, args)
    note = run.vault.daily(run.settings.daily_template, run.workspace, when=args.date)
    assert note.id == "daily-2026-09-01"
    assert "2026-09-01" in note.body


# Shell completion ---------------------------------------------------------

@pytest.fixture
def completion_env(tmp_path):
    """A vault with known IDs, tags and actions, and a jotline command on PATH."""
    vault_path = tmp_path / "vault"
    vault = Vault(vault_path)
    saved(vault, "Plan #work", "abcd1234")
    saved(vault, "Other #home", "ffff0000", workspace="side")
    (vault_path / ".jotline-settings.json").write_text(json.dumps(
        {"actions": {"shout": [{"type": "uppercase"}]}}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "jotline"
    shim.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -m jotline "$@"\n')
    shim.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return vault_path, env


def completion_script(shell: str, env) -> str:
    result = subprocess.run(["jotline", "completion", shell], capture_output=True, text=True, env=env,
                            check=True, timeout=30)
    return result.stdout


def shell_words(line: str) -> list[str]:
    # Readline splits at "=", so --vault=PATH arrives as three words.
    return line.replace("=", " = ").split(" ")


BASH_CASES = [
    ("jotline cap", {"capture"}),
    ("jotline dai", {"daily"}),
    ("jotline sta", {"stats"}),
    ("jotline --vault VAULT tag ab", {"abcd1234"}),
    ("jotline --vault VAULT tag abcd1234 wo", {"work"}),
    ("jotline --vault=VAULT export ", {"abcd1234", "last"}),
    ("jotline --vault VAULT --workspace side export ", {"ffff0000", "last"}),
    ("jotline --vault VAULT --workspace ", {"default", "side"}),
    ("jotline --vault VAULT run ", {"shout"}),
    ("jotline --vault VAULT run shout ", {"abcd1234", "last"}),
    ("jotline import --duplicates ", {"skip", "copy"}),
    ("jotline append --encoding latin", {"latin-1"}),
    ("jotline list --j", {"--json"}),
    ("jotline capture --da", {"--daily", "--date"}),
    ("jotline capture --date ", {"today", "yesterday"}),
    ("jotline completion ", {"bash", "zsh", "fish"}),
    ("jotline --vau", {"--vault"}),
]


@posix_only
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
@pytest.mark.parametrize("line, expected", BASH_CASES)
def test_bash_completion(completion_env, line, expected):
    vault_path, env = completion_env
    words = shell_words(line.replace("VAULT", str(vault_path)))
    program = (completion_script("bash", env)
               + f"\nCOMP_WORDS=({' '.join(shlex.quote(word) for word in words)})\nCOMP_CWORD={len(words) - 1}\n"
               + "_jotline\nprintf '%s\\n' \"${COMPREPLY[@]}\"\n")
    result = subprocess.run(["bash", "--norc", "--noprofile", "-c", program], capture_output=True, text=True,
                            env=env, timeout=60)
    assert set(filter(None, result.stdout.splitlines())) == expected


@posix_only
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_bash_completion_completes_import_paths(completion_env, tmp_path):
    vault_path, env = completion_env
    (tmp_path / "meeting notes.md").write_text("x")
    program = (completion_script("bash", env) + f"\ncd {shlex.quote(str(tmp_path))}\n"
               "COMP_WORDS=(jotline import meet)\nCOMP_CWORD=2\n_jotline\nprintf '%s\\n' \"${COMPREPLY[@]}\"\n")
    result = subprocess.run(["bash", "--norc", "--noprofile", "-c", program], capture_output=True, text=True,
                            env=env, timeout=60)
    assert result.stdout.splitlines() == ["meeting notes.md"]


@posix_only
@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not installed")
@pytest.mark.parametrize("line, expected", BASH_CASES)
def test_zsh_completion(completion_env, line, expected):
    vault_path, env = completion_env
    words = shell_words(line.replace("VAULT", str(vault_path)))
    current = words[-1] if words[-1] != "=" else ""
    # Call the function the way bashcompinit's compgen -F does, in its sh emulation.
    program = ("autoload -U compinit && compinit -u -D\n" + completion_script("zsh", env)
               + f"\nCOMP_WORDS=({' '.join(shlex.quote(word) for word in words)})\nCOMP_CWORD={len(words) - 1}\n"
               + f"compgen -F _jotline -- {shlex.quote(current)}\n")
    result = subprocess.run(["zsh", "-f", "-c", program], capture_output=True, text=True, env=env, timeout=60)
    # Zsh's compadd filters candidates by the typed prefix after compgen returns.
    offered = {word for word in result.stdout.splitlines() if word and word.startswith(current)}
    assert offered == expected, result.stderr


FISH_CASES = [
    ("jotline cap", {"capture"}),
    ("jotline --vault VAULT tag ab", {"abcd1234"}),
    ("jotline --vault VAULT tag abcd1234 wo", {"work"}),
    ("jotline --vault=VAULT export abcd", {"abcd1234"}),
    ("jotline --vault VAULT --workspace side export ff", {"ffff0000"}),
    ("jotline --vault VAULT --workspace s", {"side"}),
    ("jotline --vault VAULT run sh", {"shout"}),
    ("jotline --vault VAULT export la", {"last"}),
    ("jotline import --duplicates c", {"copy"}),
    ("jotline append abcd --encoding latin", {"latin-1"}),
    ("jotline list --j", {"--json"}),
    ("jotline capture --da", {"--daily", "--date"}),
    ("jotline completion f", {"fish"}),
]


@posix_only
@pytest.mark.skipif(shutil.which("fish") is None, reason="fish is not installed")
@pytest.mark.parametrize("line, expected", FISH_CASES)
def test_fish_completion(completion_env, line, expected):
    vault_path, env = completion_env
    line = line.replace("VAULT", str(vault_path))
    program = f"jotline completion fish | source\ncomplete -C {shlex.quote(line)}\n"
    result = subprocess.run(["fish", "--no-config", "-c", program], capture_output=True, text=True, env=env,
                            timeout=60)
    assert {row.split("\t")[0] for row in result.stdout.splitlines()} == expected, result.stderr
