"""Cross-boundary regressions: running UI, shell capture, and external files."""
import asyncio
import sys

from textual.widgets import Input, OptionList, TextArea
from jotline.app import Jotline
from jotline.store import Vault


async def test_visible_search_picks_up_shell_capture_without_disturbing_the_draft(tmp_path):
    vault = Vault(tmp_path)
    older = vault.new("# Older note\n\nIncludes rutabagas.")
    vault.save(older)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.autosave_timer.stop()
        draft_id = app.current.id
        await pilot.press(*"unsaved draft", "ctrl+f", *"rutabagas", "down")
        listing = app.query_one("#notes", OptionList)
        assert listing.has_focus
        assert listing.option_count == 1
        assert listing.highlighted_option.id == older.id

        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'jotline', '--vault', str(tmp_path), 'capture', 'Rutabagas',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        output, error = await asyncio.wait_for(process.communicate(), timeout=10)
        assert process.returncode == 0, error.decode()
        capture_id = output.decode().strip()
        for _ in range(30):
            if listing.option_count == 2:
                break
            await pilot.pause(0.1)
        assert listing.option_count == 2
        assert listing.get_option_at_index(0).id == capture_id
        assert listing.has_focus
        assert listing.highlighted_option.id == older.id
        assert app.query_one("#search", Input).value == "rutabagas"
        assert app.current.id == draft_id and app.dirty
        assert app.editor().text == "unsaved draft"
        assert not vault.file(draft_id).exists()


async def test_shell_capture_during_edit_preserves_both_versions(tmp_path):
    vault = Vault(tmp_path)
    daily = vault.daily()
    daily.body += 'Original daily log'
    vault.save(daily)
    app = Jotline(vault)
    async with app.run_test() as pilot:
        app.load_id(daily.id)
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'jotline', '--vault', str(tmp_path),
            'capture', '--daily', 'Captured from a different terminal',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        output, error = await process.communicate()
        assert process.returncode == 0, error.decode()
        assert output.decode().strip() == daily.id
        editor = app.query_one('#editor', TextArea)
        editor.insert('\nUnfinished editor thought')
        await pilot.pause()
        assert app.save_current() is False
        app.action_new()
        assert app.current.id == daily.id
        app.command('recovery')
        await pilot.pause()
        assert app.current.id != daily.id
        assert 'Unfinished editor thought' in vault.read(app.current.id).body
        assert 'Captured from a different terminal' in vault.read(daily.id).body
