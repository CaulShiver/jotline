"""Opt-in headless measurements; no hardware-dependent CI timing assertions.

Run JOTLINE_OUTLINE_BENCHMARK=1 pytest tests/test_outline_measurements.py -q -s.
"""
import json
import os
import statistics
import time
from pathlib import Path

import pytest
from textual.widgets import TextArea

from jotline.app import Jotline
from jotline.store import Vault


@pytest.mark.skipif(os.environ.get('JOTLINE_OUTLINE_BENCHMARK') != '1', reason='opt-in outline measurements')
async def test_outline_measurements(tmp_path):
    results = []
    for count in (1000, 10000):
        app = Jotline(Vault(tmp_path / str(count)))
        async with app.run_test(size=(110, 35)) as pilot:
            body = '\n'.join(f'- Item {i:05d} ' + 'detail ' * 8 for i in range(count))
            app.editor().load_text(body)
            await pilot.pause()
            start = time.perf_counter()
            app.action_outliner()
            await pilot.pause()
            opening = (time.perf_counter() - start) * 1000
            screen = app.screen
            screen.choose(screen.outline.roots[count // 2])
            screen.action_edit_block()
            await pilot.pause()
            samples = []
            for _ in range(7):
                editor = screen.block_editor()
                with editor.prevent(TextArea.Changed):
                    editor.insert_checked('x')
                start = time.perf_counter()
                assert screen.flush()
                samples.append((time.perf_counter() - start) * 1000)
                await pilot.pause()
            results.append({'blocks': count, 'open_headless_ms': round(opening, 2),
                            'flush_median_ms': round(statistics.median(samples), 2),
                            'flush_max_ms': round(max(samples), 2),
                            'editor_widgets': len(screen.query(TextArea)),
                            'visible_rows': screen.view().size.height})
            assert len(screen.query(TextArea)) == 1
            assert screen.source.text == screen.outline.text
            if count == 1000:
                app.save_screenshot('/tmp/jotline-inline-outliner.svg')
    path = Path('/tmp/jotline-outline-measurements.json')
    path.write_text(json.dumps(results, indent=2) + '\n')
    print(path.read_text())
