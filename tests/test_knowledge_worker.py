from datetime import date, timedelta

from textual.widgets import Input, Static, TextArea

from jotline.app import Jotline, TextPrompt
from jotline.store import Vault, daily_id


def saved(vault, body, **fields):
    note = vault.new(body, workspace=fields.pop("workspace", "default"))
    for name, value in fields.items():
        setattr(note, name, value)
    vault.save(note)
    return note


async def test_previous_next_and_dated_daily_logs(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        app.command("daily")
        await pilot.pause()
        today = date.today()
        assert app.current.id == daily_id(today)
        app.command("daily-previous")
        await pilot.pause()
        yesterday = today - timedelta(days=1)
        assert app.current.id == daily_id(yesterday)
        assert yesterday.isoformat() in app.current.body
        app.command("daily-next")
        await pilot.pause()
        assert app.current.id == daily_id(today)
        app.command("daily-date")
        await pilot.pause()
        assert isinstance(app.screen, TextPrompt)
        app.screen.query_one(Input).value = "2026-09-01"
        await pilot.press("enter")
        await pilot.pause()
        assert app.current.id == "daily-2026-09-01"
        assert "# 2026-09-01" in app.query_one("#editor", TextArea).text


async def test_extract_selection_creates_linked_inbox_note(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test() as pilot:
        editor = app.query_one("#editor", TextArea)
        editor.insert("# Keep\n\n# Durable idea\n\nKeep this with the idea.")
        await pilot.pause()
        start = editor.text.index("# Durable idea")
        editor.move_cursor(app.editor_location(start, editor.text))
        editor.move_cursor(app.editor_location(len(editor.text), editor.text), select=True)
        app.command("extract")
        await pilot.pause()
        extracted = [note for note in app.vault.search() if note.id != app.current.id]
        assert len(extracted) == 1
        note = extracted[0]
        assert note.collection == "inbox"
        assert note.body.startswith("# Durable idea")
        assert "Keep this with the idea." in note.body
        assert editor.text == "# Keep\n\n" + note.wiki_link()
        assert app.inbox_capture_count == 1
        assert "1 inbox" in str(app.query_one("#status", Static).render())


async def test_extract_requires_a_selection(tmp_path):
    app = Jotline(Vault(tmp_path))
    async with app.run_test():
        app.query_one("#editor", TextArea).insert("unextracted")
        app.command("extract")
        assert app.vault.notes() == []
        assert app.query_one("#editor", TextArea).text == "unextracted"


async def test_process_inbox_skips_dailies_and_opens_next_after_filing(tmp_path):
    vault = Vault(tmp_path)
    older = saved(vault, "old capture", created="2026-01-01T00:00:00+00:00")
    newer = saved(vault, "new capture", created="2026-06-01T00:00:00+00:00")
    daily = vault.daily()
    vault.save(daily)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        assert "2 inbox" in str(app.query_one("#status", Static).render())
        assert app.inbox_capture_count == 2
        app.command("process-inbox")
        await pilot.pause()
        assert app.current.id == older.id
        app.command("move:projects")
        await pilot.pause()
        assert vault.read(older.id).collection == "projects"
        assert app.current.id == newer.id
        assert app.inbox_capture_count == 1
        assert "1 inbox" in str(app.query_one("#status", Static).render())
        app.command("move:areas")
        await pilot.pause()
        assert vault.read(newer.id).collection == "areas"
        assert app.current.id == newer.id
        assert app.inbox_capture_count == 0
        assert vault.read(daily.id).collection == "inbox"
