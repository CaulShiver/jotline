"""Application task commands must operate on the visible outline selection."""
import pytest

from jotline.app import Jotline
from jotline.modal import Palette
from jotline.outliner_ui import OutlinerScreen
from jotline.store import Vault


@pytest.mark.parametrize("command", ["shortcut", "palette"])
@pytest.mark.parametrize("editing", [False, True])
async def test_app_task_command_targets_current_outline_block(tmp_path, command, editing):
    vault = Vault(tmp_path)
    body = "- [ ] First\n- [ ] Second"
    note = vault.new(body)
    vault.save(note)
    app = Jotline(vault, initial_note=note)
    async with app.run_test(size=(100, 32)) as pilot:
        app.editor().move_cursor((0, 0))
        app.action_outliner()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, OutlinerScreen)
        screen.choose(screen.outline.roots[1])
        if editing:
            screen.action_edit_block()
        await pilot.pause()
        if command == "shortcut":
            await pilot.press("ctrl+l")
        else:
            screen.action_commands()
            await pilot.pause()
            assert isinstance(app.screen, Palette)
            app.screen.dismiss("app:task")
        await pilot.pause()
        assert app.editor().text == "- [ ] First\n- [x] Second"
        assert app.save_current()
        assert vault.read(note.id).body == app.editor().text
        screen.action_undo()
        assert app.editor().text == body
