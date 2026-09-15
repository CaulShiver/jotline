"""The small capture editor opened by `jotline capture` with no text."""
import sys

import pytest

from jotline import cli
from jotline.capture_ui import QuickCapture
from jotline.store import Vault


async def test_ctrl_s_returns_the_typed_text():
    app = QuickCapture("inbox · default")
    async with app.run_test() as pilot:
        await pilot.press("h", "i", "enter", "x", "ctrl+s")
    assert app.return_value == "hi\nx"


async def test_escape_needs_a_second_press_once_something_is_typed():
    app = QuickCapture("inbox · default")
    async with app.run_test() as pilot:
        await pilot.press("a", "escape")
        assert app.discard_armed and app.return_value is None
        await pilot.press("b")
        assert not app.discard_armed
        await pilot.press("escape", "escape")
    assert app.return_value is None


async def test_ctrl_q_saves_instead_of_discarding():
    app = QuickCapture("inbox · default")
    async with app.run_test() as pilot:
        await pilot.press("a", "ctrl+q")
    assert app.return_value == "a"


async def test_blank_capture_saves_nothing():
    app = QuickCapture("inbox · default")
    async with app.run_test() as pilot:
        await pilot.press("space", "enter", "ctrl+s")
    assert app.return_value is None


def run_main(monkeypatch, vault_path, *args):
    monkeypatch.setattr(sys, "argv", ["jotline", "--vault", str(vault_path), *args])
    cli.main()


def test_capture_without_text_opens_the_editor_in_a_terminal(tmp_path, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(cli, "can_open_editor", lambda: True)
    monkeypatch.setattr(cli, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(cli, "quick_capture", lambda settings, daily, workspace, when=None: opened.append(
        (daily, workspace, when)) or "From the hotkey")
    run_main(monkeypatch, tmp_path, "capture")
    note_id = capsys.readouterr().out.strip()
    assert Vault(tmp_path).read(note_id).body == "From the hotkey"
    assert opened == [(False, "default", None)]

    monkeypatch.setattr(cli, "quick_capture", lambda settings, daily, workspace, when=None: None)
    with pytest.raises(SystemExit) as cancelled:
        run_main(monkeypatch, tmp_path, "capture")
    assert cancelled.value.code == 1
    assert "Nothing captured" in capsys.readouterr().err
    assert len(Vault(tmp_path).notes()) == 1


def test_capture_without_text_or_terminal_still_asks_for_text(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "can_open_editor", lambda: False)
    monkeypatch.setattr(cli, "stdin_is_interactive", lambda: True)
    with pytest.raises(SystemExit) as refused:
        run_main(monkeypatch, tmp_path, "capture")
    assert refused.value.code == 2
    assert "Provide text or pipe text" in capsys.readouterr().err
