"""The default surface stays the writing loop."""
from textual.widgets import TextArea

from jotline.app import Jotline
from jotline.cli import build_parser
from jotline.commands import EVERYDAY_COMMANDS
from jotline.crypto import KEY_FILE
from jotline.screens import FindInNote
from jotline.store import Vault

import jotline.cli as cli
import jotline.crypto as crypto


def test_everyday_commands_stay_the_writing_loop(tmp_path):
    app = Jotline(Vault(tmp_path))
    everyday = {key for key, command in app.command_registry.items() if command.group == "everyday"}
    assert everyday == EVERYDAY_COMMANDS
    assert "outliner" in app.command_registry
    assert app.command_registry["outliner"].group == "more"
    assert "sync-recipe" in app.command_registry
    assert app.command_registry["sync-recipe"].group == "more"
    assert len(everyday) == len(EVERYDAY_COMMANDS)


async def test_a_new_vault_opens_on_a_blank_page(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        assert app.settings.focus_on_start
        assert app.focused_writing
        assert app.editor().has_focus
        for selector in ("#sidebar", "#markdown-toolbar", "#hint"):
            assert app.query_one(selector).has_class("hidden"), selector
        assert not app.query("#md-outliner")
        editor = app.query_one("#editor", TextArea)
        editor.insert("one two")
        await pilot.press("ctrl+w")
        assert editor.text == "one "
        await pilot.press("f3")
        assert isinstance(app.screen, FindInNote)
        await pilot.press("escape")
        await pilot.press("ctrl+f")
        assert not app.query_one("#sidebar").has_class("hidden")
        await pilot.press("escape", "ctrl+o")
        await pilot.pause()
        assert app.screen.query("#command-query")


def test_encryption_stays_hidden_until_the_extra_or_a_key_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto, "library_installed", lambda: False)
    monkeypatch.setattr(cli, "default_vault", lambda: tmp_path)
    hidden = Jotline(Vault(tmp_path))
    assert "encrypt" not in hidden.command_registry
    assert "decrypt" not in hidden.command_registry
    task = _task_lines(build_parser().format_help())
    assert "encrypt" not in task and "decrypt" not in task
    assert "encryption" not in task

    (tmp_path / KEY_FILE).write_text("{}\n")
    revealed = Jotline(Vault(tmp_path))
    assert revealed.command_registry["encrypt"].group == "more"
    listed = _task_lines(build_parser().format_help())
    assert "encrypt" in listed and "decrypt" in listed and "encryption" in listed

    (tmp_path / KEY_FILE).unlink()
    monkeypatch.setattr(crypto, "library_installed", lambda: True)
    installed = Jotline(Vault(tmp_path))
    assert installed.command_registry["encrypt"].group == "more"
    assert "encrypt" in _task_lines(build_parser().format_help())


def _task_lines(help_text: str) -> str:
    return help_text.split("commands by task:", 1)[1].split("examples:", 1)[0]
