"""Opt-in headless measurements for the note list; no CI timing assertions.

Run JOTLINE_LIST_BENCHMARK=1 pytest tests/test_list_measurements.py -q -s.
"""
import json
import os
import statistics
import time
from pathlib import Path

import pytest
from textual.widgets import Input

from jotline.app import Jotline
from jotline.store import Vault

PHRASES = ('project', 'alpha', 'note 01')


@pytest.mark.skipif(os.environ.get('JOTLINE_LIST_BENCHMARK') != '1', reason='opt-in note list measurements')
async def test_note_list_measurements(tmp_path):
    results = []
    refresh_notes = Jotline.refresh_notes
    spent = []

    def timed(self):
        start = time.perf_counter()
        refresh_notes(self)
        spent.append((time.perf_counter() - start) * 1000)

    Jotline.refresh_notes = timed
    try:
        for count in (100, 500, 2000):
            vault = Vault(tmp_path / f'vault-{count}')
            for index in range(count):
                vault.save(vault.new(f'# Note {index:05d} about project alpha\n\nbody #tag{index % 20}\n'))
            app = Jotline(vault)
            async with app.run_test(size=(110, 35)) as pilot:
                await pilot.pause()
                search = app.query_one('#search', Input)
                typed = []
                for phrase in PHRASES:
                    search.value = ''
                    app.refresh_notes()
                    await pilot.pause()
                    spent.clear()
                    for character in phrase:
                        search.value += character
                        await pilot.pause()
                        await pilot.pause(0.03)      # a fast typist's gap between keys
                    for _ in range(200):
                        if app._search_timer is None:
                            break
                        await pilot.pause(0.02)
                    typed.append({'query': phrase, 'keys': len(phrase),
                                  'rebuilds': len(spent), 'refresh_ms': round(sum(spent), 2)})
                # A save that leaves every row reading the same, as an autosave does.
                changed, unchanged = [], []
                for index in range(5):
                    search.value = ''
                    app.refresh_notes()
                    await pilot.pause()
                    app.editor().load_text(f'# Measured note {index}\n')
                    spent.clear()
                    assert app.save_current(explicit=True)
                    changed.extend(spent)
                    spent.clear()
                    app.refresh_notes()
                    unchanged.extend(spent)
                    await pilot.pause()
            results.append({'notes': count, 'typed': typed,
                            'rebuilds_per_phrase': [entry['rebuilds'] for entry in typed],
                            'refresh_changed_median_ms': round(statistics.median(changed), 2),
                            'refresh_unchanged_median_ms': round(statistics.median(unchanged), 2),
                            'refresh_changed_samples_ms': [round(value, 2) for value in changed],
                            'refresh_unchanged_samples_ms': [round(value, 2) for value in unchanged]})
    finally:
        Jotline.refresh_notes = refresh_notes
    path = Path('/tmp/jotline-list-measurements.json')
    path.write_text(json.dumps(results, indent=2) + '\n')
    print(path.read_text())
