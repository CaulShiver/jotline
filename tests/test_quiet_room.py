from textual.widgets import Input, Static

from jotline.app import Jotline, Palette
from jotline.store import Vault


async def test_empty_inbox_and_trash_explain_the_next_step(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        empty = str(app.query_one("#empty-notes", Static).render())
        assert "Inbox is empty" in empty
        assert "ctrl+n starts another" in empty
        app.command("view:trash")
        await pilot.pause()
        empty = str(app.query_one("#empty-notes", Static).render())
        assert "Trash is empty" in empty
        assert "restore" in empty
        app.command("view:starred")
        await pilot.pause()
        assert "No starred notes" in str(app.query_one("#empty-notes", Static).render())
        app.command("view:projects")
        await pilot.pause()
        assert "Move note to projects" in str(app.query_one("#empty-notes", Static).render())


async def test_compact_empty_state_stays_one_line(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        empty = str(app.query_one("#empty-notes", Static).render())
        assert "Inbox is empty" in empty
        assert "Ctrl+N" not in empty and "ctrl+n" not in empty
        brand = str(app.query_one("#brand", Static).render())
        assert "workspaces" not in brand
        assert app.query_one("#hint").has_class("hidden")
        assert app.query_one("#connections").has_class("hidden")


async def test_command_palette_opens_on_everyday_commands(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        palette = app.screen
        assert isinstance(palette, Palette)
        keys = {key for key, _ in palette.filtered}
        assert "new" in keys
        assert "daily" in keys
        assert "recovery" in keys
        assert "format:bold" not in keys
        assert "move:projects" not in keys
        assert "encrypt" not in keys
        assert "type to see" in str(palette.query_one("#command-count", Static).render())
        palette.query_one("#command-query", Input).value = "format bold"
        await pilot.pause()
        keys = {key for key, _ in palette.filtered}
        assert "format:bold" in keys
        assert "new" not in keys
        palette.query_one("#command-query", Input).value = "move note to resources"
        await pilot.pause()
        assert "move:resources" in {key for key, _ in palette.filtered}
