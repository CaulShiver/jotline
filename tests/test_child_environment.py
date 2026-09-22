"""No helper process jotline starts inherits the passphrase.

Each test runs a real stand-in through the actual spawn site and reads back
the environment the child was given, since on Linux /proc/<pid>/environ shows
it to every process of the same user.
"""
from contextlib import nullcontext
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest

from jotline import clipboard, desktop, export
from jotline.app import Jotline
from jotline.environment import SECRET_VARIABLES, child_environment
from jotline.store import Vault

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="uses a shell-script stand-in")
SECRETS = {"JOTLINE_PASSPHRASE": "hunter2-correct-horse", "JOTLINE_NEW_PASSPHRASE": "new-battery-staple"}


@pytest.fixture
def secrets_in_environment(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("JOTLINE_CHILD_MARKER", "still-here")


def stand_in(folder: Path) -> tuple[Path, Path]:
    """A tool that records its environment, one NAME=value per line, and exits cleanly."""
    dump = folder / "environ.txt"
    tool = folder / "stand-in"
    tool.write_text(f'#!/bin/sh\nenv > "{dump}"\n')
    tool.chmod(0o755)
    return tool, dump


def child_saw(dump: Path, wait: float = 0) -> dict[str, str]:
    deadline = time.monotonic() + wait
    while not dump.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    lines = dump.read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def assert_clean(seen: dict[str, str]) -> None:
    for name, value in SECRETS.items():
        assert name not in seen
        assert value not in seen.values()
    # The rest of the user's environment still reaches the child.
    assert seen["JOTLINE_CHILD_MARKER"] == "still-here"
    assert seen["PATH"] == os.environ["PATH"]


def test_child_environment_strips_every_passphrase_and_nothing_else(secrets_in_environment):
    child = child_environment()
    for name in SECRETS:
        assert name not in child
    assert child["JOTLINE_CHILD_MARKER"] == "still-here"
    assert set(child) == set(os.environ) - set(SECRETS)
    # The parent keeps them; only the copy handed out is stripped.
    assert os.environ["JOTLINE_PASSPHRASE"] == SECRETS["JOTLINE_PASSPHRASE"]


def test_every_passphrase_variable_the_shell_reads_is_a_secret():
    """A passphrase read in cli.py without being listed here would leak again."""
    source = (Path(__file__).parent.parent / "src" / "jotline" / "cli.py").read_text()
    read = set(re.findall(r'"(JOTLINE_[A-Z_]*PASSPHRASE)"', source))
    assert read == set(SECRETS) == set(SECRET_VARIABLES)


@posix_only
def test_the_clipboard_tool_does_not_see_the_passphrase(tmp_path, monkeypatch, secrets_in_environment):
    tool, dump = stand_in(tmp_path)
    monkeypatch.setattr(clipboard, "clipboard_command", lambda: [str(tool)])
    assert clipboard.write_system_clipboard("note") is True
    assert_clean(child_saw(dump))


@posix_only
def test_an_export_converter_does_not_see_the_passphrase(tmp_path, monkeypatch, secrets_in_environment):
    tool, dump = stand_in(tmp_path)
    export._run([str(tool)], tmp_path / "note.docx", timeout=10)
    assert_clean(child_saw(dump))


@posix_only
def test_the_desktop_database_refresh_does_not_see_the_passphrase(tmp_path, monkeypatch, secrets_in_environment):
    tool, dump = stand_in(tmp_path)
    monkeypatch.setattr(desktop.shutil, "which", lambda name: str(tool))
    desktop.refresh_desktop_database(tmp_path)
    assert_clean(child_saw(dump))


@posix_only
def test_the_launched_terminal_does_not_see_the_passphrase(tmp_path, secrets_in_environment):
    tool, dump = stand_in(tmp_path)
    desktop.execute_launch(desktop.LaunchPlan("spawn", [str(tool)]))
    assert_clean(child_saw(dump, wait=10))


@posix_only
def test_an_exec_launch_does_not_see_the_passphrase(tmp_path, secrets_in_environment):
    """exec replaces the caller, so it runs in a child interpreter that then becomes the stand-in."""
    tool, dump = stand_in(tmp_path)
    program = ("from jotline.desktop import LaunchPlan, execute_launch\n"
               f"execute_launch(LaunchPlan('exec', [{str(tool)!r}]))\n")
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert_clean(child_saw(dump))


@posix_only
def test_the_external_editor_does_not_see_the_passphrase(tmp_path, monkeypatch, secrets_in_environment):
    tool, dump = stand_in(tmp_path)
    # Suspending is the terminal's business; the run is the point.
    monkeypatch.setattr(Jotline, "suspend", lambda self: nullcontext())
    app = Jotline(Vault(tmp_path / "vault"))
    assert app.hand_to_editor([str(tool)], tmp_path / "note.md") == ""
    assert_clean(child_saw(dump))
