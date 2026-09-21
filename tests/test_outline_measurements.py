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
    for shape in ('flat', 'nested'):
        for count in (1000, 10000):
            openings, samples = [], []
            structural, folds, paints = {}, [], []
            for repeat in range(3):
                app = Jotline(Vault(tmp_path / f'{shape}-{count}-{repeat}'))
                async with app.run_test(size=(110, 35)) as pilot:
                    body = '\n'.join(('  ' if shape == 'nested' and i % 10 else '') +
                                     f'- Item {i:05d} ' + 'detail ' * 8 for i in range(count))
                    app.editor().load_text(body)
                    await pilot.pause()
                    start = time.perf_counter()
                    app.action_outliner()
                    await pilot.pause()
                    openings.append((time.perf_counter() - start) * 1000)
                    screen = app.screen
                    screen.choose(list(screen.outline.walk())[count // 2])
                    screen.action_edit_block()
                    await pilot.pause()
                    for _ in range(7):
                        editor = screen.block_editor()
                        with editor.prevent(TextArea.Changed):
                            editor.insert_checked('x')
                        start = time.perf_counter()
                        assert screen.flush()
                        samples.append((time.perf_counter() - start) * 1000)
                        await pilot.pause()
                    assert len(screen.query(TextArea)) == 1
                    assert screen.source.text == screen.outline.text
                    visible_rows = screen.view().size.height
                    # Structural keys are what outlining actually spends its
                    # day on, so time them alongside opening and typing.
                    for name in ('new_block', 'indent', 'outdent', 'move_down', 'task'):
                        for _ in range(5):
                            start = time.perf_counter()
                            getattr(screen, 'action_' + name)()
                            structural.setdefault(name, []).append((time.perf_counter() - start) * 1000)
                            await pilot.pause()
                    target = next(b for b in screen.outline.walk() if b.children) \
                        if any(b.children for b in screen.outline.walk()) else None
                    for _ in range(6):
                        if target is None:
                            break
                        screen.current = target
                        start = time.perf_counter()
                        screen.action_fold()
                        folds.append((time.perf_counter() - start) * 1000)
                    await pilot.pause()
                    view = screen.view()
                    for _ in range(10):
                        start = time.perf_counter()
                        for y in range(view.size.height):
                            view.render_line(y)
                        paints.append((time.perf_counter() - start) * 1000)
            results.append({'shape': shape, 'blocks': count,
                            'open_headless_ms': round(statistics.median(openings), 2),
                            'flush_median_ms': round(statistics.median(samples), 2),
                            'flush_max_ms': round(max(samples), 2),
                            'structural_median_ms': {name: round(statistics.median(values), 2)
                                                     for name, values in structural.items()},
                            'fold_median_ms': round(statistics.median(folds), 2) if folds else None,
                            'viewport_paint_median_ms': round(statistics.median(paints), 2),
                            'opening_samples_ms': openings, 'flush_samples_ms': samples,
                            'structural_samples_ms': structural, 'fold_samples_ms': folds,
                            'editor_widgets': 1, 'visible_rows': visible_rows})
    path = Path('/tmp/jotline-outline-measurements.json')
    path.write_text(json.dumps(results, indent=2) + '\n')
    print(path.read_text())
