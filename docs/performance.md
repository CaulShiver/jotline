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

# Performance measurements — 2026-09-21

Measured on Linux/Python 3.11 with Textual 8.2.8, against merge commit
`99ba1dd`, using the same headless 110×35 fixture as the section above. The
2026-09-20 round optimized opening and inline typing; this round is about the
keys used while outlining. Medians come from three openings, 21 flushes and
15 samples of each structural key per fixture.

## Outline structural editing

Every structural key re-derived the whole note from CommonMark before repainting,
so the cost of pressing Enter grew with the note rather than with the edit.

| Shape | Blocks | Enter | Tab | Shift+Tab | Move | Toggle task |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Flat | 1,000 | 67.3 → 8.5 ms | 61.3 → 6.0 ms | 62.0 → 6.9 ms | 62.7 → 8.2 ms | 64.4 → 8.2 ms |
| Flat | 10,000 | 875 → 87 ms | 884 → 153 ms | 887 → 69 ms | 877 → 76 ms | 887 → 74 ms |
| Nested | 1,000 | 74.3 → 11.5 ms | 71.4 → 9.1 ms | 70.9 → 8.7 ms | 68.7 → 11.1 ms | 69.8 → 10.3 ms |
| Nested | 10,000 | 1,061 → 92 ms | 994 → 74 ms | 1,026 → 79 ms | 1,051 → 90 ms | 1,040 → 88 ms |

## Typing, folding and painting

| Measurement | Shape | Blocks | Before | After |
| --- | --- | ---: | ---: | ---: |
| Edit flush | Flat | 10,000 | 10.68 ms | 3.57 ms |
| Edit flush | Nested | 10,000 | 14.61 ms | 3.81 ms |
| Fold or expand a branch | Nested | 1,000 | 4.26 ms | 2.12 ms |
| Fold or expand a branch | Nested | 10,000 | 55.99 ms | 25.95 ms |
| Paint the visible rows | any | any | ~2.7 ms | ~0.95 ms |

Opening is unchanged. Its samples overlap between the two trees (flat 10,000
before 528–708 ms, after 526–707 ms; nested 10,000 before 1,085–1,259 ms, after
1,152–1,254 ms), and headless scheduling dominates that spread.
[Raw samples](performance-measurements-2026-09-21.json) retain every reading.

## Note list and search box

Measured on the same machine on 2026-09-21 under Python 3.13, before and after
this change rather than against `99ba1dd`, with
`JOTLINE_LIST_BENCHMARK=1 pytest tests/test_list_measurements.py -q -s`, which
types `project`, `alpha` and `note 01` into the search box at a fast typist's
pace and adds up the work the app does for them. Every key rebuilt the whole
note list, and rebuilding measures and wraps every row.

| Notes | Rebuilds for the three queries | Work for the three queries | A refresh whose rows are unchanged |
| ---: | ---: | ---: | ---: |
| 100 | 19 → 3 | 194.9 → 21.7 ms | 9.9 → 2.4 ms |
| 500 | 19 → 3 | 918.0 → 92.0 ms | 47.8 → 10.5 ms |
| 2,000 | 19 → 3 | 4,405 → 426 ms | 189.5 → 45.5 ms |

A refresh that does change the rows costs what it always did (500 notes:
67.2 → 46.7 ms, 2,000 notes: 191.0 → 194.6 ms; the spread between runs is wider
than the difference). The saving is in not doing it, and the note list is
refreshed on every save, so an autosave that leaves every row reading the same
no longer redraws them. Typing now shows results up to 200 ms after the last
key rather than after every key.
[Raw samples](performance-measurements-2026-09-21.json) retain every reading.

## What changed

- A structural edit writes its Markdown to the note straight away, as before,
  and repaints from the tree it just built. Re-deriving that tree from
  CommonMark waits for a pause in editing, so a burst of keys pays for one
  parse instead of one per key. Saving, leaving the outliner, copying, undo,
  block search and the twice-a-second status tick all settle the tree first, so
  nothing reads or writes a note from a tree that has not been re-derived.
- A block's list prefix and its content text are derived from its raw lines and
  now cached against them. Raw lines stay authoritative and are replaced, never
  mutated in place, so the cache cannot outlive them.
- Wrapped rows are cached by their text and the column they wrap into rather
  than by block identity, so re-deriving the tree no longer re-wraps a note that
  did not change. Rows are stored wrapped and gain their bullet gutter only when
  painted, and a painted row is one styled segment instead of a full Rich render.
- A reflow works out whether this pass will add a scrollbar before it wraps.
  Reading the not-yet-laid-out width made the next reflow re-wrap the note.
- Typing in the search box rebuilds the note list once typing pauses rather than
  on every key, and a refresh redraws the list only when the rows themselves
  changed. Code that sets the search box and refreshes with it is unaffected.
- The status line reuses its last whole-note word and tag scan for up to 250 ms
  and catches up when typing stops. The Markdown editor carries its character
  count across each edit instead of re-adding every line's length to decide
  whether to highlight.

## Limits

Opening a large note, and the first settle after a burst of structural edits,
still parse the whole note through CommonMark. There is still no incremental
block parser. A note-list refresh still stats every note in the vault to
validate its cache, which is what an unchanged-row refresh above costs. Nothing about autosave, filesystem sync, conflict detection,
encryption or recovery was relaxed.
