"""Newcomer five-minute path: install is packaging; this is open-to-first-keystroke."""
from dataclasses import replace

from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, TextArea

from jotline.app import Jotline
from jotline.recovery_ui import RecoveryScreen
from jotline.settings import Settings
from jotline.store import Vault


async def test_newcomer_open_type_find_process_and_recover(tmp_path):
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(110, 40)) as pilot:
        app.autosave_timer.stop()
        editor = app.query_one("#editor", TextArea)
        assert Settings().startup == "new"
        assert editor.has_focus
        assert editor.text == ""
        assert not isinstance(app.screen, ModalScreen)
        await pilot.press(*"buy oat milk")
        assert editor.text == "buy oat milk"
        assert app.save_current(explicit=True)
        captured = app.current
        assert captured.body == "buy oat milk"
        assert captured.collection == "inbox"

        await pilot.press("ctrl+f")
        search = app.query_one("#search", Input)
        assert search.has_focus
        search.value = "oat milk"
        app.action_search()
        await pilot.pause()
        listing = app.query_one("#notes", OptionList)
        found = [listing.get_option_at_index(index).id for index in range(listing.option_count)]
        assert captured.id in found

        project = vault.new("# Kitchen project")
        project.collection = "projects"
        vault.save(project)
        app.save_settings(replace(app.settings, actions={
            "file-to-project": [
                {"type": "append", "value": project.id},
                {"type": "archive"},
            ],
        }))
        app.load(captured)
        editor.load_text("buy oat milk")
        app.run_local_action("file-to-project")
        await pilot.pause()
        assert "buy oat milk" in vault.read(project.id).body
        assert vault.read(captured.id).collection == "archive"

        app.load(vault.read(project.id))
        editor.load_text("buy oat milk\nand bread")
        external = vault.read(project.id)
        external.body = "someone else added rice"
        vault.save(external)
        assert not app.save_current(explicit=True)
        await pilot.pause()
        assert isinstance(app.screen, RecoveryScreen)
        for _ in range(12):
            if getattr(app.focused, "id", None) == "preserve":
                break
            await pilot.press("tab")
        assert app.focused.id == "preserve"
        await pilot.press("enter")
        await pilot.pause()
        recovered = [note for note in vault.notes() if "and bread" in note.body]
        assert recovered
        assert vault.read(project.id).body == "someone else added rice"
