# Performance measurements — 2026-09-20

Measured on Linux/Python 3.12 against pre-optimization commit `cc8c125`.
These are synthetic local measurements, not guaranteed latency on every machine.

## Outline opening and editing

The headless Textual fixture uses a 110×35 terminal, one reusable editor and
1,000 or 10,000 blocks. Each block has an item label and eight words of detail.
The nested fixture groups nine children under each root. Opening includes
headless event settling; editing measures a direct flush after inserting one
character halfway through the note. Medians use three openings and 21 flushes
per fixture. Terminal transport and physical key-to-paint latency are excluded.

| Shape | Blocks | Opening before → after | Edit flush before → after |
| --- | ---: | ---: | ---: |
| Flat | 1,000 | 320 → 302 ms | 2.88 → 1.33 ms |
| Flat | 10,000 | 1,091 → 512 ms | 24.99 → 8.13 ms |
| Nested | 1,000 | 447 → 252 ms | 3.58 → 2.43 ms |
| Nested | 10,000 | 1,303 → 1,055 ms | 23.49 → 8.78 ms |

The full suite was finished before either run. Headless opening varies with
event scheduling: the three optimized 10,000-flat-block samples ranged from
440 to 707 ms. The larger nested fixture still exceeds the proposed 500 ms
opening target. [Raw samples](performance-measurements.json) retain that variation.

The before/after measurements use the same fixture in separate processes and
source trees. Run the optimized fixture with:

```sh
JOTLINE_OUTLINE_BENCHMARK=1 uv run --locked pytest tests/test_outline_measurements.py -q -s
```

## Link-heavy navigation and metadata

The connections fixture has 2,000 temporary notes, 1.48 MB of text, three links
per note, and an 80-link dashboard. Timings are medians of five calls.

| Operation | Before | After |
| --- | ---: | ---: |
| Resolve 80 outgoing links, including lookup construction | 166.8 ms | 2.68 ms |
| Resolve the same links with a cached workspace lookup | 166.8 ms | 0.27 ms |
| Find incoming links | 22.1 ms | 1.48 ms |
| Scan tags in a 700 KB note with no tags | 5.93 ms | 0.15 ms |

The link numbers isolate the connection changes; the combined heading
optimization subsequently reduced lookup construction further. Cold vault scans
and plain-text search were already fast (about 50 ms and 2 ms respectively) and
were left unchanged. The lookup is ephemeral and invalidates when the workspace
snapshot refreshes; it is not a persistent search index.

```sh
uv run --locked python scripts/connection_bench.py
```

## Changes and limits

- Ordinary inline typing reuses the block row/identity snapshot when line counts
  stay the same. Structural edits and undo still capture current folds and rows.
- Outline rows remain plain strings until wrapping or viewport rendering needs
  Rich text. Idle status refreshes compare the canonical source with its last
  synchronized value instead of serializing the block tree every half second.
- A narrow shortcut recognizes flat dash lists whose content starts with a
  letter or number. All other inputs, including nested lists, task items, empty
  blocks, fences and continuation lines, use the existing CommonMark parser.
- Link aliases are built once per workspace snapshot, preserving ambiguous
  title matches, ordering and block anchors. Backlinks skip parsing notes that
  cannot contain the target alias.
- Tag scanning lets the regex engine jump to the literal `#`; heading lookup
  avoids copying the entire body. Both retain existing Unicode and boundary
  behavior and metadata limits.

Large nested notes still require full CommonMark parsing during opening and
structural edits. There is no incremental block parser. No autosave, filesystem
sync, conflict detection, encryption, or recovery safeguards were relaxed.

## Verification

The complete suite passed with **880 passed, 41 skipped**. Both installed-wheel
smokes passed: CLI/TUI workflows and the POSIX PTY outliner workflow. Regression
tests cover undo identity/folds, viewport work counts, external source updates,
link cache invalidation, alias ambiguity, metadata boundaries and parser parity.

A separate agent reviewed the combined changes and compared 6,000 generated
fast-path outlines with CommonMark and 10,000 metadata examples with the previous
implementation. Its UI sequence covered repeated edits, line-count changes,
folds, move/undo/redo and an external replacement without finding a regression.
