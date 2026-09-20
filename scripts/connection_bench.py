#!/usr/bin/env python3
"""Measure link-heavy navigation on temporary synthetic notes; never user data."""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
import tempfile
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from jotline.links import incoming_refs, index_link_targets, outgoing_refs
from jotline.store import Vault


def measure(operation):
    samples = []
    for _ in range(5):
        start = perf_counter()
        result = operation()
        samples.append((perf_counter() - start) * 1000)
    return {'median_ms': round(statistics.median(samples), 3), 'hits': len(result)}


def main():
    with tempfile.TemporaryDirectory(prefix='jotline-connections-bench-') as folder:
        root = Path(folder)
        filler = ' '.join('project progress planning reference research review'.split() * 12)
        for index in range(2000):
            body = f'# Project {index:04d}\n\n{filler}\n'
            body += ''.join(f'See [[Project {(index + offset + 1) % 2000:04d}]] for details.\n'
                            for offset in range(3))
            (root / f'{index:032x}.md').write_text(body, encoding='utf-8')
        vault = Vault(root)
        start = perf_counter()
        notes = vault.notes()
        scan_ms = (perf_counter() - start) * 1000
        target = notes[1000]
        dashboard = '# Reference dashboard\n' + ''.join(f'[[Project {index:04d}]]\n' for index in range(80))
        targets = index_link_targets(notes)
        print(json.dumps({
            'notes': len(notes), 'body_bytes': sum(len(note.body.encode()) for note in notes),
            'cold_scan_ms': round(scan_ms, 3),
            'search': measure(lambda: vault.search('project review', notes=notes)),
            'outgoing_80': measure(lambda: outgoing_refs(dashboard, notes)),
            'outgoing_80_cached': measure(lambda: outgoing_refs(dashboard, notes, target_index=targets)),
            'backlinks': measure(lambda: incoming_refs(target, notes)),
        }, indent=2))


if __name__ == '__main__':
    main()
