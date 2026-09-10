"""Render the real app with synthetic notes; never reads the user's vault."""
import asyncio
from pathlib import Path
import tempfile
from jotline.app import Jotline
from jotline.store import Vault


async def main():
    with tempfile.TemporaryDirectory() as directory:
        vault = Vault(Path(directory))
        for body in ('# Small ideas, loosely connected\n\nGood notes leave room for a second thought. #writing',
                     '# The next small step\n\n- [ ] Sketch the first version\n- [ ] Ask one useful question #project/jotline'):
            vault.save(vault.new(body))
        daily = vault.new('# A quieter way to work\n\nCapture the thought before deciding where it belongs.\n\n## This morning\n\n- One place for unfinished thoughts.\n- Plain text that stays mine.\n- A few good connections, made over time.\n\n## Next\n\n- [ ] Turn the rough idea into a first draft\n- [x] Make a little room to think\n\n#writing #daily')
        vault.save(daily)
        app = Jotline(vault)
        async with app.run_test(size=(112, 32)) as pilot:
            app.load_id(daily.id)
            await pilot.pause()
            app.save_screenshot('screenshot.svg', path='docs')


asyncio.run(main())
