# Shared index design for search and backlinks

Measured September 14, 2026 on a Linux Cloud Agent (Python 3.12). These numbers
are a baseline, not a performance guarantee. Do not add an on-disk or
in-memory inverted index until a representative vault is slower than the
budgets below.

## What already happens

Every search, tag count, and connection pass walks `Vault.notes()`.
`workspace_notes()` is the same scan with trash and other workspaces removed.
Wiki-link extraction now lives in `links.py` and is fence-aware, so search
and backlinks already share:

- the file-signature cache in `store.py` (reread after one second, or on
  Refresh vault)
- one derived-link parser
- workspace and trash filters

An index that only helps search would drift from backlinks. Any later index
must answer both “which notes match this query?” and “which notes point at
this id/title/heading?”

## Synthetic baseline

200-byte notes, one hub, each note linking to the hub. Cache cleared before
the first search in each vault. Later calls in the same process reuse the
in-memory parse cache, so they run faster.

| Notes | Search one word | Backlinks | Connections | Tag search |
| --- | ---: | ---: | ---: | ---: |
| 50 | 4.5 ms | 1.7 ms | 1.0 ms | 0.7 ms |
| 200 | 8.2 ms | 4.3 ms | 2.8 ms | 2.3 ms |
| 500 | 19.9 ms | 11.3 ms | 6.7 ms | 4.4 ms |

`tests/test_indexing_baseline.py` keeps a 200-note vault under 1.5 s for
search and backlinks so CI machines have room. If a real vault with a few
thousand notes, or 10 MiB notes, exceeds about 200 ms for a typed search or
for opening connections, that is the signal to implement an index.

## What a later index should look like

Build it during `notes()` / `workspace_notes()`, not as a separate file
format:

- token → note ids (words and tags already used by `search.py`)
- link target → note ids (the incoming side of `connections`)
- note id → outgoing targets (cheap to rebuild from the current body)

Invalidate the same way the parse cache does: file signature change, TTL,
or Refresh vault. Keep it process-local. Do not write a new sidecar next to
each Markdown file; ZIP backups and external editors should keep seeing
plain `.md` files.

Encrypted locked notes contribute no tokens and no outgoing targets. Their
id can still appear as an incoming target.

## Out of scope until measured

- SQLite or another query engine
- Incremental watchers
- Cross-workspace link tables
- Unlinked-mention indexes
