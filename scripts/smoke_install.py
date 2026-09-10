"""Check the installed wheel, with Python isolated from the source checkout."""
import asyncio
from pathlib import Path
import subprocess
import sys
import tempfile

from jotline.app import Jotline
from jotline.store import Vault
from textual.widgets import TextArea


async def check(directory):
    command = [sys.executable, '-I', '-m', 'jotline', '--vault', directory]
    captured = subprocess.run(command + ['capture', 'Installed package smoke test'],
                              text=True, capture_output=True, check=True)
    exported = subprocess.run(command + ['export', captured.stdout.strip()],
                              text=True, capture_output=True, check=True)
    assert exported.stdout == 'Installed package smoke test'
    app = Jotline(Vault(Path(directory)))
    async with app.run_test() as pilot:
        await pilot.press('w', 'h', 'e', 'e', 'l')
        await pilot.press('ctrl+n')
        assert any(n.body == 'wheel' for n in app.vault.notes())
        assert app.query_one('#editor', TextArea).text == ''
    print('Installed wheel: CLI capture/export and terminal writing passed.')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        asyncio.run(check(directory))
