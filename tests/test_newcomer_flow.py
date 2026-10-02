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


async def test_first_launch_of_an_empty_vault_shows_the_walkthrough_once(tmp_path):
    from jotline.navigation import Walkthrough
    app = Jotline(Vault(tmp_path / "vault"), first_run=True)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, Walkthrough)
        assert "Capture, find, and use your notes" in app.screen.body
        await pilot.press("escape")
        assert app.editor().has_focus
    assert app.vault.notes() == []
    assert Settings.load(app.settings_path)[0].walkthrough_shown
    again = Jotline(Vault(tmp_path / "vault"), first_run=True)
    async with again.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        assert not isinstance(again.screen, ModalScreen)


async def test_first_run_walkthrough_skips_filled_vaults_and_note_launches(tmp_path):
    vault = Vault(tmp_path / "empty")
    note = vault.new("# Opened from the shell")
    filled = Vault(tmp_path / "filled")
    filled.save(filled.new("# Already writing"))
    for app in (Jotline(vault, initial_note=note, first_run=True), Jotline(filled, first_run=True),
                Jotline(Vault(tmp_path / "pilot"))):
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            assert not isinstance(app.screen, ModalScreen)
            assert not app.settings.walkthrough_shown


def test_settings_without_walkthrough_flag_still_load(tmp_path):
    path = tmp_path / ".jotline-settings.json"
    path.write_text('{"theme": "nord", "line_numbers": true}\n')
    settings, warning = Settings.load(path)
    assert not warning and settings.theme == "nord" and settings.walkthrough_shown is False
    path.write_text('{"theme": "nord", "walkthrough_shown": "yes"}\n')
    settings, warning = Settings.load(path)
    assert "walkthrough_shown" in warning and settings.theme == "nord"


async def test_guide_opens_read_only_and_review_saves_only_once_typed(tmp_path):
    from jotline.navigation import Walkthrough
    vault = Vault(tmp_path)
    app = Jotline(vault)
    async with app.run_test(size=(110, 40)) as pilot:
        app.autosave_timer.stop()
        app.settings = replace(app.settings, hotkeys={"new": "alt+n"})
        for _ in range(3):
            app.command("help")
            await pilot.pause()
            assert isinstance(app.screen, Walkthrough)
            assert "A little room to think" in app.screen.body
            assert "Press alt+n and write" in app.screen.body
            await pilot.press("escape")
        app.command("review")
        await pilot.pause()
        assert app.editor().text.startswith("# Weekly review")
        app.action_new()
        assert vault.notes() == []
        app.command("review")
        await pilot.pause()
        app.editor().move_cursor(app.editor().document.end)
        await pilot.press(*"calm week")
        assert app.save_current(explicit=True)
        saved = vault.notes()
        assert len(saved) == 1 and saved[0].body.startswith("# Weekly review")
        assert saved[0].body.endswith("calm week")


def test_only_a_plain_launch_may_introduce_the_vault(tmp_path, monkeypatch):
    import sys
    from jotline import cli
    vault = Vault(tmp_path)
    note = vault.new("# Shell note")
    vault.save(note)
    launched = []
    monkeypatch.setattr(Jotline, "run", lambda self: launched.append(self.first_run))
    for extra in ([], ["daily"], ["open", note.id]):
        monkeypatch.setattr(sys, "argv", ["jotline", "--vault", str(tmp_path), *extra])
        cli.main()
    assert launched == [True, False, False]
