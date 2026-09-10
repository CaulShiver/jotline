"""Cross-boundary regressions: running UI, shell capture, and external files."""
import asyncio
import sys

from textual.widgets import TextArea
from jotline.app import Jotline
from jotline.store import Vault


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
