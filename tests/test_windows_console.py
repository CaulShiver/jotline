"""Windows reports the NUL device as a TTY; only a real console may prompt."""
import io

import pytest

from jotline import cli


class NulStdin(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def windows_nul_stdin(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.sys, "stdin", NulStdin())
    monkeypatch.setattr(cli, "windows_console_input", lambda: False)
    monkeypatch.delenv("JOTLINE_PASSPHRASE", raising=False)


def test_nul_stdin_is_not_interactive(windows_nul_stdin):
    assert not cli.stdin_is_interactive()
    assert not cli.terminal_available()
    assert not cli.can_ask_passphrase()


def test_passphrase_prompt_refuses_instead_of_waiting(windows_nul_stdin, monkeypatch):
    def waits_forever(prompt=""):
        raise AssertionError("getpass would block on the console")

    monkeypatch.setattr(cli.getpass, "getpass", waits_forever)
    with pytest.raises(ValueError, match="set JOTLINE_PASSPHRASE"):
        cli.ask_passphrase()


def test_a_real_windows_console_still_prompts(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.sys, "stdin", NulStdin())
    monkeypatch.setattr(cli, "windows_console_input", lambda: True)
    assert cli.stdin_is_interactive()


def test_console_probe_is_false_off_windows_or_without_a_handle(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO())
    assert cli.windows_console_input() is False
